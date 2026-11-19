"""Tests for multi-strategy MIX decryption, sanitization, and mixing."""

import base64
import binascii
import hashlib
import json
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor
lazy from pathlib import Path

import pytest

from mentara._mix_crypto import (
    _WESTWOOD_MODULUS,
    MVMX_ROOT_LABEL,
    MVMX_SECRET_HEX_DEFAULT,
    MIXCrypto,
    _PureAES256GCM,
    _PureBlowfish,
    derive_mvmx_keys,
    extract_mvmx_secret_from_dll,
    fnv1a_32,
    is_pe_binary,
    mt19937_key1024,
    xor_key1024,
)
from mentara.config import MIXDecryptMode
from mentara.errors import OverlayError
from mentara.mix import (
    LMD_FILENAME,
    LMD_ID,
    MIXContext,
    MIXProbeKind,
    MIXStrategy,
    build_lmd_blob,
    mix_id,
    open_mix_archive,
    open_mix_bytes,
    parse_lmd_blob,
    probe_mix_file,
    read_mix_entry_bytes,
    signed_id,
)
from mentara.planner import (
    EntryOrigin,
    LayerSource,
    Materialization,
    build_overlay_plan,
    materialize_synthesized_entry,
    render_virtual_text,
    validate_synthesized_entry,
)


def _pack_standard_mix(entries: dict[str, bytes]) -> bytes:
    lmd_blob = build_lmd_blob(tuple(entries))
    items = [(mix_id(name), payload) for name, payload in entries.items()]
    items.append((LMD_ID, lmd_blob))
    items.sort(key=lambda pair: signed_id(pair[0]))

    total_body = sum(len(payload) for _, payload in items)
    header = bytearray(10 + 12 * len(items))
    struct.pack_into("<IHI", header, 0, 0, len(items), total_body)
    offset = 0
    body_parts: list[bytes] = []
    for idx, (eid, payload) in enumerate(items):
        struct.pack_into("<III", header, 10 + 12 * idx, eid, offset, len(payload))
        offset += len(payload)
        body_parts.append(payload)
    return bytes(header) + b"".join(body_parts)


def _rc4_sub_encrypt(data: bytes, key: bytes) -> bytes:
    state = list(range(256))
    j_idx = 0
    key_len = len(key)
    for i_idx in range(256):
        j_idx = (j_idx + state[i_idx] + key[i_idx % key_len]) & 0xFF
        state[i_idx], state[j_idx] = state[j_idx], state[i_idx]
    out = bytearray(len(data))
    i_idx = 0
    j_idx = 0
    for pos, byte in enumerate(data):
        i_idx = (i_idx + 1) & 0xFF
        j_idx = (j_idx + state[i_idx]) & 0xFF
        state[i_idx], state[j_idx] = state[j_idx], state[i_idx]
        ks_byte = state[(state[i_idx] + state[j_idx]) & 0xFF]
        out[pos] = (byte + ks_byte) & 0xFF
    return bytes(out)


def _pack_fw_crypto_mix(entries: dict[str, bytes]) -> bytes:
    items = [(mix_id(name), payload) for name, payload in entries.items()]
    items.append((LMD_ID, build_lmd_blob(tuple(entries))))
    items.sort(key=lambda pair: signed_id(pair[0]))

    body_parts: list[bytes] = []
    plain_idx = bytearray()
    offset = 0
    for eid, payload in items:
        plain_idx.extend(struct.pack("<III", eid, offset, len(payload)))
        body_parts.append(payload)
        offset += len(payload)
    body = b"".join(body_parts)

    hdr_tail = struct.pack("<HI", len(items), len(body))
    rc4_key = base64.b64encode(hdr_tail)
    enc_idx = _rc4_sub_encrypt(bytes(plain_idx), rc4_key)
    xor_key = mt19937_key1024(fnv1a_32(enc_idx))
    enc_body = xor_key1024(body, xor_key, 0)
    return struct.pack("<I", 0x0004FFFF) + hdr_tail + enc_idx + enc_body


def _pack_mvmx(
    inner_bytes: bytes,
    *,
    secret: bytes | None = None,
    chunk_size: int = 128,
    compress: bool = True,
) -> bytes:
    raw_secret = bytes.fromhex(MVMX_SECRET_HEX_DEFAULT) if secret is None else secret
    salt = bytes(range(16))
    nonce_pfx = b"MVNONCE1"
    policy = b'{"policy":"test"}'
    meta_key, data_key = derive_mvmx_keys(raw_secret, salt)
    meta_cipher = _PureAES256GCM(meta_key)
    data_cipher = _PureAES256GCM(data_key)

    chunks_plain = [
        inner_bytes[pos : pos + chunk_size]
        for pos in range(0, len(inner_bytes), chunk_size)
    ] or [b""]
    flags = 1 if compress else 0

    meta_plain = json.dumps(
        {"original_sha256": hashlib.sha256(inner_bytes).hexdigest()}
    ).encode("utf-8")
    meta_ct_len = len(meta_plain) + 16

    hdr = bytearray(0x78)
    hdr[:8] = b"MVMXV1\x00\x00"
    struct.pack_into(
        "<HHIIIIQII",
        hdr,
        8,
        1,
        0,
        0x78,
        flags,
        chunk_size,
        len(chunks_plain),
        len(inner_bytes),
        meta_ct_len,
        len(policy),
    )
    hdr[0x2C:0x3C] = salt
    hdr[0x3C:0x44] = nonce_pfx
    hdr[0x44:0x54] = b"MVMX_HEADER_PAD!"
    hdr_sha = hashlib.sha256(bytes(hdr[:0x54]) + b"\x00" * 36 + policy).digest()
    hdr[0x54:0x74] = hdr_sha
    struct.pack_into("<I", hdr, 0x74, binascii.crc32(hdr[:0x74]) & 0xFFFFFFFF)

    aad_mid = bytes(hdr[0x44:0x74])
    meta_ct = meta_cipher.encrypt(
        nonce_pfx + b"\xff\xff\xff\xff",
        b"MVX-META-v1\x00" + aad_mid,
        meta_plain,
    )

    chunk_stream = bytearray()
    for idx, plain in enumerate(chunks_plain):
        stored = zlib.compress(plain) if compress else plain
        ct = data_cipher.encrypt(
            nonce_pfx + struct.pack(">I", idx),
            b"MVX-CHUNK-v1\x00"
            + aad_mid
            + struct.pack("<III", idx, len(plain), len(stored)),
            stored,
        )
        chunk_stream.extend(struct.pack("<III", len(plain), len(stored), len(ct)))
        chunk_stream.extend(ct)

    return bytes(hdr) + policy + meta_ct + bytes(chunk_stream)


def _pack_s4_obfuscated(entries: dict[str, bytes]) -> bytes:
    items = [(mix_id(name), payload) for name, payload in entries.items()]
    orphaned_lmd = build_lmd_blob(tuple(entries))
    body = bytearray()
    rows: list[tuple[int, int, int]] = []
    for eid, payload in items:
        rows.append((eid, len(body), len(payload)))
        body.extend(payload)
    rows.append((mix_id("fake_decoy.bin"), 3, 12))
    rows.append((LMD_ID, 0xFFFFFFFF, 0xFFFFFFFF))
    rows.sort(key=lambda item: signed_id(item[0]))
    header = struct.pack("<IHI", 0, len(rows), 0x1234)
    index = b"".join(struct.pack("<III", *row) for row in rows)
    return header + index + bytes(body) + orphaned_lmd


def _build_minimal_pe32_mvloader(secret: bytes) -> bytes:
    """Build a synthetic PE32 DLL embedding `MVMX_ROOT_LABEL` + key."""
    image_base = 0x10000000
    pe_off = 0x80
    opt_sz = 0xE0
    sec_off = pe_off + 24 + opt_sz

    text_rva = 0x1000
    text_raw = 0x200
    text_sz = 0x200
    rdata_rva = 0x2000
    rdata_raw = 0x400
    rdata_sz = 0x200

    buf = bytearray(rdata_raw + rdata_sz)
    buf[:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, pe_off)
    buf[pe_off : pe_off + 4] = b"PE\x00\x00"
    struct.pack_into("<H", buf, pe_off + 6, 2)
    struct.pack_into("<H", buf, pe_off + 20, opt_sz)
    opt_off = pe_off + 24
    struct.pack_into("<H", buf, opt_off, 0x10B)
    struct.pack_into("<I", buf, opt_off + 28, image_base)

    # Section 0: .text
    buf[sec_off : sec_off + 5] = b".text"
    struct.pack_into("<4I", buf, sec_off + 8, text_sz, text_rva, text_sz, text_raw)
    # Section 1: .rdata
    sec1 = sec_off + 40
    buf[sec1 : sec1 + 6] = b".rdata"
    struct.pack_into("<4I", buf, sec1 + 8, rdata_sz, rdata_rva, rdata_sz, rdata_raw)

    label_off = rdata_raw + 0x10
    secret_off = rdata_raw + 0x40
    buf[label_off : label_off + len(MVMX_ROOT_LABEL)] = MVMX_ROOT_LABEL
    buf[secret_off : secret_off + len(secret)] = secret

    label_va = image_base + rdata_rva + 0x10
    secret_va = image_base + rdata_rva + 0x40
    # Fake x86 instructions referencing label_va then push secret_va.
    code = (
        b"\x68"
        + struct.pack("<I", label_va)
        + b"\x90\x90\x90\x90"
        + b"\x6a\x20\x68"
        + struct.pack("<I", secret_va)
    )
    buf[text_raw : text_raw + len(code)] = code
    return bytes(buf)


def test_mix_id_and_lmd_round_trip() -> None:
    assert mix_id("rulesmo.ini") == 0xE8DF0937
    assert mix_id("uimd.ini") == 0xE99E00A7
    assert mix_id("artmo.ini") == 0x062DC483
    assert LMD_ID == 0x366E051F
    assert mix_id(LMD_FILENAME) == LMD_ID

    der_pubkey = base64.b64decode(
        "AihRvNoIbTn85FZRYNZRcT+i6KpU+maCsEqr3Q5q+LDB5tH7Tz2qQ38V"
    )
    assert der_pubkey[:2] == b"\x02\x28"
    assert int.from_bytes(der_pubkey[2:], "big") == _WESTWOOD_MODULUS

    lmd_blob = build_lmd_blob(("rulesmo.ini", "uimd.ini"))
    names, game = parse_lmd_blob(lmd_blob)
    assert game == 5
    assert "rulesmo.ini" in names
    assert "uimd.ini" in names


def test_open_mix_handles_s1_standard_and_s2b_fw_crypto(tmp_path: Path) -> None:
    s1_path = tmp_path / "s1.mix"
    s1_path.write_bytes(
        _pack_standard_mix(
            {
                "uimd.ini": b"[ToolTips]\r\nExtendedToolTips=no\r\n",
                "rulesmo.ini": b"[General]\r\nName=MO\r\n",
            }
        )
    )
    assert probe_mix_file(s1_path) is MIXProbeKind.STANDARD
    parsed_s1 = open_mix_archive(s1_path)
    assert parsed_s1.strategy is MIXStrategy.STANDARD
    assert parsed_s1.lmd_names[mix_id("uimd.ini")] == "uimd.ini"
    assert (
        read_mix_entry_bytes(parsed_s1, mix_id("rulesmo.ini"))
        == b"[General]\r\nName=MO\r\n"
    )

    payload = b"[Phobos]\r\nRealTimeTimers=true\r\n"
    s2b_path = tmp_path / "s2b.mix"
    s2b_path.write_bytes(_pack_fw_crypto_mix({"ra2mo.ini": payload}))
    assert probe_mix_file(s2b_path) is MIXProbeKind.FW_CRYPTO
    parsed_s2b = open_mix_archive(s2b_path)
    assert parsed_s2b.strategy is MIXStrategy.FW_CRYPTO
    assert read_mix_entry_bytes(parsed_s2b, mix_id("ra2mo.ini")) == payload


def test_open_mix_s2_mvmx_multichunk_and_openssl_pure_parity(tmp_path: Path) -> None:
    # Verify OpenSSL and pure-Python AES-256-GCM agree identically.
    key = bytes(range(32))
    nonce = b"123456789012"
    aad = b"aad-header-data"
    pt = b"Mentara AES-256-GCM parity payload " * 17
    ct = _PureAES256GCM(key).encrypt(nonce, aad, pt)
    assert MIXCrypto(force_pure=True).aes_gcm_decrypt(key, nonce, aad, ct) == pt
    assert MIXCrypto(force_pure=False).aes_gcm_decrypt(key, nonce, aad, ct) == pt

    # Wrap an S4-obfuscated MIX inside multi-chunk zlib MVMXV1.
    inner_s4 = _pack_s4_obfuscated(
        {
            "rulesmo.ini": b"[General]\r\nName=Multiverse\r\n" + b";" * 80,
            "uimd.ini": b"[ToolTips]\r\nExtendedToolTips=no\r\n" + b";" * 80,
        }
    )
    for compressed in (True, False):
        mvmx_path = tmp_path / f"mv_{compressed}.mix"
        mvmx_path.write_bytes(_pack_mvmx(inner_s4, chunk_size=64, compress=compressed))
        assert probe_mix_file(mvmx_path) is MIXProbeKind.MVMX
        parsed = open_mix_archive(mvmx_path)
        assert parsed.strategy is MIXStrategy.MVMX
        assert parsed.lmd_names[mix_id("rulesmo.ini")] == "rulesmo.ini"
        rules = read_mix_entry_bytes(parsed, mix_id("rulesmo.ini"))
        assert rules is not None
        assert b"Name=Multiverse" in rules


def test_mvmx_dynamic_key_extraction_from_overlay_pe32_dll(tmp_path: Path) -> None:
    custom_secret = bytes(range(0xA0, 0xC0))
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    base_dir.mkdir()
    layer_dir.mkdir()

    dll_path = layer_dir / "MVLoader.dll"
    dll_path.write_bytes(_build_minimal_pe32_mvloader(custom_secret))
    assert is_pe_binary(dll_path)
    assert extract_mvmx_secret_from_dll(dll_path) == custom_secret

    inner = _pack_standard_mix({"custom.ini": b"[Custom]\r\nKey=SecretOK\r\n"})
    (layer_dir / "expandmo92.mix").write_bytes(
        _pack_mvmx(inner, secret=custom_secret, chunk_size=48)
    )

    plan = build_overlay_plan(
        (
            LayerSource("base", base_dir, EntryOrigin.BASE),
            LayerSource("layer:mod", layer_dir, EntryOrigin.LAYER),
        ),
    )
    entry = plan.lookup_case_insensitive(Path("expandmo92.mix"))
    assert entry is not None
    assert entry.materialization is Materialization.MIX
    assert entry.mix_probe is MIXProbeKind.MVMX

    validate_synthesized_entry(entry, context=plan.mix_context)
    assert "Key=SecretOK" in render_virtual_text(
        plan, Path("expandmo92.mix/custom.ini")
    )

    out_mix = tmp_path / "out" / "expandmo92.mix"
    materialize_synthesized_entry(entry, out_mix, context=plan.mix_context)
    reopened = open_mix_archive(out_mix)
    assert reopened.strategy is MIXStrategy.STANDARD
    assert (
        read_mix_entry_bytes(reopened, mix_id("custom.ini"))
        == b"[Custom]\r\nKey=SecretOK\r\n"
    )

    # Explicit hex override also works without MVLoader.dll.
    ctx = MIXContext(mvmx_secret_hex=custom_secret.hex())
    direct = open_mix_archive(layer_dir / "expandmo92.mix", context=ctx)
    assert read_mix_entry_bytes(direct, mix_id("custom.ini")) == (
        b"[Custom]\r\nKey=SecretOK\r\n"
    )


def test_open_mix_s4_sanitize_removes_sentinels_decoys_and_carves_lmd(
    tmp_path: Path,
) -> None:
    body_a = b"[General]\r\nVeteranRatio=4.5\r\n" + b";" * 40
    body_b = b"[ToolTips]\r\nExtendedToolTips=no\r\n" + b";" * 40
    s4_path = tmp_path / "expandmo99.mix"
    s4_path.write_bytes(
        _pack_s4_obfuscated({"rulesmo.ini": body_a, "uimd.ini": body_b})
    )

    assert probe_mix_file(s4_path) is MIXProbeKind.OBFUSCATED
    parsed = open_mix_archive(s4_path)
    assert parsed.strategy is MIXStrategy.SANITIZE
    entry_ids = {item.id for item in parsed.entries}
    assert mix_id("rulesmo.ini") in entry_ids
    assert mix_id("uimd.ini") in entry_ids
    assert LMD_ID not in entry_ids
    assert parsed.lmd_names[mix_id("rulesmo.ini")] == "rulesmo.ini"
    assert parsed.lmd_names[mix_id("uimd.ini")] == "uimd.ini"
    assert read_mix_entry_bytes(parsed, mix_id("rulesmo.ini")) == body_a


def test_open_mix_s5_shifted_header_and_pe_guard(tmp_path: Path) -> None:
    plain = _pack_standard_mix({"a.ini": b"[A]\r\nX=1\r\n", "b.ini": b"[B]\r\nY=2\r\n"})
    shifted_std = tmp_path / "shifted_std.mix"
    shifted_std.write_bytes(b"JUNK_PREFIX_1234" + plain)
    assert probe_mix_file(shifted_std) is MIXProbeKind.OBFUSCATED
    parsed_std = open_mix_archive(shifted_std)
    assert parsed_std.strategy is MIXStrategy.SHIFTED
    assert read_mix_entry_bytes(parsed_std, mix_id("a.ini")) == b"[A]\r\nX=1\r\n"

    shifted_mv = tmp_path / "shifted_mv.mix"
    shifted_mv.write_bytes(b"LEAD" + _pack_mvmx(plain, chunk_size=64))
    assert probe_mix_file(shifted_mv) is MIXProbeKind.MVMX
    parsed_mv = open_mix_archive(shifted_mv)
    assert parsed_mv.strategy is MIXStrategy.SHIFTED
    assert read_mix_entry_bytes(parsed_mv, mix_id("b.ini")) == b"[B]\r\nY=2\r\n"

    pe_mix = tmp_path / "syringe_ext.mix"
    pe_mix.write_bytes(_build_minimal_pe32_mvloader(bytes(32)))
    assert probe_mix_file(pe_mix) is MIXProbeKind.PE_BINARY
    with pytest.raises(OverlayError, match="PE executable/DLL"):
        open_mix_archive(pe_mix)


def test_pure_blowfish_encrypt_decrypt_round_trip() -> None:
    cipher = _PureBlowfish(b"WestwoodBlowfishTestKey56BytesLongForTestingMIX!")
    left, right = cipher.encrypt_pair(0x12345678, 0x9ABCDEF0)
    block = struct.pack(">II", left, right)
    decrypted = cipher.decrypt_ecb(block)
    assert struct.unpack(">II", decrypted) == (0x12345678, 0x9ABCDEF0)


def test_standalone_overlay_mix_modes_and_pe_passthrough(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    base_dir.mkdir()
    layer_dir.mkdir()

    base_s4 = _pack_s4_obfuscated(
        {"base.ini": b"[Base]\r\nK=1\r\n" + b";" * 40, "two.ini": b"2" * 50}
    )
    (base_dir / "base_obf.mix").write_bytes(base_s4)

    (layer_dir / "mvmx_mod.mix").write_bytes(
        _pack_mvmx(_pack_standard_mix({"m.ini": b"[M]\r\nOk=yes\r\n"}))
    )
    (layer_dir / "fw_mod.mix").write_bytes(
        _pack_fw_crypto_mix({"f.ini": b"[F]\r\nOk=yes\r\n"})
    )
    (layer_dir / "clean.mix").write_bytes(
        _pack_standard_mix({"c.ini": b"[C]\r\nOk=yes\r\n"})
    )
    (layer_dir / "disguised_dll.mix").write_bytes(
        _build_minimal_pe32_mvloader(bytes(32))
    )

    sources = (
        LayerSource("base", base_dir, EntryOrigin.BASE),
        LayerSource("layer:ext", layer_dir, EntryOrigin.LAYER),
    )

    # Default MIXDecryptMode.LAYERS: decrypts overlay MIXes only.
    plan_layers = build_overlay_plan(sources, mix_decrypt=MIXDecryptMode.LAYERS)
    by_name = {e.relative_path.name: e for e in plan_layers.entries}
    assert by_name["base_obf.mix"].materialization is Materialization.SYMLINK
    assert by_name["mvmx_mod.mix"].materialization is Materialization.MIX
    assert by_name["mvmx_mod.mix"].mix_probe is MIXProbeKind.MVMX
    assert by_name["fw_mod.mix"].materialization is Materialization.MIX
    assert by_name["fw_mod.mix"].mix_probe is MIXProbeKind.FW_CRYPTO
    assert by_name["clean.mix"].materialization is Materialization.SYMLINK
    assert by_name["disguised_dll.mix"].materialization is Materialization.SYMLINK

    # MIXDecryptMode.ALL: also decrypts obfuscated/encrypted base MIXes.
    plan_all = build_overlay_plan(sources, mix_decrypt=MIXDecryptMode.ALL)
    by_name_all = {e.relative_path.name: e for e in plan_all.entries}
    assert by_name_all["base_obf.mix"].materialization is Materialization.MIX
    assert by_name_all["base_obf.mix"].mix_probe is MIXProbeKind.OBFUSCATED
    assert by_name_all["disguised_dll.mix"].materialization is Materialization.SYMLINK

    # MIXDecryptMode.PATCHED: leaves standalone overlay MIXes untouched.
    plan_patched = build_overlay_plan(sources, mix_decrypt=MIXDecryptMode.PATCHED)
    by_name_patched = {e.relative_path.name: e for e in plan_patched.entries}
    assert by_name_patched["mvmx_mod.mix"].materialization is Materialization.SYMLINK
    assert by_name_patched["fw_mod.mix"].materialization is Materialization.SYMLINK


def test_nested_encrypted_mix_inside_standard_overlay_is_recursively_decrypted(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    base_dir.mkdir()
    layer_dir.mkdir()

    inner_mv = _pack_mvmx(
        _pack_standard_mix({"secret.ini": b"[Inner]\r\nMV=1\r\n"}),
        chunk_size=64,
    )
    inner_fw = _pack_fw_crypto_mix({"fw.ini": b"[Inner]\r\nFW=1\r\n"})
    wrapper_path = layer_dir / "wrapper.mix"
    wrapper_path.write_bytes(
        _pack_standard_mix(
            {
                "inner_mv.mix": inner_mv,
                "inner_fw.mix": inner_fw,
                "readme.txt": b"keep",
            }
        )
    )

    assert probe_mix_file(wrapper_path) is MIXProbeKind.NESTED_ENCRYPTED
    plan = build_overlay_plan(
        (
            LayerSource("base", base_dir, EntryOrigin.BASE),
            LayerSource("layer:mod", layer_dir, EntryOrigin.LAYER),
        ),
    )
    entry = plan.lookup_case_insensitive(Path("wrapper.mix"))
    assert entry is not None
    assert entry.materialization is Materialization.MIX
    assert entry.mix_probe is MIXProbeKind.NESTED_ENCRYPTED

    out_mix = tmp_path / "out" / "wrapper.mix"
    materialize_synthesized_entry(entry, out_mix, context=plan.mix_context)
    assert probe_mix_file(out_mix) is MIXProbeKind.STANDARD

    reopened = open_mix_archive(out_mix)
    mv_bytes = read_mix_entry_bytes(reopened, mix_id("inner_mv.mix"))
    fw_bytes = read_mix_entry_bytes(reopened, mix_id("inner_fw.mix"))
    assert mv_bytes is not None
    assert fw_bytes is not None
    mv_inner = open_mix_bytes(mv_bytes)
    fw_inner = open_mix_bytes(fw_bytes)
    assert mv_inner.strategy is MIXStrategy.STANDARD
    assert fw_inner.strategy is MIXStrategy.STANDARD
    assert (
        read_mix_entry_bytes(mv_inner, mix_id("secret.ini")) == b"[Inner]\r\nMV=1\r\n"
    )
    assert read_mix_entry_bytes(fw_inner, mix_id("fw.ini")) == b"[Inner]\r\nFW=1\r\n"


def test_nested_mix_container_patching_and_patch_mix(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    layer1 = tmp_path / "layer1"
    layer2 = tmp_path / "layer2"
    base_dir.mkdir()
    (layer1 / "ra2md.mix" / "localmd.mix").mkdir(parents=True)
    (layer2 / "ra2md.mix").mkdir(parents=True)

    nested_local = _pack_mvmx(
        _pack_standard_mix(
            {
                "rulesmd.ini": b"[General]\r\nSpeed=1\r\n",
                "keep.ini": b"[Keep]\r\nYes=1\r\n",
            }
        ),
        chunk_size=64,
    )
    (base_dir / "ra2md.mix").write_bytes(
        _pack_standard_mix({"localmd.mix": nested_local})
    )
    (layer1 / "ra2md.mix" / "localmd.mix" / "rulesmd.patch.ini").write_text(
        "[General]\nSpeed=9\n",
        encoding="utf-8",
    )
    (layer2 / "ra2md.mix" / "localmd.patch.mix").write_bytes(
        _pack_fw_crypto_mix({"injected.ini": b"[Injected]\r\nOk=yes\r\n"})
    )

    plan = build_overlay_plan(
        (
            LayerSource("base", base_dir, EntryOrigin.BASE),
            LayerSource("layer:one", layer1, EntryOrigin.LAYER),
            LayerSource("layer:two", layer2, EntryOrigin.LAYER),
        ),
    )

    rendered = render_virtual_text(plan, Path("ra2md.mix/localmd.mix/rulesmd.ini"))
    assert "Speed=9\r\n" in rendered

    entry = plan.lookup_case_insensitive(Path("ra2md.mix"))
    assert entry is not None
    assert entry.materialization is Materialization.MIX
    validate_synthesized_entry(entry, context=plan.mix_context)

    out_mix = tmp_path / "out" / "ra2md.mix"
    materialize_synthesized_entry(entry, out_mix, context=plan.mix_context)
    outer = open_mix_archive(out_mix)
    assert outer.strategy is MIXStrategy.STANDARD
    local_bytes = read_mix_entry_bytes(outer, mix_id("localmd.mix"))
    assert local_bytes is not None
    local = open_mix_bytes(local_bytes)
    assert local.strategy is MIXStrategy.STANDARD
    assert (
        read_mix_entry_bytes(local, mix_id("rulesmd.ini"))
        == b"[General]\r\nSpeed=9\r\n"
    )
    assert read_mix_entry_bytes(local, mix_id("keep.ini")) == b"[Keep]\r\nYes=1\r\n"
    assert (
        read_mix_entry_bytes(local, mix_id("injected.ini"))
        == b"[Injected]\r\nOk=yes\r\n"
    )

    # Non-.mix subdirectory inside a MIX container is rejected cleanly.
    bad_layer = tmp_path / "bad_layer"
    (bad_layer / "ra2md.mix" / "not_a_mix").mkdir(parents=True)
    (bad_layer / "ra2md.mix" / "not_a_mix" / "file.ini").write_text(
        "x",
        encoding="utf-8",
    )
    with pytest.raises(OverlayError, match=r"invalid non-\.mix subdirectory"):
        build_overlay_plan(
            (
                LayerSource("base", base_dir, EntryOrigin.BASE),
                LayerSource("layer:bad", bad_layer, EntryOrigin.LAYER),
            ),
        )


def test_multi_layer_mix_op_strict_precedence_and_case_matching(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer1 = tmp_path / "layer1"
    layer2 = tmp_path / "layer2"
    layer3 = tmp_path / "layer3"
    base_dir.mkdir()
    (layer1 / "expandmo99.mix").mkdir(parents=True)
    layer2.mkdir()
    (layer3 / "expandmo99.mix").mkdir(parents=True)

    # Uppercase base filename; lowercase overlay container & .patch.mix.
    (base_dir / "EXPANDMO99.MIX").write_bytes(
        _pack_standard_mix(
            {
                "rulesmo.ini": b"[General]\r\nVal=1\r\nBaseOnly=yes\r\n",
                "untouched.ini": b"[Keep]\r\nA=1\r\n",
            }
        )
    )
    (layer1 / "expandmo99.mix" / "rulesmo.patch.ini").write_text(
        "[General]\nVal=2\nFromL1=yes\n",
        encoding="utf-8",
    )
    (layer2 / "expandmo99.patch.mix").write_bytes(
        _pack_mvmx(
            _pack_standard_mix(
                {"rulesmo.ini": b"[General]\r\nVal=10\r\nFromL2=yes\r\n"}
            ),
            chunk_size=64,
        )
    )
    (layer3 / "expandmo99.mix" / "rulesmo.patch.ini").write_text(
        "[General]\nVal=20\n",
        encoding="utf-8",
    )

    plan = build_overlay_plan(
        (
            LayerSource("base", base_dir, EntryOrigin.BASE),
            LayerSource("layer:one", layer1, EntryOrigin.LAYER),
            LayerSource("layer:two", layer2, EntryOrigin.LAYER),
            LayerSource("layer:three", layer3, EntryOrigin.LAYER),
        ),
    )

    # Canonical path kept; consumed .patch.mix & mismatched dir hidden.
    entry = plan.lookup_case_insensitive(Path("expandmo99.mix"))
    assert entry is not None
    assert entry.relative_path == Path("EXPANDMO99.MIX")
    assert Path("expandmo99.patch.mix") in plan.hidden_paths
    assert Path("expandmo99.mix") in plan.hidden_paths

    rendered = render_virtual_text(plan, Path("expandmo99.mix/rulesmo.ini"))
    assert "Val=20\r\n" in rendered
    assert "FromL2=yes\r\n" in rendered
    assert "FromL1" not in rendered

    out_mix = tmp_path / "out" / "EXPANDMO99.MIX"
    materialize_synthesized_entry(entry, out_mix, context=plan.mix_context)
    reopened = open_mix_archive(out_mix)
    rules = read_mix_entry_bytes(reopened, mix_id("rulesmo.ini"))
    assert rules is not None
    assert b"Val=20\r\n" in rules
    assert b"FromL2=yes\r\n" in rules
    assert b"FromL1" not in rules
    assert (
        read_mix_entry_bytes(reopened, mix_id("untouched.ini")) == b"[Keep]\r\nA=1\r\n"
    )


def test_overlay_replaces_base_with_encrypted_mix_then_higher_layer_patches(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_mod = tmp_path / "layer_mod"
    layer_phobos = tmp_path / "layer_phobos"
    base_dir.mkdir()
    layer_mod.mkdir()
    (layer_phobos / "expandmo99.mix").mkdir(parents=True)

    (base_dir / "expandmo99.mix").write_bytes(
        _pack_standard_mix({"rulesmo.ini": b"[General]\r\nBaseTag=1\r\nSpeed=1\r\n"})
    )
    (layer_mod / "expandmo99.mix").write_bytes(
        _pack_mvmx(
            _pack_standard_mix(
                {"rulesmo.ini": b"[General]\r\nModTag=1\r\nSpeed=2\r\n"}
            ),
            chunk_size=64,
        )
    )
    (layer_phobos / "expandmo99.mix" / "rulesmo.patch.ini").write_text(
        "[General]\nSpeed=5\n",
        encoding="utf-8",
    )

    plan = build_overlay_plan(
        (
            LayerSource("base", base_dir, EntryOrigin.BASE),
            LayerSource("layer:mod", layer_mod, EntryOrigin.LAYER),
            LayerSource("layer:phobos", layer_phobos, EntryOrigin.LAYER),
        ),
    )

    rendered = render_virtual_text(plan, Path("expandmo99.mix/rulesmo.ini"))
    assert "ModTag=1\r\n" in rendered
    assert "Speed=5\r\n" in rendered
    assert "BaseTag" not in rendered

    entry = plan.lookup_case_insensitive(Path("expandmo99.mix"))
    assert entry is not None
    out_mix = tmp_path / "out" / "expandmo99.mix"
    materialize_synthesized_entry(entry, out_mix, context=plan.mix_context)
    reopened = open_mix_archive(out_mix)
    assert reopened.strategy is MIXStrategy.STANDARD
    rules = read_mix_entry_bytes(reopened, mix_id("rulesmo.ini"))
    assert rules == b"[General]\r\nModTag=1\r\nSpeed=5\r\n"


def test_mix_crypto_concurrent_decryption_preserves_invariants() -> None:
    crypto = MIXCrypto(force_pure=False)
    aes_key = bytes(range(32))
    bf_key = b"WestwoodBlowfishConcurrentKey56BytesLongForTesting!"
    bf_cipher = _PureBlowfish(bf_key)
    left, right = bf_cipher.encrypt_pair(0xCAFEBABE, 0xDEADBEEF)
    bf_block = struct.pack(">II", left, right)
    bf_expected = struct.pack(">II", 0xCAFEBABE, 0xDEADBEEF)

    samples = [
        (
            f"nonce-{index:06d}".encode("ascii"),
            f"aad-{index}".encode("ascii"),
            f"payload-{index}-".encode("ascii") * 12,
        )
        for index in range(32)
    ]
    ciphertexts = [
        (nonce, aad, plain, _PureAES256GCM(aes_key).encrypt(nonce, aad, plain))
        for nonce, aad, plain in samples
    ]

    def _verify_worker(item: tuple[bytes, bytes, bytes, bytes]) -> bool:
        nonce, aad, expected_plain, ciphertext = item
        aes_ok = (
            crypto.aes_gcm_decrypt(aes_key, nonce, aad, ciphertext) == expected_plain
        )
        bf_ok = crypto.blowfish_ecb_decrypt(bf_key, bf_block) == bf_expected
        return aes_ok and bf_ok

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_verify_worker, ciphertexts))

    assert all(results)
