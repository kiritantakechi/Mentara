"""Tests for multi-strategy MIX decryption, sanitization, and mixing."""

import base64
import struct
lazy from pathlib import Path

from mentara.mix import (
    LMD_ID,
    MixStrategy,
    _fnv1a_32,
    _mt19937_key1024,
    _PureBlowfish,
    _xor_key1024,
    build_lmd_blob,
    mix_id,
    open_mix_archive,
    parse_lmd_blob,
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


def test_mix_id_and_lmd_round_trip() -> None:
    assert mix_id("rulesmo.ini") == 0xE8DF0937
    assert mix_id("uimd.ini") == 0xE99E00A7
    assert mix_id("artmo.ini") == 0x062DC483
    assert LMD_ID == 0x366E051F

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
    parsed_s1 = open_mix_archive(s1_path)
    assert parsed_s1.strategy is MixStrategy.STANDARD
    assert parsed_s1.lmd_names[mix_id("uimd.ini")] == "uimd.ini"
    assert (
        read_mix_entry_bytes(parsed_s1, mix_id("rulesmo.ini"))
        == b"[General]\r\nName=MO\r\n"
    )

    # Build an S2b CryptoRuntime (0x0004FFFF) encrypted MIX.
    payload = b"[Phobos]\r\nRealTimeTimers=true\r\n"
    eid = mix_id("ra2mo.ini")
    hdr_tail = struct.pack("<HI", 1, len(payload))
    rc4_key = base64.b64encode(hdr_tail)
    plain_idx = struct.pack("<III", eid, 0, len(payload))
    enc_idx = _rc4_sub_encrypt(plain_idx, rc4_key)
    xor_key = _mt19937_key1024(_fnv1a_32(enc_idx))
    enc_body = _xor_key1024(payload, xor_key, 0)

    s2b_path = tmp_path / "s2b.mix"
    s2b_path.write_bytes(struct.pack("<I", 0x0004FFFF) + hdr_tail + enc_idx + enc_body)
    parsed_s2b = open_mix_archive(s2b_path)
    assert parsed_s2b.strategy is MixStrategy.FW_CRYPTO
    assert read_mix_entry_bytes(parsed_s2b, eid) == payload


def test_open_mix_s4_sanitize_removes_sentinels_decoys_and_carves_lmd(
    tmp_path: Path,
) -> None:
    body_a = b"[General]\r\nVeteranRatio=4.5\r\n" + b";" * 40
    body_b = b"[ToolTips]\r\nExtendedToolTips=no\r\n" + b";" * 40
    orphaned_lmd = build_lmd_blob(("rulesmo.ini", "uimd.ini"))

    id_a = mix_id("rulesmo.ini")
    id_b = mix_id("uimd.ini")
    id_decoy = mix_id("fake_decoy.bin")

    # S4 obfuscated MIX: fake body_size (0x1234), 0xFFFFFFFF sentinel on
    # LMD_ID, an overlapping decoy entry, and orphaned LMD in the body.
    raw_entries = sorted(
        [
            (id_a, 0, len(body_a)),
            (id_b, len(body_a), len(body_b)),
            (id_decoy, 3, 12),
            (LMD_ID, 0xFFFFFFFF, 0xFFFFFFFF),
        ],
        key=lambda item: signed_id(item[0]),
    )
    header = struct.pack("<IHI", 0, len(raw_entries), 0x1234)
    index = b"".join(struct.pack("<III", *row) for row in raw_entries)
    s4_path = tmp_path / "expandmo99.mix"
    s4_path.write_bytes(header + index + body_a + body_b + orphaned_lmd)

    parsed = open_mix_archive(s4_path)
    assert parsed.strategy is MixStrategy.SANITIZE
    entry_ids = {item.id for item in parsed.entries}
    assert id_a in entry_ids
    assert id_b in entry_ids
    assert LMD_ID not in entry_ids
    assert parsed.lmd_names[id_a] == "rulesmo.ini"
    assert parsed.lmd_names[id_b] == "uimd.ini"
    assert read_mix_entry_bytes(parsed, id_a) == body_a


def test_pure_blowfish_encrypt_decrypt_round_trip() -> None:
    cipher = _PureBlowfish(b"WestwoodBlowfishTestKey56BytesLongForTestingMIX!")
    left, right = cipher._encrypt_pair(0x12345678, 0x9ABCDEF0)
    block = struct.pack(">II", left, right)
    decrypted = cipher.decrypt_ecb(block)
    assert struct.unpack(">II", decrypted) == (0x12345678, 0x9ABCDEF0)


def test_overlay_plan_composes_mix_directory_patches_and_files(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    base_dir.mkdir()
    (layer_dir / "expandmo99.mix").mkdir(parents=True)

    (base_dir / "expandmo99.mix").write_bytes(
        _pack_standard_mix(
            {
                "uimd.ini": (
                    b"[Sidebar]\r\nCreditsIndicator.MaxStep=143\r\n"
                    b"[ToolTips]\r\nExtendedToolTips=no\r\n"
                ),
                "rulesmo.ini": b"[General]\r\nBuildingProductionQueue=false\r\n",
            }
        )
    )
    (layer_dir / "expandmo99.mix" / "uimd.patch.ini").write_text(
        "[Sidebar]\nCreditsIndicator.MaxStep=500\n[ToolTips]\nExtendedToolTips=true\n",
        encoding="utf-8",
    )
    (layer_dir / "expandmo99.mix" / "rulesmo.patch.ini").write_text(
        "[General]\nBuildingProductionQueue=true\n",
        encoding="utf-8",
    )
    (layer_dir / "expandmo99.mix" / "extra.ini").write_bytes(
        b"[Extra]\r\nLoaded=yes\r\n"
    )

    plan = build_overlay_plan(
        (
            LayerSource("base", base_dir, EntryOrigin.BASE),
            LayerSource("layer:phobos", layer_dir, EntryOrigin.LAYER),
        ),
    )

    assert Path("expandmo99.mix") not in plan.directories
    mix_entry = plan.lookup_case_insensitive(Path("expandmo99.mix"))
    assert mix_entry is not None
    assert mix_entry.materialization is Materialization.MIX
    assert len(mix_entry.mix_patches) == 2
    assert len(mix_entry.mix_files) == 1

    rendered_uimd = render_virtual_text(
        plan,
        Path("expandmo99.mix/uimd.ini"),
    )
    assert "CreditsIndicator.MaxStep=500\r\n" in rendered_uimd
    assert "ExtendedToolTips=true\r\n" in rendered_uimd

    out_mix = tmp_path / "merged" / "expandmo99.mix"
    materialize_synthesized_entry(mix_entry, out_mix)
    reopened = open_mix_archive(out_mix)
    assert reopened.strategy is MixStrategy.STANDARD
    assert (
        read_mix_entry_bytes(reopened, mix_id("extra.ini"))
        == b"[Extra]\r\nLoaded=yes\r\n"
    )
    patched_rules = read_mix_entry_bytes(reopened, mix_id("rulesmo.ini"))
    assert patched_rules is not None
    assert b"BuildingProductionQueue=true\r\n" in patched_rules
