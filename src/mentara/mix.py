"""Multi-strategy MIX archive decryption, sanitization, and mixing."""

import base64
import binascii
import bisect
import mmap
import re
import struct
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final
lazy from collections.abc import Callable, Mapping, Sequence

from mentara.errors import OverlayError
from mentara.patcher import PatchSpec, apply_patch_chain

__all__ = [
    "LMD_FILENAME",
    "LMD_ID",
    "MIX_PATCH_SUFFIX",
    "MixArchiveSpec",
    "MixEntry",
    "MixFileSpec",
    "MixPatchSpec",
    "MixStrategy",
    "ParsedMix",
    "build_lmd_blob",
    "compose_mix_archive",
    "mix_id",
    "open_mix_archive",
    "parse_lmd_blob",
    "read_mix_entry_bytes",
    "render_mix_member_text",
    "signed_id",
]

LMD_FILENAME: Final[str] = "local mix database.dat"
MIX_PATCH_SUFFIX: Final[str] = ".patch.mix"

_XCC_ID: Final[bytes] = b"XCC by Olaf van der Spek\x1a\x04\x17\x27\x10\x19\x80\x00"
_XCC_ID_LEN: Final[int] = 32
_LMD_HEADER_SIZE: Final[int] = 52
_LMD_DEFAULT_GAME: Final[int] = 5
_LMD_MAX_SIZE: Final[int] = 16 << 20

_FLAG_CHECKSUM: Final[int] = 0x00010000
_FLAG_ENCRYPTED: Final[int] = 0x00020000
_FLAG_FW_CRYPTO: Final[int] = 0x00040000
_FW_LOW_MASK: Final[int] = 0xFFFF

_WESTWOOD_PUBKEY_B64: Final[str] = (
    "AihRvNoIbTn85FZRYNZRcT+i6KpU+maCsEqr3Q5q+LDB5tH7Tz2qQ38V"
)
_WESTWOOD_PUBKEY_SLICE_START: Final[int] = 2
_WESTWOOD_PUBKEY_SLICE_END: Final[int] = 42
_WESTWOOD_EXP_E: Final[int] = 65537
_WESTWOOD_MODULUS: Final[int] = int.from_bytes(
    base64.b64decode(_WESTWOOD_PUBKEY_B64)[
        _WESTWOOD_PUBKEY_SLICE_START:_WESTWOOD_PUBKEY_SLICE_END
    ],
    "big",
)
_WESTWOOD_KEY_SOURCE_SIZE: Final[int] = 80
_WESTWOOD_RSA_BLOCK_IN: Final[int] = 40
_WESTWOOD_RSA_BLOCK_OUT: Final[int] = 39
_WESTWOOD_BF_KEY_LEN: Final[int] = 56
_WESTWOOD_BF_BLOCK_SIZE: Final[int] = 8
_WESTWOOD_MIN_SIZE: Final[int] = 92
_WESTWOOD_HEADER_END: Final[int] = 84

_NEW_HEADER_SIZE: Final[int] = 10
_OLD_HEADER_SIZE: Final[int] = 6
_ENTRY_SIZE: Final[int] = 12
_SHA1_SIZE: Final[int] = 20
_SENTINEL_U32: Final[int] = 0xFFFFFFFF
_SIGN_BIT_32: Final[int] = 0x80000000
_MOD_32: Final[int] = 0x100000000
_MASK_32: Final[int] = 0xFFFFFFFF
_MAX_MIX_ENTRIES: Final[int] = 0xFFFF

_PAD_ALIGN_MASK: Final[int] = 3
_PAD_BYTES: Final[tuple[bytes, ...]] = (b"", b"\x01", b"\x02", b"\x03")
_INVALID_NAME_CHARS: Final[frozenset[str]] = frozenset('/\\:*?"<>|')
_MAX_NAME_LEN: Final[int] = 128
_ASCII_MIN_PRINTABLE: Final[int] = 0x20
_ASCII_MAX_PRINTABLE: Final[int] = 0x7F
_RAW_ID_RE: Final[re.Pattern[str]] = re.compile(r"^_([0-9A-Fa-f]{8})$")

_XOR_KEY_SIZE: Final[int] = 1024
_XOR_KEY_MASK: Final[int] = 1023
_XOR_CHUNK_SIZE: Final[int] = 256 << 10
_IO_CHUNK_SIZE: Final[int] = 4 << 20

_FNV1A_INIT: Final[int] = 0x811C9DC5
_FNV1A_PRIME: Final[int] = 0x01000193
_MT_N: Final[int] = 624
_MT_M: Final[int] = 397
_MT_MULT: Final[int] = 1812433253
_MT_UPPER_MASK: Final[int] = 0x80000000
_MT_LOWER_MASK: Final[int] = 0x7FFFFFFF
_MT_MATRIX_A: Final[int] = 0x9908B0DF
_MT_TEMPER_B: Final[int] = 0x9D2C5680
_MT_TEMPER_C: Final[int] = 0xEFC60000
_MT_SHIFT_INIT: Final[int] = 30
_MT_SHIFT_U: Final[int] = 11
_MT_SHIFT_S: Final[int] = 7
_MT_SHIFT_T: Final[int] = 15
_MT_SHIFT_L: Final[int] = 18
_MT_OUT_WORDS: Final[int] = 256

_RC4_STATE_LEN: Final[int] = 256
_BYTE_MASK: Final[int] = 0xFF

_BF_ROUNDS: Final[int] = 16
_BF_P_LEN: Final[int] = 18
_BF_S_BOXES: Final[int] = 4
_BF_S_ENTRIES: Final[int] = 256
_BF_TOTAL_WORDS: Final[int] = 1042
_BF_EXTRA_BITS: Final[int] = 64
_BF_SHIFT_24: Final[int] = 24
_BF_SHIFT_16: Final[int] = 16
_BF_SHIFT_8: Final[int] = 8
_ARCCOT_5: Final[int] = 5
_ARCCOT_239: Final[int] = 239
_MACHIN_4: Final[int] = 4
_MACHIN_3: Final[int] = 3

_ALIGN_16_MASK: Final[int] = 15
_MAJORITY_A16_RATIO: Final[float] = 0.85
_WEIGHT_LMD: Final[int] = 10**13
_WEIGHT_BOTH_ADJ: Final[int] = 3 * 10**11
_WEIGHT_ONE_ADJ: Final[int] = 10**11
_WEIGHT_A16: Final[int] = 5 * 10**10
_DECOY_SMALL_LIMIT: Final[int] = 32768
_WEIGHT_SMALL_PENALTY: Final[int] = 8 * 10**10
_MIN_CARVED_HITS: Final[int] = 2

_IDX_STRUCT: Final[struct.Struct] = struct.Struct("<III")
_HDR_NEW_STRUCT: Final[struct.Struct] = struct.Struct("<IHI")
_HDR_OLD_STRUCT: Final[struct.Struct] = struct.Struct("<HI")
_LMD_META_STRUCT: Final[struct.Struct] = struct.Struct("<5I")
_U32_LE: Final[struct.Struct] = struct.Struct("<I")
_U32_2_BE: Final[struct.Struct] = struct.Struct(">II")


class MixStrategy(StrEnum):
    """Supported MIX archive parsing and decryption strategies."""

    STANDARD = "S1:standard"
    FW_CRYPTO = "S2b:fw_crypto"
    WESTWOOD = "S3:westwood"
    WESTWOOD_SANITIZE = "S3:westwood->S4:sanitize"
    SANITIZE = "S4:sanitize"
    COUNT_RECOVER = "S5:count_recover"


@dataclass(frozen=True, slots=True)
class MixEntry:
    """Single file record inside a MIX archive index."""

    id: int
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class ParsedMix:
    """Parsed and decrypted MIX archive metadata and index."""

    source_path: Path
    strategy: MixStrategy
    flags: int | None
    body_at: int
    body_size: int
    entries: tuple[MixEntry, ...]
    lmd_names: frozendict[int, str]
    lmd_order: tuple[str, ...]
    lmd_game: int = _LMD_DEFAULT_GAME
    body_xor_key: bytes | None = None


@dataclass(frozen=True, slots=True)
class MixArchiveSpec:
    """Overlay `.patch.mix` binary archive merged by entry ID."""

    source_path: Path
    layer_label: str


@dataclass(frozen=True, slots=True)
class MixFileSpec:
    """Loose file injected or replaced in a virtual `.mix` archive."""

    target_name: str
    source_path: Path
    layer_label: str


@dataclass(frozen=True, slots=True)
class MixPatchSpec:
    """Declarative text patch targeting an entry in a `.mix` archive."""

    target_name: str
    patch: PatchSpec


def mix_id(name: str) -> int:
    """Compute the 32-bit TS/RA2/YR MIX CRC32 ID for `name`.

    Args:
        name: Case-insensitive inner filename.

    Returns:
        Unsigned 32-bit MIX entry identifier.
    """
    raw = name.upper().encode("latin-1", errors="ignore")
    length = len(raw)
    rem = length & _PAD_ALIGN_MASK
    if rem:
        aligned = length & ~_PAD_ALIGN_MASK
        raw = (
            raw + _PAD_BYTES[rem] + raw[aligned : aligned + 1] * (_PAD_ALIGN_MASK - rem)
        )
    return binascii.crc32(raw) & _MASK_32


LMD_ID: Final[int] = mix_id(LMD_FILENAME)


def signed_id(entry_id: int) -> int:
    """Convert an unsigned 32-bit MIX ID to signed 32-bit sort order.

    Args:
        entry_id: Unsigned 32-bit MIX entry identifier.

    Returns:
        Signed 32-bit integer used by the game's binary search.
    """
    return entry_id - _MOD_32 if entry_id & _SIGN_BIT_32 else entry_id


def _is_valid_mix_name(name: str) -> bool:
    return (
        bool(name)
        and len(name) <= _MAX_NAME_LEN
        and name not in {".", ".."}
        and all(
            _ASCII_MIN_PRINTABLE <= ord(ch) < _ASCII_MAX_PRINTABLE
            and ch not in _INVALID_NAME_CHARS
            for ch in name
        )
    )


def build_lmd_blob(
    names: Sequence[str],
    *,
    game: int = _LMD_DEFAULT_GAME,
) -> bytes:
    """Build a standard XCC `local mix database.dat` binary payload.

    Args:
        names: Filenames stored in the MIX archive.
        game: XCC game identifier (defaults to 5 for Yuri's Revenge).

    Returns:
        Serialized XCC LMD bytes.
    """
    order: list[str] = []
    seen: set[str] = set()
    for name in names:
        folded = name.casefold()
        if folded != LMD_FILENAME and folded not in seen and _is_valid_mix_name(name):
            seen.add(folded)
            order.append(name)
    order.append(LMD_FILENAME)
    payload = b"".join(item.encode("latin-1") + b"\x00" for item in order)
    meta = _LMD_META_STRUCT.pack(
        _LMD_HEADER_SIZE + len(payload),
        0,
        0,
        game,
        len(order),
    )
    return _XCC_ID + meta + payload


def parse_lmd_blob(blob: bytes | memoryview) -> tuple[tuple[str, ...], int]:
    """Parse an XCC `local mix database.dat` binary payload.

    Args:
        blob: Raw LMD entry bytes.

    Returns:
        `(filenames, game_id)` extracted from the database.
    """
    if len(blob) < _LMD_HEADER_SIZE or bytes(blob[:_XCC_ID_LEN]) != _XCC_ID:
        return (), _LMD_DEFAULT_GAME
    lmd_size, _, _, game, _count = _LMD_META_STRUCT.unpack_from(
        blob,
        _XCC_ID_LEN,
    )
    end = min(len(blob), lmd_size) if lmd_size >= _LMD_HEADER_SIZE else len(blob)
    raw = bytes(blob[_LMD_HEADER_SIZE:end])
    names = tuple(
        decoded
        for item in raw.split(b"\x00")
        if item and _is_valid_mix_name(decoded := item.decode("latin-1", "ignore"))
    )
    return names, int(game)


def open_mix_archive(path: Path) -> ParsedMix:
    """Open, decrypt, and sanitize a MIX archive across S1..S5 formats.

    Supports:
    - `S1:standard`: Unencrypted 6-byte and 10-byte MIX headers.
    - `S2b:fw_crypto`: CryptoRuntime RC4-sub index + FNV-1a/MT19937 XOR.
    - `S3:westwood`: Westwood RSA-320 + Blowfish-ECB encrypted MIX.
    - `S4:sanitize`: Fake `body_size`, `0xFFFFFFFF` sentinels, and
      weighted interval scheduling DP decoy removal + LMD carving.
    - `S5:count_recover`: Corrupted entry count recovery.

    Args:
        path: Path to the `.mix` file on disk.

    Returns:
        A `ParsedMix` descriptor with clean, sorted entries.

    Raises:
        OverlayError: If the file cannot be read or is not a valid MIX.
    """
    if not path.is_file():
        role = "MIX archive"
        raise OverlayError.missing_directory(role, path)

    try:
        file_size = path.stat().st_size
        if file_size < _OLD_HEADER_SIZE:
            detail = "file too small to be a MIX archive"
            raise OverlayError.invalid_patch(path, detail)
        with (
            path.open("rb") as handle,
            mmap.mmap(
                handle.fileno(),
                0,
                access=mmap.ACCESS_READ,
            ) as mm,
        ):
            parsed = (
                _try_standard(path, mm, file_size)
                or _try_fw_crypto(path, mm, file_size)
                or _try_westwood(path, mm, file_size)
                or _try_sanitize(path, mm, file_size)
                or _try_count_recover(path, mm, file_size)
            )
            if parsed is None:
                detail = "unrecognised or corrupted MIX archive format"
                raise OverlayError.invalid_patch(path, detail)
            return parsed
    except OSError as exc:
        raise OverlayError.invalid_patch(path, str(exc)) from exc


def read_mix_entry_bytes(
    parsed: ParsedMix,
    entry_id: int,
) -> bytes | None:
    """Read and decrypt the payload bytes for `entry_id` from `parsed`.

    Args:
        parsed: Open `ParsedMix` descriptor.
        entry_id: Unsigned 32-bit MIX entry identifier.

    Returns:
        Decrypted entry bytes, or `None` if `entry_id` is absent.
    """
    target: MixEntry | None = None
    for item in parsed.entries:
        if item.id == entry_id:
            target = item
            break
    if target is None:
        return None
    if target.size == 0:
        return b""

    with parsed.source_path.open("rb") as handle:
        handle.seek(parsed.body_at + target.offset)
        raw = handle.read(target.size)
    if parsed.body_xor_key is not None:
        return _xor_key1024(raw, parsed.body_xor_key, target.offset)
    return raw


def render_mix_member_text(
    base_archive: Path | None,
    *,
    mix_archives: Sequence[MixArchiveSpec] = (),
    mix_files: Sequence[MixFileSpec] = (),
    mix_patches: Sequence[MixPatchSpec] = (),
    member_name: str,
) -> str:
    """Render the final UTF-8 text of `member_name` in a virtual MIX.

    Args:
        base_archive: Base `.mix` archive path, if present.
        mix_archives: Stacked `.patch.mix` archives.
        mix_files: Loose file overrides inside `<archive>.mix/`.
        mix_patches: Declarative text patches inside `<archive>.mix/`.
        member_name: Inner filename to render (e.g. `rulesmo.ini`).

    Returns:
        Final merged UTF-8 text of `member_name`.

    Raises:
        OverlayError: If `member_name` does not exist in the MIX stack.
    """
    target_id = _resolve_name_to_id(member_name)
    raw_bytes: bytes | None = None

    archives: list[Path] = []
    if base_archive is not None:
        archives.append(base_archive)
    archives.extend(spec.source_path for spec in mix_archives)

    for archive_path in archives:
        parsed = open_mix_archive(archive_path)
        found = read_mix_entry_bytes(parsed, target_id)
        if found is not None:
            raw_bytes = found

    for file_spec in mix_files:
        if _resolve_name_to_id(file_spec.target_name) == target_id:
            try:
                raw_bytes = file_spec.source_path.read_bytes()
            except OSError as exc:
                raise OverlayError.invalid_patch(
                    file_spec.source_path,
                    str(exc),
                ) from exc

    matching_patches = tuple(
        spec.patch
        for spec in mix_patches
        if _resolve_name_to_id(spec.target_name) == target_id
    )
    if raw_bytes is None and not matching_patches:
        raise OverlayError.missing_virtual_file(Path(member_name))

    base_text = (
        raw_bytes.decode("utf-8", errors="replace") if raw_bytes is not None else ""
    )
    if not matching_patches:
        return base_text
    return apply_patch_chain(base_text, matching_patches)


def compose_mix_archive(
    target_path: Path,
    *,
    base_archive: Path | None,
    mix_archives: Sequence[MixArchiveSpec] = (),
    mix_files: Sequence[MixFileSpec] = (),
    mix_patches: Sequence[MixPatchSpec] = (),
) -> None:
    """Decrypt, patch, and mix all sources into a standard MIX archive.

    Unmodified entry spans from the base and `.patch.mix` archives are
    streamed directly by file offset while modified or patched entries
    and the rebuilt XCC `local mix database.dat` are injected in signed
    32-bit ID order.

    Args:
        target_path: Output `.mix` file path in the virtual workspace.
        base_archive: Base `.mix` archive path, if present.
        mix_archives: Stacked `.patch.mix` binary archives.
        mix_files: Loose file overrides inside `<archive>.mix/`.
        mix_patches: Declarative text patches inside `<archive>.mix/`.

    Raises:
        OverlayError: If any source MIX or patch is invalid.
    """
    parsed_archives: list[ParsedMix] = []
    if base_archive is not None:
        parsed_archives.append(open_mix_archive(base_archive))
    parsed_archives.extend(open_mix_archive(spec.source_path) for spec in mix_archives)

    # Map entry_id -> (archive_index, MixEntry) or in-memory bytes.
    archive_refs: dict[int, tuple[int, MixEntry]] = {}
    memory_blobs: dict[int, bytes] = {}
    known_names: dict[int, str] = {}
    lmd_order: list[str] = []
    lmd_game = _LMD_DEFAULT_GAME

    for arch_idx, parsed in enumerate(parsed_archives):
        lmd_game = parsed.lmd_game
        lmd_order.extend(parsed.lmd_order)
        known_names.update(parsed.lmd_names)
        for entry in parsed.entries:
            if entry.id == LMD_ID:
                continue
            archive_refs[entry.id] = (arch_idx, entry)

    for file_spec in mix_files:
        entry_id = _resolve_name_to_id(file_spec.target_name)
        if entry_id == LMD_ID:
            continue
        try:
            memory_blobs[entry_id] = file_spec.source_path.read_bytes()
        except OSError as exc:
            raise OverlayError.invalid_patch(
                file_spec.source_path,
                str(exc),
            ) from exc
        if _is_valid_mix_name(file_spec.target_name) and not _RAW_ID_RE.match(
            file_spec.target_name
        ):
            known_names[entry_id] = file_spec.target_name

    _apply_mix_patches(
        parsed_archives=parsed_archives,
        archive_refs=archive_refs,
        memory_blobs=memory_blobs,
        known_names=known_names,
        mix_patches=mix_patches,
    )

    _rebuild_lmd_entry(
        archive_refs=archive_refs,
        memory_blobs=memory_blobs,
        known_names=known_names,
        lmd_order=lmd_order,
        lmd_game=lmd_game,
    )

    _write_standard_mix_atomic(
        target_path=target_path,
        parsed_archives=parsed_archives,
        archive_refs=archive_refs,
        memory_blobs=memory_blobs,
    )


def _resolve_name_to_id(name: str) -> int:
    match = _RAW_ID_RE.match(name)
    if match is not None:
        return int(match.group(1), 16)
    return mix_id(name)


def _apply_mix_patches(
    *,
    parsed_archives: Sequence[ParsedMix],
    archive_refs: Mapping[int, tuple[int, MixEntry]],
    memory_blobs: dict[int, bytes],
    known_names: dict[int, str],
    mix_patches: Sequence[MixPatchSpec],
) -> None:
    grouped: dict[int, list[PatchSpec]] = {}
    for spec in mix_patches:
        entry_id = _resolve_name_to_id(spec.target_name)
        grouped.setdefault(entry_id, []).append(spec.patch)
        if _is_valid_mix_name(spec.target_name) and not _RAW_ID_RE.match(
            spec.target_name
        ):
            known_names[entry_id] = spec.target_name

    for entry_id, patches in grouped.items():
        raw_base = memory_blobs.get(entry_id)
        if raw_base is None and entry_id in archive_refs:
            arch_idx, entry = archive_refs[entry_id]
            raw_base = read_mix_entry_bytes(
                parsed_archives[arch_idx],
                entry.id,
            )
        base_text = (
            raw_base.decode("utf-8", errors="replace") if raw_base is not None else ""
        )
        merged_text = apply_patch_chain(base_text, patches)
        memory_blobs[entry_id] = merged_text.encode("utf-8")


def _rebuild_lmd_entry(
    *,
    archive_refs: Mapping[int, tuple[int, MixEntry]],
    memory_blobs: dict[int, bytes],
    known_names: Mapping[int, str],
    lmd_order: Sequence[str],
    lmd_game: int,
) -> None:
    all_ids = set(archive_refs) | set(memory_blobs)
    present = {
        known_names[eid].casefold(): known_names[eid]
        for eid in all_ids
        if eid in known_names and eid != LMD_ID
    }
    if not present:
        return
    ordered: list[str] = []
    for name in lmd_order:
        folded = name.casefold()
        if folded in present:
            ordered.append(present.pop(folded))
    ordered.extend(sorted(present.values(), key=str.casefold))
    memory_blobs[LMD_ID] = build_lmd_blob(ordered, game=lmd_game)


def _write_standard_mix_atomic(
    *,
    target_path: Path,
    parsed_archives: Sequence[ParsedMix],
    archive_refs: Mapping[int, tuple[int, MixEntry]],
    memory_blobs: Mapping[int, bytes],
) -> None:
    all_ids = sorted(set(archive_refs) | set(memory_blobs), key=signed_id)
    if len(all_ids) > _MAX_MIX_ENTRIES:
        detail = f"too many MIX entries ({len(all_ids)} > {_MAX_MIX_ENTRIES})"
        raise OverlayError.invalid_patch(target_path, detail)

    sizes: dict[int, int] = {}
    for eid in all_ids:
        if eid in memory_blobs:
            sizes[eid] = len(memory_blobs[eid])
        else:
            _, entry = archive_refs[eid]
            sizes[eid] = entry.size

    total_body = sum(sizes.values())
    header_and_index = bytearray(_NEW_HEADER_SIZE + _ENTRY_SIZE * len(all_ids))
    _HDR_NEW_STRUCT.pack_into(header_and_index, 0, 0, len(all_ids), total_body)
    current_offset = 0
    for idx, eid in enumerate(all_ids):
        _IDX_STRUCT.pack_into(
            header_and_index,
            _NEW_HEADER_SIZE + _ENTRY_SIZE * idx,
            eid,
            current_offset,
            sizes[eid],
        )
        current_offset += sizes[eid]

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as out_handle:
            temp_path = Path(out_handle.name)
            out_handle.write(header_and_index)
            _stream_mix_bodies(
                write_fn=out_handle.write,
                all_ids=all_ids,
                parsed_archives=parsed_archives,
                archive_refs=archive_refs,
                memory_blobs=memory_blobs,
            )
        temp_path.replace(target_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _stream_mix_bodies(
    *,
    write_fn: Callable[[bytes], object],
    all_ids: Sequence[int],
    parsed_archives: Sequence[ParsedMix],
    archive_refs: Mapping[int, tuple[int, MixEntry]],
    memory_blobs: Mapping[int, bytes],
) -> None:
    handles = [arch.source_path.open("rb") for arch in parsed_archives]
    try:
        for eid in all_ids:
            blob = memory_blobs.get(eid)
            if blob is not None:
                if blob:
                    write_fn(blob)
                continue

            arch_idx, entry = archive_refs[eid]
            if entry.size == 0:
                continue
            parsed = parsed_archives[arch_idx]
            src_handle = handles[arch_idx]
            src_handle.seek(parsed.body_at + entry.offset)
            remaining = entry.size
            rel_off = entry.offset
            while remaining > 0:
                step = min(
                    _XOR_CHUNK_SIZE
                    if parsed.body_xor_key is not None
                    else _IO_CHUNK_SIZE,
                    remaining,
                )
                chunk = src_handle.read(step)
                if not chunk:
                    detail = f"unexpected EOF in {parsed.source_path}"
                    raise OverlayError.invalid_patch(
                        parsed.source_path,
                        detail,
                    )
                if parsed.body_xor_key is not None:
                    chunk = _xor_key1024(chunk, parsed.body_xor_key, rel_off)
                write_fn(chunk)
                rel_off += len(chunk)
                remaining -= len(chunk)
    finally:
        for handle in handles:
            handle.close()


# ----------------------------------------------------------------------
# Strategy S1..S5 Parsers & Decryptors
# ----------------------------------------------------------------------


def _try_standard(
    path: Path,
    mm: mmap.mmap,
    file_size: int,
) -> ParsedMix | None:
    old_cnt, old_bsz = _HDR_OLD_STRUCT.unpack_from(mm, 0)
    if old_cnt != 0:
        flags: int | None = None
        count, body_size, idx_off, has_ck = (
            old_cnt,
            old_bsz,
            _OLD_HEADER_SIZE,
            False,
        )
    else:
        if file_size < _NEW_HEADER_SIZE:
            return None
        raw_flags, count, body_size = _HDR_NEW_STRUCT.unpack_from(mm, 0)
        if (raw_flags & _FLAG_ENCRYPTED) or (raw_flags & ~_FLAG_CHECKSUM):
            return None
        flags = raw_flags
        idx_off = _NEW_HEADER_SIZE
        has_ck = bool(raw_flags & _FLAG_CHECKSUM)

    body_at = idx_off + _ENTRY_SIZE * count
    if body_at + body_size + (_SHA1_SIZE if has_ck else 0) != file_size:
        return None

    seen: set[int] = set()
    entries: list[MixEntry] = []
    for eid, off, sz in _iter_index_mm(mm, idx_off, body_at):
        if off + sz > body_size or eid in seen:
            return None
        seen.add(eid)
        entries.append(MixEntry(eid, off, sz))

    entries.sort(key=lambda item: signed_id(item.id))
    lmd_names, lmd_order, lmd_game = _extract_lmd(
        mm=mm,
        body_at=body_at,
        file_size=file_size,
        entries=entries,
        body_xor_key=None,
    )
    return ParsedMix(
        source_path=path,
        strategy=MixStrategy.STANDARD,
        flags=flags,
        body_at=body_at,
        body_size=body_size,
        entries=tuple(entries),
        lmd_names=frozendict(lmd_names),
        lmd_order=lmd_order,
        lmd_game=lmd_game,
    )


def _try_fw_crypto(
    path: Path,
    mm: mmap.mmap,
    file_size: int,
) -> ParsedMix | None:
    if file_size < _NEW_HEADER_SIZE:
        return None
    flags, count, body_size = _HDR_NEW_STRUCT.unpack_from(mm, 0)
    if (
        (flags & _FW_LOW_MASK) != _FW_LOW_MASK
        or not (flags & _FLAG_FW_CRYPTO)
        or count == 0
    ):
        return None
    has_ck = bool(flags & _FLAG_CHECKSUM)
    idx_off = _NEW_HEADER_SIZE
    body_at = idx_off + _ENTRY_SIZE * count
    if body_at + body_size + (_SHA1_SIZE if has_ck else 0) > file_size:
        return None

    rc4_key = base64.b64encode(mm[4:_NEW_HEADER_SIZE])
    raw_idx = mm[idx_off:body_at]
    dec_idx = _rc4_sub_decrypt(raw_idx, rc4_key)
    body_key = _mt19937_key1024(_fnv1a_32(raw_idx))

    seen: set[int] = set()
    entries: list[MixEntry] = []
    for eid, off, sz in _IDX_STRUCT.iter_unpack(dec_idx):
        if off + sz > body_size:
            return None
        if eid not in seen:
            seen.add(eid)
            entries.append(MixEntry(eid, off, sz))
    if not entries:
        return None
    entries.sort(key=lambda item: signed_id(item.id))
    lmd_names, lmd_order, lmd_game = _extract_lmd(
        mm=mm,
        body_at=body_at,
        file_size=file_size,
        entries=entries,
        body_xor_key=body_key,
    )
    return ParsedMix(
        source_path=path,
        strategy=MixStrategy.FW_CRYPTO,
        flags=flags,
        body_at=body_at,
        body_size=body_size,
        entries=tuple(entries),
        lmd_names=frozendict(lmd_names),
        lmd_order=lmd_order,
        lmd_game=lmd_game,
        body_xor_key=body_key,
    )


def _try_westwood(
    path: Path,
    mm: mmap.mmap,
    file_size: int,
) -> ParsedMix | None:
    if file_size < _WESTWOOD_MIN_SIZE:
        return None
    flags = _U32_LE.unpack_from(mm, 0)[0]
    if not (flags & _FLAG_ENCRYPTED) or (flags & ~(_FLAG_ENCRYPTED | _FLAG_CHECKSUM)):
        return None
    has_ck = bool(flags & _FLAG_CHECKSUM)

    bf_key = _westwood_blowfish_key(mm[4:_WESTWOOD_HEADER_END])
    if bf_key is None:
        return None
    cipher = _PureBlowfish(bf_key)
    blk0 = cipher.decrypt_ecb(mm[_WESTWOOD_HEADER_END:_WESTWOOD_MIN_SIZE])
    count, body_size = _HDR_OLD_STRUCT.unpack_from(blk0, 0)
    enc_total = (
        (_OLD_HEADER_SIZE + _ENTRY_SIZE * count + _WESTWOOD_BF_BLOCK_SIZE - 1)
        // _WESTWOOD_BF_BLOCK_SIZE
    ) * _WESTWOOD_BF_BLOCK_SIZE
    body_at = _WESTWOOD_HEADER_END + enc_total
    if count == 0 or body_at > file_size:
        return None

    rest = (
        cipher.decrypt_ecb(mm[_WESTWOOD_MIN_SIZE:body_at])
        if enc_total > _WESTWOOD_BF_BLOCK_SIZE
        else b""
    )
    dec_idx = blk0 + rest

    in_bounds: list[MixEntry] = []
    oob_or_dups = False
    seen: set[int] = set()
    idx_slice = memoryview(dec_idx)[
        _OLD_HEADER_SIZE : _OLD_HEADER_SIZE + _ENTRY_SIZE * count
    ]
    for eid, off, sz in _IDX_STRUCT.iter_unpack(idx_slice):
        if _SENTINEL_U32 in (off, sz) or body_at + off + sz > file_size or eid in seen:
            oob_or_dups = True
        else:
            seen.add(eid)
            in_bounds.append(MixEntry(eid, off, sz))

    if not in_bounds:
        return None

    expected = body_at + body_size + (_SHA1_SIZE if has_ck else 0)
    strategy = MixStrategy.WESTWOOD
    if oob_or_dups or expected != file_size:
        strategy = MixStrategy.WESTWOOD_SANITIZE
        trusted = _carve_trusted_ids(mm, body_at, file_size, in_bounds)
        in_bounds = _resolve_overlapping_decoys(in_bounds, trusted)
        body_size = max((e.offset + e.size for e in in_bounds), default=0)
    else:
        in_bounds.sort(key=lambda item: signed_id(item.id))

    lmd_names, lmd_order, lmd_game = _extract_lmd(
        mm=mm,
        body_at=body_at,
        file_size=file_size,
        entries=in_bounds,
        body_xor_key=None,
    )
    return ParsedMix(
        source_path=path,
        strategy=strategy,
        flags=flags,
        body_at=body_at,
        body_size=body_size,
        entries=tuple(in_bounds),
        lmd_names=frozendict(lmd_names),
        lmd_order=lmd_order,
        lmd_game=lmd_game,
    )


def _try_sanitize(
    path: Path,
    mm: mmap.mmap,
    file_size: int,
) -> ParsedMix | None:
    if file_size < _NEW_HEADER_SIZE:
        return None
    old_cnt, _old_bsz = _HDR_OLD_STRUCT.unpack_from(mm, 0)
    if old_cnt != 0:
        flags: int | None = None
        count = old_cnt
        idx_off = _OLD_HEADER_SIZE
    else:
        raw_flags, count, _hdr_bsz = _HDR_NEW_STRUCT.unpack_from(mm, 0)
        if (raw_flags & _FLAG_ENCRYPTED) or (raw_flags & ~_FLAG_CHECKSUM):
            return None
        flags = raw_flags
        idx_off = _NEW_HEADER_SIZE

    if count == 0 or idx_off + _ENTRY_SIZE * count > file_size:
        return None

    body_at = idx_off + _ENTRY_SIZE * count
    in_bounds: list[MixEntry] = []
    seen: set[int] = set()
    for eid, off, sz in _iter_index_mm(mm, idx_off, body_at):
        if _SENTINEL_U32 in (off, sz) or body_at + off + sz > file_size or eid in seen:
            continue
        seen.add(eid)
        in_bounds.append(MixEntry(eid, off, sz))

    if not in_bounds or len(in_bounds) < max(1, count // 2):
        return None

    trusted = _carve_trusted_ids(mm, body_at, file_size, in_bounds)
    clean = _resolve_overlapping_decoys(in_bounds, trusted)
    max_end = max((item.offset + item.size for item in clean), default=0)
    lmd_names, lmd_order, lmd_game = _extract_lmd(
        mm=mm,
        body_at=body_at,
        file_size=file_size,
        entries=clean,
        body_xor_key=None,
    )
    return ParsedMix(
        source_path=path,
        strategy=MixStrategy.SANITIZE,
        flags=flags,
        body_at=body_at,
        body_size=max_end,
        entries=tuple(clean),
        lmd_names=frozendict(lmd_names),
        lmd_order=lmd_order,
        lmd_game=lmd_game,
    )


def _try_count_recover(
    path: Path,
    mm: mmap.mmap,
    file_size: int,
) -> ParsedMix | None:
    for idx_start in (_NEW_HEADER_SIZE, _OLD_HEADER_SIZE):
        if idx_start + _ENTRY_SIZE > file_size:
            continue
        candidates = _scan_monotonic_index(mm, idx_start, file_size)
        if len(candidates) < _MIN_CARVED_HITS:
            continue
        best_k = _pick_best_index_prefix(mm, idx_start, file_size, candidates)
        if best_k >= _MIN_CARVED_HITS:
            body_at = idx_start + _ENTRY_SIZE * best_k
            in_bounds = [
                item
                for item in candidates[:best_k]
                if _SENTINEL_U32 not in (item.offset, item.size)
                and body_at + item.offset + item.size <= file_size
            ]
            trusted = _carve_trusted_ids(mm, body_at, file_size, in_bounds)
            clean = _resolve_overlapping_decoys(in_bounds, trusted)
            max_end = max(
                (item.offset + item.size for item in clean),
                default=0,
            )
            lmd_names, lmd_order, lmd_game = _extract_lmd(
                mm=mm,
                body_at=body_at,
                file_size=file_size,
                entries=clean,
                body_xor_key=None,
            )
            return ParsedMix(
                source_path=path,
                strategy=MixStrategy.COUNT_RECOVER,
                flags=0 if idx_start == _NEW_HEADER_SIZE else None,
                body_at=body_at,
                body_size=max_end,
                entries=tuple(clean),
                lmd_names=frozendict(lmd_names),
                lmd_order=lmd_order,
                lmd_game=lmd_game,
            )
    return None


def _scan_monotonic_index(
    mm: mmap.mmap,
    idx_start: int,
    file_size: int,
) -> list[MixEntry]:
    candidates: list[MixEntry] = []
    prev_sid = -_MOD_32
    pos = idx_start
    while pos + _ENTRY_SIZE <= file_size and len(candidates) < _MAX_MIX_ENTRIES:
        eid, off, sz = _IDX_STRUCT.unpack_from(mm, pos)
        sid = signed_id(eid)
        if sid <= prev_sid:
            break
        is_sentinel = off == _SENTINEL_U32 and sz == _SENTINEL_U32
        if not is_sentinel and (
            off > file_size or sz > file_size or off + sz > file_size
        ):
            break
        candidates.append(MixEntry(eid, off, sz))
        prev_sid = sid
        pos += _ENTRY_SIZE
    return candidates


def _pick_best_index_prefix(
    mm: mmap.mmap,
    idx_start: int,
    file_size: int,
    candidates: Sequence[MixEntry],
) -> int:
    best_k = 0
    best_score = -1
    for count in range(_MIN_CARVED_HITS, len(candidates) + 1):
        body_at = idx_start + _ENTRY_SIZE * count
        if body_at > file_size:
            break
        sub = candidates[:count]
        in_b = sum(
            1
            for item in sub
            if item.offset != _SENTINEL_U32
            and body_at + item.offset + item.size <= file_size
        )
        sent = sum(
            1
            for item in sub
            if item.offset == _SENTINEL_U32 and item.size == _SENTINEL_U32
        )
        oob = count - in_b - sent
        if in_b < _MIN_CARVED_HITS or oob > _MIN_CARVED_HITS:
            continue
        score = in_b * 100 - oob * 500
        if any(item.offset == 0 for item in sub):
            score += 500
        if any(
            item.id == LMD_ID
            and item.offset != _SENTINEL_U32
            and body_at + item.offset + _XCC_ID_LEN <= file_size
            and mm[body_at + item.offset : body_at + item.offset + _XCC_ID_LEN]
            == _XCC_ID
            for item in sub
        ):
            score += 5000
        if score > best_score:
            best_score = score
            best_k = count
    return best_k


# ----------------------------------------------------------------------
# S4 Weighted Interval Scheduling DP & LMD Carving
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _IntervalContext:
    trusted_ids: frozenset[int]
    majority_a16: bool
    all_starts: frozenset[int]
    all_ends: frozenset[int]
    all_ends_a16: frozenset[int]


def _resolve_overlapping_decoys(
    entries: Sequence[MixEntry],
    trusted_ids: frozenset[int],
) -> list[MixEntry]:
    if len(entries) <= 1:
        return list(entries)

    zero_entries: list[MixEntry] = []
    range_groups: dict[tuple[int, int], list[MixEntry]] = {}
    for entry in entries:
        if entry.size == 0:
            zero_entries.append(entry)
        else:
            range_groups.setdefault((entry.offset, entry.size), []).append(entry)

    intervals = sorted(
        ((off, off + sz, grp) for (off, sz), grp in range_groups.items()),
        key=lambda item: (item[0], -(item[1] - item[0])),
    )
    if not intervals:
        return zero_entries

    ctx = _IntervalContext(
        trusted_ids=trusted_ids,
        majority_a16=(
            sum(1 for off, _, _ in intervals if (off & _ALIGN_16_MASK) == 0)
            / len(intervals)
        )
        >= _MAJORITY_A16_RATIO,
        all_starts=frozenset(off for off, _, _ in intervals),
        all_ends=frozenset(end for _, end, _ in intervals),
        all_ends_a16=frozenset(
            (end + _ALIGN_16_MASK) & ~_ALIGN_16_MASK for _, end, _ in intervals
        ),
    )
    kept = list(zero_entries)

    comp = [intervals[0]]
    comp_max = intervals[0][1]
    for item in intervals[1:]:
        if item[0] < comp_max:
            comp.append(item)
            comp_max = max(comp_max, item[1])
        else:
            kept.extend(_solve_interval_component(comp, ctx))
            comp = [item]
            comp_max = item[1]
    kept.extend(_solve_interval_component(comp, ctx))
    kept.sort(key=lambda item: signed_id(item.id))
    return kept


def _score_interval(
    off: int,
    end: int,
    grp: Sequence[MixEntry],
    ctx: _IntervalContext,
) -> int:
    sz = end - off
    weight = sz
    in_lmd = any(item.id in ctx.trusted_ids for item in grp)
    if in_lmd:
        weight += _WEIGHT_LMD
    left_ok = (
        off == 0
        or off in ctx.all_ends
        or (ctx.majority_a16 and off in ctx.all_ends_a16)
    )
    right_ok = end in ctx.all_starts or (
        ctx.majority_a16
        and ((end + _ALIGN_16_MASK) & ~_ALIGN_16_MASK) in ctx.all_starts
    )
    if left_ok and right_ok:
        weight += _WEIGHT_BOTH_ADJ
    elif left_ok or right_ok:
        weight += _WEIGHT_ONE_ADJ
    if ctx.majority_a16 and (off & _ALIGN_16_MASK) == 0:
        weight += _WEIGHT_A16
    if (
        off < _DECOY_SMALL_LIMIT
        and sz < _DECOY_SMALL_LIMIT
        and not in_lmd
        and ctx.majority_a16
        and (off & _ALIGN_16_MASK) != 0
    ):
        weight -= _WEIGHT_SMALL_PENALTY
    return max(1, weight)


def _solve_interval_component(
    comp: Sequence[tuple[int, int, list[MixEntry]]],
    ctx: _IntervalContext,
) -> list[MixEntry]:
    if len(comp) == 1:
        return list(comp[0][2])

    c_end = sorted(comp, key=lambda item: (item[1], item[0]))
    count = len(c_end)
    ends = [item[1] for item in c_end]
    weights = [_score_interval(off, end, grp, ctx) for off, end, grp in c_end]

    prev_ok = [bisect.bisect_right(ends, c_end[i][0]) - 1 for i in range(count)]
    dp = [0] * (count + 1)
    take = [False] * count
    for idx in range(count):
        inc = weights[idx] + dp[prev_ok[idx] + 1]
        if inc >= dp[idx]:
            dp[idx + 1] = inc
            take[idx] = True
        else:
            dp[idx + 1] = dp[idx]

    chosen: set[int] = set()
    cursor = count - 1
    while cursor >= 0:
        if take[cursor]:
            chosen.add(cursor)
            cursor = prev_ok[cursor]
        else:
            cursor -= 1

    out: list[MixEntry] = []
    for idx, (_, _, grp) in enumerate(c_end):
        if idx in chosen:
            out.extend(grp)
    return out


def _carve_trusted_ids(
    mm: mmap.mmap,
    body_at: int,
    file_size: int,
    entries: Sequence[MixEntry],
) -> frozenset[int]:
    entry_ids = frozenset(item.id for item in entries)
    matched, _, _ = _carve_orphaned_lmds(mm, body_at, file_size, entry_ids)
    return frozenset(matched)


def _extract_lmd(
    *,
    mm: mmap.mmap,
    body_at: int,
    file_size: int,
    entries: Sequence[MixEntry],
    body_xor_key: bytes | None,
) -> tuple[dict[int, str], tuple[str, ...], int]:
    entry_ids = frozenset(item.id for item in entries)
    for entry in entries:
        if entry.id == LMD_ID:
            raw_blob = mm[body_at + entry.offset : body_at + entry.offset + entry.size]
            blob = (
                _xor_key1024(raw_blob, body_xor_key, entry.offset)
                if body_xor_key is not None
                else raw_blob
            )
            if len(blob) >= _LMD_HEADER_SIZE and blob[:_XCC_ID_LEN] == _XCC_ID:
                names, game = parse_lmd_blob(blob)
                matched: dict[int, str] = {LMD_ID: LMD_FILENAME}
                for name in names:
                    eid = mix_id(name)
                    if eid in entry_ids and eid not in matched:
                        matched[eid] = name
                return matched, names, game

    if body_xor_key is None:
        return _carve_orphaned_lmds(mm, body_at, file_size, entry_ids)
    return {}, (), _LMD_DEFAULT_GAME


def _carve_orphaned_lmds(
    mm: mmap.mmap,
    body_at: int,
    file_size: int,
    entry_ids: frozenset[int],
) -> tuple[dict[int, str], tuple[str, ...], int]:
    best_map: dict[int, str] = {}
    best_order: tuple[str, ...] = ()
    best_game = _LMD_DEFAULT_GAME
    best_hits = 0

    pos = body_at
    while pos < file_size and (hit := mm.find(_XCC_ID, pos)) >= 0:
        if hit + _LMD_HEADER_SIZE <= file_size:
            lmd_size = _U32_LE.unpack_from(mm, hit + _XCC_ID_LEN)[0]
            if (
                _LMD_HEADER_SIZE
                <= lmd_size
                <= min(
                    _LMD_MAX_SIZE,
                    file_size - hit,
                )
            ):
                names, game = parse_lmd_blob(mm[hit : hit + lmd_size])
                matched: dict[int, str] = {}
                for name in names:
                    eid = mix_id(name)
                    if eid in entry_ids and eid not in matched:
                        matched[eid] = name
                real_hits = len(matched) - (1 if LMD_ID in matched else 0)
                if real_hits >= _MIN_CARVED_HITS and real_hits > best_hits:
                    best_hits = real_hits
                    best_map = matched
                    best_order = names
                    best_game = game
        pos = hit + _XCC_ID_LEN
    return best_map, best_order, best_game


def _iter_index_mm(
    mm: mmap.mmap,
    start: int,
    end: int,
) -> list[tuple[int, int, int]]:
    with memoryview(mm)[start:end] as segment:
        return list(_IDX_STRUCT.iter_unpack(segment))


# ----------------------------------------------------------------------
# Cryptographic Primitives (Westwood RSA+Blowfish & CryptoRuntime)
# ----------------------------------------------------------------------


def _westwood_blowfish_key(key_source: bytes) -> bytes | None:
    if len(key_source) != _WESTWOOD_KEY_SOURCE_SIZE:
        return None
    out = bytearray()
    for offset in (0, _WESTWOOD_RSA_BLOCK_IN):
        block_int = int.from_bytes(
            key_source[offset : offset + _WESTWOOD_RSA_BLOCK_IN],
            "little",
        )
        decrypted = pow(block_int, _WESTWOOD_EXP_E, _WESTWOOD_MODULUS)
        try:
            out.extend(
                decrypted.to_bytes(_WESTWOOD_RSA_BLOCK_OUT, "little"),
            )
        except OverflowError:
            return None
    return bytes(out[:_WESTWOOD_BF_KEY_LEN])


class _PureBlowfish:
    """Pure-Python Blowfish-ECB cipher with lazy Machin pi tables."""

    __slots__ = ("p_box", "s_box")
    _PI_CACHE: tuple[tuple[int, ...], tuple[tuple[int, ...], ...]] | None = None

    @classmethod
    def _pi_tables(
        cls,
    ) -> tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]:
        if cls._PI_CACHE is not None:
            return cls._PI_CACHE
        bits = _BF_TOTAL_WORDS * 32 + _BF_EXTRA_BITS
        one = 1 << bits

        def _arccot(val: int) -> int:
            val_sq = val * val
            term = one // val
            step = 1
            total = term
            while term:
                term //= val_sq
                step += 2
                if step & 2:
                    total -= term // step
                else:
                    total += term // step
            return total

        frac = (
            (_MACHIN_4 * (_MACHIN_4 * _arccot(_ARCCOT_5) - _arccot(_ARCCOT_239)))
            - (_MACHIN_3 << bits)
        ) >> _BF_EXTRA_BITS
        words = [
            (frac >> (32 * (_BF_TOTAL_WORDS - 1 - idx))) & _MASK_32
            for idx in range(_BF_TOTAL_WORDS)
        ]
        cls._PI_CACHE = (
            tuple(words[:_BF_P_LEN]),
            tuple(
                tuple(
                    words[
                        _BF_P_LEN + box * _BF_S_ENTRIES : _BF_P_LEN
                        + (box + 1) * _BF_S_ENTRIES
                    ]
                )
                for box in range(_BF_S_BOXES)
            ),
        )
        return cls._PI_CACHE

    def __init__(self, key: bytes) -> None:
        p_init, s_init = self._pi_tables()
        p_box = list(p_init)
        s_box = [list(box) for box in s_init]
        key_len = len(key)
        cursor = 0
        for idx in range(_BF_P_LEN):
            word = 0
            for _ in range(4):
                word = (word << _BF_SHIFT_8) | key[cursor]
                cursor = (cursor + 1) % key_len
            p_box[idx] ^= word
        self.p_box = p_box
        self.s_box = s_box

        left = 0
        right = 0
        for idx in range(0, _BF_P_LEN, 2):
            left, right = self._encrypt_pair(left, right)
            p_box[idx], p_box[idx + 1] = left, right
        for box in s_box:
            for idx in range(0, _BF_S_ENTRIES, 2):
                left, right = self._encrypt_pair(left, right)
                box[idx], box[idx + 1] = left, right

    def _feistel(self, val: int) -> int:
        s0, s1, s2, s3 = self.s_box
        part = (
            s0[val >> _BF_SHIFT_24] + s1[(val >> _BF_SHIFT_16) & _BYTE_MASK]
        ) & _MASK_32
        return (
            (part ^ s2[(val >> _BF_SHIFT_8) & _BYTE_MASK]) + s3[val & _BYTE_MASK]
        ) & _MASK_32

    def _encrypt_pair(self, left: int, right: int) -> tuple[int, int]:
        p_box = self.p_box
        for idx in range(_BF_ROUNDS):
            left ^= p_box[idx]
            right ^= self._feistel(left)
            left, right = right, left
        return (
            (right ^ p_box[_BF_ROUNDS + 1]) & _MASK_32,
            (left ^ p_box[_BF_ROUNDS]) & _MASK_32,
        )

    def _decrypt_pair(self, left: int, right: int) -> tuple[int, int]:
        p_box = self.p_box
        for idx in range(_BF_ROUNDS + 1, 1, -1):
            left ^= p_box[idx]
            right ^= self._feistel(left)
            left, right = right, left
        return (
            (right ^ p_box[0]) & _MASK_32,
            (left ^ p_box[1]) & _MASK_32,
        )

    def decrypt_ecb(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        offset = 0
        for left, right in _U32_2_BE.iter_unpack(data):
            dec_l, dec_r = self._decrypt_pair(left, right)
            _U32_2_BE.pack_into(out, offset, dec_l, dec_r)
            offset += _WESTWOOD_BF_BLOCK_SIZE
        return bytes(out)


def _fnv1a_32(data: bytes | memoryview) -> int:
    digest = _FNV1A_INIT
    for byte in data:
        digest = ((digest ^ byte) * _FNV1A_PRIME) & _MASK_32
    return digest


def _mt19937_key1024(seed: int) -> bytes:
    mt = [0] * _MT_N
    mt[0] = seed & _MASK_32
    for idx in range(1, _MT_N):
        prev = mt[idx - 1]
        mt[idx] = (_MT_MULT * (prev ^ (prev >> _MT_SHIFT_INIT)) + idx) & _MASK_32
    for idx in range(_MT_N):
        y_val = (mt[idx] & _MT_UPPER_MASK) | (mt[(idx + 1) % _MT_N] & _MT_LOWER_MASK)
        mt[idx] = (
            mt[(idx + _MT_M) % _MT_N]
            ^ (y_val >> 1)
            ^ (_MT_MATRIX_A if (y_val & 1) else 0)
        )
    out = bytearray(_XOR_KEY_SIZE)
    for idx in range(_MT_OUT_WORDS):
        y_val = mt[idx]
        y_val ^= y_val >> _MT_SHIFT_U
        y_val ^= (y_val << _MT_SHIFT_S) & _MT_TEMPER_B
        y_val ^= (y_val << _MT_SHIFT_T) & _MT_TEMPER_C
        y_val ^= y_val >> _MT_SHIFT_L
        _U32_LE.pack_into(out, idx * 4, y_val & _MASK_32)
    return bytes(out)


def _rc4_sub_decrypt(data: bytes | memoryview, key: bytes) -> bytes:
    state = list(range(_RC4_STATE_LEN))
    j_idx = 0
    key_len = len(key)
    for i_idx in range(_RC4_STATE_LEN):
        j_idx = (j_idx + state[i_idx] + key[i_idx % key_len]) & _BYTE_MASK
        state[i_idx], state[j_idx] = state[j_idx], state[i_idx]
    out = bytearray(len(data))
    i_idx = 0
    j_idx = 0
    for pos, byte in enumerate(data):
        i_idx = (i_idx + 1) & _BYTE_MASK
        j_idx = (j_idx + state[i_idx]) & _BYTE_MASK
        state[i_idx], state[j_idx] = state[j_idx], state[i_idx]
        ks_byte = state[(state[i_idx] + state[j_idx]) & _BYTE_MASK]
        out[pos] = (byte - ks_byte) & _BYTE_MASK
    return bytes(out)


def _xor_key1024(
    data: bytes | memoryview,
    key1024: bytes,
    body_rel_off: int = 0,
) -> bytes:
    length = len(data)
    if length == 0:
        return b""
    shift = body_rel_off & _XOR_KEY_MASK
    rotated = (key1024[shift:] + key1024[:shift]) if shift else key1024
    repeated = (rotated * ((length // _XOR_KEY_SIZE) + 1))[:length]
    return (
        int.from_bytes(data, "little") ^ int.from_bytes(repeated, "little")
    ).to_bytes(length, "little")
