"""Multi-strategy MIX archive decryption, sanitization, and mixing.

Supports all six TS/RA2/YR MIX formats symmetrically across disk files,
MVMXV1 chunked containers, and arbitrarily nested inner `.mix` archives:
- `S1:standard`: Unencrypted 6-byte and 10-byte MIX archives.
- `S2:mvmx`: MVLoader `MVMXV1` (HKDF-SHA256 + chunked AES-256-GCM +
  optional zlib) with automatic `MVLoader.dll` PE32 secret extraction.
- `S2b:fw_crypto`: CryptoRuntime `0x0004FFFF` (RC4-sub + MT19937 XOR).
- `S3:westwood`: Westwood RSA-320 + Blowfish-ECB (cascading to S4).
- `S4:sanitize`: Fake `body_size`, `0xFFFFFFFF` sentinels, weighted
  interval scheduling DP decoy removal, and orphaned XCC LMD carving.
- `S5a:shifted` / `S5b:count_recover`: Leading-junk header shifts and
  corrupted entry count monotonic index recovery.
"""

import base64
import binascii
import bisect
import hashlib
import io
import json
import mmap
import re
import struct
import tempfile
import zlib
from contextlib import ExitStack
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, assert_never
lazy from collections.abc import Buffer, Callable, Sequence

from mentara._mix_crypto import (
    WESTWOOD_KEY_SOURCE_BYTES,
    MIXCrypto,
    default_crypto,
    derive_mvmx_keys,
    fnv1a_32,
    is_pe_binary,
    mt19937_key1024,
    rc4_sub_decrypt,
    resolve_mvmx_secret,
    westwood_blowfish_key,
    xor_key1024,
)
from mentara.errors import OverlayError
from mentara.patcher import PatchSpec, apply_patch_chain

__all__ = [
    "LMD_FILENAME",
    "LMD_ID",
    "MIX_PATCH_SUFFIX",
    "MIXArchiveOp",
    "MIXContext",
    "MIXEntry",
    "MIXFileOp",
    "MIXOp",
    "MIXPatchOp",
    "MIXProbeKind",
    "MIXStrategy",
    "ParsedMIX",
    "build_lmd_blob",
    "compose_mix_archive",
    "mix_context_secret_digest",
    "mix_id",
    "open_mix_archive",
    "open_mix_bytes",
    "parse_lmd_blob",
    "probe_mix_file",
    "read_mix_entry_bytes",
    "render_mix_member_text",
    "signed_id",
]

LMD_FILENAME: Final[str] = "local mix database.dat"
# Precomputed `mix_id(LMD_FILENAME)` to avoid import-time computation.
LMD_ID: Final[int] = 0x366E051F
MIX_PATCH_SUFFIX: Final[str] = ".patch.mix"
_MIX_SUFFIX: Final[str] = ".mix"

_XCC_ID: Final[bytes] = b"XCC by Olaf van der Spek\x1a\x04\x17\x27\x10\x19\x80\x00"
_XCC_ID_BYTES: Final[int] = 32
_LMD_HEADER_BYTES: Final[int] = 52
_LMD_GAME_DEFAULT: Final[int] = 5
_LMD_SIZE_BYTES_MAX: Final[int] = 16 << 20

_FLAG_CHECKSUM: Final[int] = 0x00010000
_FLAG_ENCRYPTED: Final[int] = 0x00020000
_FLAG_FW_CRYPTO: Final[int] = 0x00040000
_FW_LOW_MASK: Final[int] = 0xFFFF

_MVMX_MAGIC: Final[bytes] = b"MVMXV1\x00\x00"
_MVMX_MAGIC_BYTES: Final[int] = 8
_MVMX_HEADER_BYTES: Final[int] = 0x78
_MVMX_VERSION: Final[int] = 1
_MVMX_FLAG_COMPRESSED: Final[int] = 1
_MVMX_SHA_SPLIT: Final[int] = 0x54
_MVMX_SHA_END: Final[int] = 0x74
_MVMX_SHA_ZERO_PAD: Final[bytes] = b"\x00" * 36
_MVMX_SALT_START: Final[int] = 0x2C
_MVMX_SALT_END: Final[int] = 0x3C
_MVMX_NONCE_END: Final[int] = 0x44
_MVMX_CHUNK_HEADER_BYTES: Final[int] = 12
_MVMX_GCM_TAG_BYTES: Final[int] = 16
_MVMX_META_NONCE_TAIL: Final[bytes] = b"\xff\xff\xff\xff"
_MVMX_META_AAD_PREFIX: Final[bytes] = b"MVX-META-v1\x00"
_MVMX_CHUNK_AAD_PREFIX: Final[bytes] = b"MVX-CHUNK-v1\x00"
_MVMX_CHUNK_CACHE_MAX: Final[int] = 4

_WESTWOOD_BF_BLOCK_BYTES: Final[int] = 8
_WESTWOOD_SIZE_BYTES_MIN: Final[int] = 92
_WESTWOOD_HEADER_END: Final[int] = 4 + WESTWOOD_KEY_SOURCE_BYTES

_NEW_HEADER_BYTES: Final[int] = 10
_OLD_HEADER_BYTES: Final[int] = 6
_ENTRY_BYTES: Final[int] = 12
_SHA1_BYTES: Final[int] = 20
_SENTINEL_U32: Final[int] = 0xFFFFFFFF
_SIGN_BIT_32: Final[int] = 0x80000000
_MOD_32: Final[int] = 0x100000000
_MASK_32: Final[int] = 0xFFFFFFFF
_MIX_ENTRIES_MAX: Final[int] = 0xFFFF
_SHIFTED_SCAN_BYTES_MAX: Final[int] = 1 << 20
_SHIFTED_TAIL_BYTES_MIN: Final[int] = 22
_MIX_NESTING_DEPTH_MAX: Final[int] = 8

_PE_DOS_BYTES_MIN: Final[int] = 0x40
_PE_LFANEW_OFFSET: Final[int] = 0x3C
_PE_OFFSET_BYTES_MAX: Final[int] = 1 << 20

_PAD_ALIGN_MASK: Final[int] = 3
_PAD_BYTES: Final[tuple[bytes, ...]] = (b"", b"\x01", b"\x02", b"\x03")
_INVALID_NAME_CHARS: Final[frozenset[str]] = frozenset('/\\:*?"<>|')
_NAME_LENGTH_MAX: Final[int] = 128
_ASCII_PRINTABLE_MIN: Final[int] = 0x20
_ASCII_PRINTABLE_MAX: Final[int] = 0x7F
_ASCII_HIGH_BIT: Final[int] = 0x80
_RAW_ID_RE: Final[re.Pattern[str]] = re.compile(r"^_([0-9A-Fa-f]{8})$")

_XOR_CHUNK_BYTES: Final[int] = 256 << 10
_IO_CHUNK_BYTES: Final[int] = 4 << 20

_ALIGN_16_MASK: Final[int] = 15
_MAJORITY_A16_RATIO: Final[float] = 0.85
_WEIGHT_LMD: Final[int] = 10**13
_WEIGHT_BOTH_ADJ: Final[int] = 3 * 10**11
_WEIGHT_ONE_ADJ: Final[int] = 10**11
_WEIGHT_A16: Final[int] = 5 * 10**10
_WEIGHT_MAGIC: Final[int] = 2 * 10**10
_DECOY_SMALL_BYTES_MAX: Final[int] = 32768
_WEIGHT_SMALL_PENALTY: Final[int] = 8 * 10**10
_CARVED_HITS_MIN: Final[int] = 2

_MAGIC_HEAD_BYTES: Final[int] = 32
_MAGIC_VXL_BYTES: Final[int] = 16
_MAGIC_WAV_BYTES: Final[int] = 12
_MAGIC_TAG_BYTES: Final[int] = 4
_MAGIC_BIK_BYTES: Final[int] = 3
_MAGIC_SHP_BYTES: Final[int] = 8
_PCX_MAGIC_BYTE: Final[int] = 0x0A
_PALETTE_BYTES: Final[int] = 768
_PALETTE_VALUE_MAX: Final[int] = 63
_HVA_HEADER_BYTES_MIN: Final[int] = 24
_HVA_FRAMES_MAX: Final[int] = 10000
_HVA_SECTIONS_MAX: Final[int] = 256
_TMP_HEADER_BYTES_MIN: Final[int] = 20
_TMP_DIMENSION_MAX: Final[int] = 64
_SHP_DIMENSION_MAX: Final[int] = 4096
_SHP_FRAMES_MAX: Final[int] = 8192
_PRINTABLE_RATIO: Final[float] = 0.9
_WW_NON_ZERO_KEY_BYTES_MIN: Final[int] = 14
_WW_ENTROPY_SLICE_END: Final[int] = 28

_IDX_STRUCT: Final[struct.Struct] = struct.Struct("<III")
_HDR_NEW_STRUCT: Final[struct.Struct] = struct.Struct("<IHI")
_HDR_OLD_STRUCT: Final[struct.Struct] = struct.Struct("<HI")
_LMD_META_STRUCT: Final[struct.Struct] = struct.Struct("<5I")
_MVMX_HDR_STRUCT: Final[struct.Struct] = struct.Struct("<HHIIIIQII")
_MVMX_CHUNK_STRUCT: Final[struct.Struct] = struct.Struct("<III")
_U32_LE: Final[struct.Struct] = struct.Struct("<I")
_U32_BE: Final[struct.Struct] = struct.Struct(">I")
_U32_2_LE: Final[struct.Struct] = struct.Struct("<II")
_U32_4_LE: Final[struct.Struct] = struct.Struct("<4I")
_U16_3_LE: Final[struct.Struct] = struct.Struct("<HHH")


class MIXStrategy(StrEnum):
    """Supported MIX archive parsing and decryption strategies."""

    STANDARD = "S1:standard"
    MVMX = "S2:mvmx"
    FW_CRYPTO = "S2b:fw_crypto"
    WESTWOOD = "S3:westwood"
    WESTWOOD_SANITIZE = "S3:westwood->S4:sanitize"
    SANITIZE = "S4:sanitize"
    SHIFTED = "S5a:shifted"
    COUNT_RECOVER = "S5b:count_recover"


class MIXProbeKind(StrEnum):
    """Fast header classification of a candidate `.mix` file."""

    STANDARD = "standard"
    MVMX = "mvmx"
    FW_CRYPTO = "fw_crypto"
    WESTWOOD = "westwood"
    OBFUSCATED = "obfuscated"
    NESTED_ENCRYPTED = "nested_encrypted"
    PE_BINARY = "pe_binary"
    UNKNOWN = "unknown"

    @property
    def needs_decryption(self) -> bool:
        """Return whether this probe requires decryption/normalizing."""
        return self in {
            MIXProbeKind.MVMX,
            MIXProbeKind.FW_CRYPTO,
            MIXProbeKind.WESTWOOD,
            MIXProbeKind.OBFUSCATED,
            MIXProbeKind.NESTED_ENCRYPTED,
        }


@dataclass(frozen=True, slots=True)
class MIXContext:
    """Decryption context shared across MIX archive operations."""

    search_dirs: tuple[Path, ...] = ()
    mvmx_secret_hex: str | None = None


@dataclass(frozen=True, slots=True)
class MIXEntry:
    """Single file record inside a MIX archive index."""

    id: int
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class MIXArchiveOp:
    """Overlay `.patch.mix` binary archive merged by entry ID."""

    target_path: tuple[str, ...]
    source_path: Path
    layer_label: str


@dataclass(frozen=True, slots=True)
class MIXFileOp:
    """Loose file injected or replaced in a virtual `.mix` archive."""

    target_path: tuple[str, ...]
    source_path: Path
    layer_label: str


@dataclass(frozen=True, slots=True)
class MIXPatchOp:
    """Declarative text patch targeting an entry in a `.mix` archive."""

    target_path: tuple[str, ...]
    patch: PatchSpec


type MIXOp = MIXArchiveOp | MIXFileOp | MIXPatchOp


@dataclass(frozen=True, slots=True)
class ParsedMIX:
    """Parsed and decrypted MIX archive metadata and index."""

    source_path: Path | None
    strategy: MIXStrategy
    flags: int | None
    body_offset: int
    body_size: int
    entries: tuple[MIXEntry, ...]
    lmd_names: frozendict[int, str]
    lmd_order: tuple[str, ...]
    lmd_game: int = _LMD_GAME_DEFAULT
    body_xor_key: bytes | None = None
    mvmx_stream: _MVMXStreamSpec | None = None
    raw_buffer: bytes | None = None


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


def signed_id(entry_id: int) -> int:
    """Convert an unsigned 32-bit MIX ID to signed 32-bit sort order.

    Args:
        entry_id: Unsigned 32-bit MIX entry identifier.

    Returns:
        Signed 32-bit integer used by the game's binary search.
    """
    return entry_id - _MOD_32 if entry_id & _SIGN_BIT_32 else entry_id


def mix_context_secret_digest(context: MIXContext) -> bytes:
    """Return a SHA-256 digest of the MVMXV1 secret resolved by context.

    Suitable as a cache-invalidation component without exposing raw key
    material.

    Args:
        context: Active `MIXContext` specifying search dirs and key.

    Returns:
        32-byte SHA-256 digest of the resolved MVMXV1 secret.

    Raises:
        OverlayError: If `context.mvmx_secret_hex` is malformed.
    """
    try:
        secret = resolve_mvmx_secret(
            context.search_dirs,
            explicit_hex=context.mvmx_secret_hex,
        )
    except ValueError as exc:
        raise OverlayError.invalid_mix(Path("<mix-context>"), str(exc)) from exc
    return hashlib.sha256(secret).digest()


def build_lmd_blob(
    names: Sequence[str],
    *,
    game: int = _LMD_GAME_DEFAULT,
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
        _LMD_HEADER_BYTES + len(payload),
        0,
        0,
        game,
        len(order),
    )
    return _XCC_ID + meta + payload


def parse_lmd_blob(blob: Buffer) -> tuple[tuple[str, ...], int]:
    """Parse an XCC `local mix database.dat` binary payload.

    Args:
        blob: Raw LMD entry buffer.

    Returns:
        `(filenames, game_id)` extracted from the database.
    """
    with memoryview(blob) as raw_view:
        byte_view = raw_view.cast("B")
        if (
            len(byte_view) < _LMD_HEADER_BYTES
            or bytes(byte_view[:_XCC_ID_BYTES]) != _XCC_ID
        ):
            return (), _LMD_GAME_DEFAULT
        lmd_size, _, _, game, _count = _LMD_META_STRUCT.unpack_from(
            byte_view,
            _XCC_ID_BYTES,
        )
        end = (
            min(len(byte_view), int(lmd_size))
            if int(lmd_size) >= _LMD_HEADER_BYTES
            else len(byte_view)
        )
        raw = bytes(byte_view[_LMD_HEADER_BYTES:end])
    names = tuple(
        decoded
        for item in raw.split(b"\x00")
        if item and _is_valid_mix_name(decoded := item.decode("latin-1", "ignore"))
    )
    return names, int(game)


def probe_mix_file(path: Path) -> MIXProbeKind:
    """Classify a candidate `.mix` file via a fast header/index probe.

    Detects PE binaries disguised as `.mix`, clean `S1:standard`
    archives (checking whether they hide nested encrypted `.mix`
    members), custom-encrypted `S2:mvmx` / `S2b:fw_crypto`, Westwood
    `S3:westwood`, and `S4`/`S5` obfuscated archives without
    decompressing or scanning full archive bodies.

    Args:
        path: Path to the candidate `.mix` file on disk.

    Returns:
        A `MIXProbeKind` describing the detected format.
    """
    if not path.is_file():
        return MIXProbeKind.UNKNOWN
    if is_pe_binary(path):
        return MIXProbeKind.PE_BINARY
    try:
        file_size = path.stat().st_size
        if file_size < _OLD_HEADER_BYTES:
            return MIXProbeKind.UNKNOWN
        with (
            path.open("rb") as handle,
            mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping,
        ):
            return _probe_source(_MmapSource(mapping, file_size), depth=0)
    except OSError:
        return MIXProbeKind.UNKNOWN


def open_mix_archive(
    path: Path,
    *,
    context: MIXContext | None = None,
) -> ParsedMIX:
    """Open, decrypt, and sanitize a MIX archive across S1..S5 formats.

    Args:
        path: Path to the `.mix` file on disk.
        context: Optional decryption context (search dirs for
            `MVLoader.dll` and optional explicit MVMXV1 secret).

    Returns:
        A `ParsedMIX` descriptor with clean, sorted entries.

    Raises:
        OverlayError: If the file cannot be read, is a PE binary, or is
            not a valid MIX archive.
    """
    if not path.is_file():
        role = "MIX archive"
        raise OverlayError.missing_file(role, path)

    resolved_context = MIXContext() if context is None else context
    try:
        file_size = path.stat().st_size
        if file_size < _OLD_HEADER_BYTES:
            detail = "file too small to be a MIX archive"
            raise OverlayError.invalid_mix(path, detail)
        with (
            path.open("rb") as handle,
            mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping,
        ):
            return _parse_source(
                _MmapSource(mapping, file_size),
                source_path=path,
                context=resolved_context,
                raw_buffer=None,
            )
    except OSError as exc:
        raise OverlayError.unreadable_file(path, str(exc)) from exc


def open_mix_bytes(
    data: bytes,
    *,
    label: Path | None = None,
    context: MIXContext | None = None,
) -> ParsedMIX:
    """Open, decrypt, and sanitize an in-memory MIX byte buffer.

    Args:
        data: Raw MIX archive bytes (e.g. a nested `.mix` payload).
        label: Optional diagnostic path label for error reporting.
        context: Optional decryption context.

    Returns:
        A `ParsedMIX` descriptor backed by `data`.

    Raises:
        OverlayError: If `data` is not a valid MIX archive.
    """
    diag_path = Path("<memory.mix>") if label is None else label
    if len(data) < _OLD_HEADER_BYTES:
        detail = "buffer too small to be a MIX archive"
        raise OverlayError.invalid_mix(diag_path, detail)
    resolved_context = MIXContext() if context is None else context
    return _parse_source(
        _MemorySource(data),
        source_path=None,
        context=resolved_context,
        raw_buffer=data,
    )


def read_mix_entry_bytes(
    parsed: ParsedMIX,
    entry_id: int,
) -> bytes | None:
    """Read and decrypt the payload bytes for `entry_id` from `parsed`.

    Args:
        parsed: Open `ParsedMIX` descriptor.
        entry_id: Unsigned 32-bit MIX entry identifier.

    Returns:
        Decrypted entry bytes, or `None` if `entry_id` is absent.
    """
    target: MIXEntry | None = None
    for item in parsed.entries:
        if item.id == entry_id:
            target = item
            break
    if target is None:
        return None
    if target.size == 0:
        return b""

    raw = _read_raw_span(parsed, parsed.body_offset + target.offset, target.size)
    if parsed.body_xor_key is not None:
        return xor_key1024(raw, parsed.body_xor_key, target.offset)
    return raw


def render_mix_member_text(
    base_archive: Path | None,
    *,
    mix_ops: Sequence[MIXOp] = (),
    member_path: Sequence[str] | str,
    context: MIXContext | None = None,
) -> str:
    """Render the final UTF-8 text of `member_path` in a virtual MIX.

    Supports both top-level members (`"rulesmo.ini"`) and arbitrarily
    nested inner MIX paths (`("localmd.mix", "rulesmd.ini")`).

    Args:
        base_archive: Base `.mix` archive path, if present.
        mix_ops: Ordered MIX overlay operations (bottom to top).
        member_path: Inner filename or nested path segments.
        context: Optional decryption context.

    Returns:
        Final merged UTF-8 text of the requested member.

    Raises:
        OverlayError: If the target member does not exist.
    """
    segments = (member_path,) if isinstance(member_path, str) else tuple(member_path)
    if not segments:
        raise OverlayError.missing_virtual_file(Path())
    resolved_context = MIXContext() if context is None else context

    base_parsed = (
        open_mix_archive(base_archive, context=resolved_context)
        if base_archive is not None
        else None
    )
    raw = _render_member_bytes(
        base_parsed=base_parsed,
        mix_ops=mix_ops,
        segments=segments,
        context=resolved_context,
    )
    if raw is None:
        raise OverlayError.missing_virtual_file(Path(*segments))
    return raw.decode("utf-8", errors="replace")


def compose_mix_archive(
    target_path: Path,
    *,
    base_archive: Path | None,
    mix_ops: Sequence[MIXOp] = (),
    context: MIXContext | None = None,
) -> None:
    """Decrypt, patch, and mix all sources into a standard MIX archive.

    Applies `mix_ops` strictly in bottom-to-top layer order, recursively
    decrypts and composes nested `.mix` archives, rebuilds the XCC
    `local mix database.dat`, lays out body spans sequentially per
    source archive for single-pass MVMX/disk streaming, and writes
    `target_path` atomically.

    Args:
        target_path: Output `.mix` file path in the virtual workspace.
        base_archive: Base `.mix` archive path, if present.
        mix_ops: Ordered MIX overlay operations (bottom to top).
        context: Optional decryption context.

    Raises:
        OverlayError: If any source MIX or patch is invalid.
    """
    resolved_context = MIXContext() if context is None else context
    base_parsed = (
        open_mix_archive(base_archive, context=resolved_context)
        if base_archive is not None
        else None
    )
    state = _build_composed_state(
        base_parsed=base_parsed,
        mix_ops=mix_ops,
        context=resolved_context,
        depth=0,
    )
    _write_standard_mix_atomic(target_path=target_path, state=state)


# ----------------------------------------------------------------------
# Unified Byte Sources (Disk mmap, In-Memory Nested, Chunked MVMX)
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _MVMXChunk:
    index: int
    plain_offset: int
    plain_size: int
    cipher_offset: int
    stored_size: int
    cipher_size: int


@dataclass(frozen=True, slots=True)
class _MVMXStreamSpec:
    data_key: bytes
    nonce_prefix: bytes
    header_aad: bytes
    compressed: bool
    original_size: int
    chunks: tuple[_MVMXChunk, ...]


class _ByteSource(Protocol):
    """Read-only random-access byte stream for MIX parsing."""

    @property
    def size(self) -> int: ...

    def read(self, start: int, length: int) -> bytes: ...

    def find(self, needle: bytes, start: int, end: int | None = None) -> int: ...


class _MmapSource:
    """Zero-copy `mmap`-backed `_ByteSource` for files on disk."""

    __slots__ = ("_mapping", "_size")

    def __init__(self, mapping: mmap.mmap, size: int) -> None:
        self._mapping = mapping
        self._size = size

    @property
    def size(self) -> int:
        return self._size

    def read(self, start: int, length: int) -> bytes:
        if length <= 0:
            return b""
        return self._mapping[start : start + length]

    def find(self, needle: bytes, start: int, end: int | None = None) -> int:
        limit = self._size if end is None else min(end, self._size)
        if start >= limit:
            return -1
        return self._mapping.find(needle, start, limit)


class _MemorySource:
    """In-memory `bytes`-backed `_ByteSource` for nested MIX files."""

    __slots__ = ("_data",)

    def __init__(self, data: bytes) -> None:
        self._data = data

    @property
    def size(self) -> int:
        return len(self._data)

    def read(self, start: int, length: int) -> bytes:
        if length <= 0:
            return b""
        return self._data[start : start + length]

    def find(self, needle: bytes, start: int, end: int | None = None) -> int:
        limit = len(self._data) if end is None else min(end, len(self._data))
        if start >= limit:
            return -1
        return self._data.find(needle, start, limit)


class _MVMXSource:
    """Random-access chunk-decrypting `_ByteSource` for MVMXV1."""

    __slots__ = ("_backing", "_cache", "_crypto", "_spec", "_starts")

    def __init__(
        self,
        backing: _ByteSource,
        spec: _MVMXStreamSpec,
        crypto: MIXCrypto,
    ) -> None:
        self._backing = backing
        self._spec = spec
        self._crypto = crypto
        self._starts = [chunk.plain_offset for chunk in spec.chunks]
        self._cache: dict[int, bytes] = {}

    @property
    def size(self) -> int:
        return self._spec.original_size

    def read(self, start: int, length: int) -> bytes:
        if length <= 0 or start >= self._spec.original_size:
            return b""
        end = min(self._spec.original_size, start + length)
        if not self._starts:
            return b""
        idx = max(0, bisect.bisect_right(self._starts, start) - 1)
        pieces: list[bytes] = []
        cursor = start
        while cursor < end and idx < len(self._spec.chunks):
            chunk = self._spec.chunks[idx]
            local_start = cursor - chunk.plain_offset
            take = min(chunk.plain_size - local_start, end - cursor)
            if take > 0:
                plain = self._decrypt_chunk(idx)
                pieces.append(plain[local_start : local_start + take])
                cursor += take
            idx += 1
        return pieces[0] if len(pieces) == 1 else b"".join(pieces)

    def find(self, needle: bytes, start: int, end: int | None = None) -> int:
        limit = (
            self._spec.original_size
            if end is None
            else min(end, self._spec.original_size)
        )
        if not needle or start >= limit or not self._starts:
            return -1
        idx = max(0, bisect.bisect_right(self._starts, start) - 1)
        overlap = len(needle) - 1
        tail = b""
        tail_offset = start
        while idx < len(self._spec.chunks):
            chunk = self._spec.chunks[idx]
            if chunk.plain_offset >= limit:
                break
            plain = self._decrypt_chunk(idx)
            local_start = max(0, start - chunk.plain_offset)
            local_end = min(chunk.plain_size, limit - chunk.plain_offset)
            segment = plain[local_start:local_end]
            combined = tail + segment
            hit = combined.find(needle)
            if hit >= 0:
                return tail_offset + hit
            if overlap > 0:
                if len(combined) > overlap:
                    tail = combined[-overlap:]
                    tail_offset = (
                        chunk.plain_offset + local_start + len(segment) - overlap
                    )
                else:
                    tail = combined
            else:
                tail = b""
                tail_offset = chunk.plain_offset + local_end
            idx += 1
        return -1

    def _decrypt_chunk(self, chunk_idx: int) -> bytes:
        cached = self._cache.get(chunk_idx)
        if cached is not None:
            return cached
        chunk = self._spec.chunks[chunk_idx]
        ciphertext = self._backing.read(chunk.cipher_offset, chunk.cipher_size)
        nonce = self._spec.nonce_prefix + _U32_BE.pack(chunk.index)
        aad = (
            _MVMX_CHUNK_AAD_PREFIX
            + self._spec.header_aad
            + _MVMX_CHUNK_STRUCT.pack(chunk.index, chunk.plain_size, chunk.stored_size)
        )
        plain = self._crypto.aes_gcm_decrypt(
            self._spec.data_key, nonce, aad, ciphertext
        )
        if self._spec.compressed:
            plain = zlib.decompress(plain)
        if len(plain) != chunk.plain_size:
            msg = (
                f"MVMX chunk {chunk.index} plaintext size mismatch "
                f"({len(plain)} != {chunk.plain_size})"
            )
            raise ValueError(msg)
        if len(self._cache) >= _MVMX_CHUNK_CACHE_MAX:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[chunk_idx] = plain
        return plain


# ----------------------------------------------------------------------
# Fast Header Probing
# ----------------------------------------------------------------------


def _is_valid_mix_name(name: str) -> bool:
    return (
        bool(name)
        and len(name) <= _NAME_LENGTH_MAX
        and name not in {".", ".."}
        and all(
            _ASCII_PRINTABLE_MIN <= ord(ch) < _ASCII_PRINTABLE_MAX
            and ch not in _INVALID_NAME_CHARS
            for ch in name
        )
    )


def _is_pe_source(source: _ByteSource) -> bool:
    if source.size < _PE_DOS_BYTES_MIN:
        return False
    dos = source.read(0, _PE_DOS_BYTES_MIN)
    if len(dos) < _PE_DOS_BYTES_MIN or dos[:2] != b"MZ":
        return False
    pe_offset = int(_U32_LE.unpack_from(dos, _PE_LFANEW_OFFSET)[0])
    if (
        pe_offset < _PE_DOS_BYTES_MIN
        or pe_offset > _PE_OFFSET_BYTES_MAX
        or pe_offset + 4 > source.size
    ):
        return False
    return source.read(pe_offset, 4) == b"PE\x00\x00"


def _probe_source(source: _ByteSource, *, depth: int) -> MIXProbeKind:
    size = source.size
    if size < _OLD_HEADER_BYTES:
        return MIXProbeKind.UNKNOWN
    if _is_pe_source(source):
        return MIXProbeKind.PE_BINARY
    head = source.read(0, min(size, _WESTWOOD_SIZE_BYTES_MIN))
    header_kind = _probe_header_magic(head, size) or _probe_standard_index(
        source,
        depth=depth,
    )
    if header_kind is not None:
        return header_kind
    if source.find(_MVMX_MAGIC, 1, min(size, _SHIFTED_SCAN_BYTES_MAX)) > 0:
        return MIXProbeKind.MVMX
    return (
        MIXProbeKind.OBFUSCATED
        if (_looks_like_sanitize(source) or _looks_like_count_or_shifted(source))
        else MIXProbeKind.UNKNOWN
    )


def _probe_header_magic(head: bytes, size: int) -> MIXProbeKind | None:
    if len(head) >= _MVMX_MAGIC_BYTES and head[:_MVMX_MAGIC_BYTES] == _MVMX_MAGIC:
        return MIXProbeKind.MVMX
    if _matches_fw_crypto_header(head, size):
        return MIXProbeKind.FW_CRYPTO
    if _looks_like_westwood(head, size):
        return MIXProbeKind.WESTWOOD
    return None


def _matches_fw_crypto_header(
    head: bytes,
    size: int,
    *,
    exact: bool = False,
) -> bool:
    if len(head) < _NEW_HEADER_BYTES:
        return False
    raw_flags, raw_count, raw_body = _HDR_NEW_STRUCT.unpack_from(head, 0)
    flags, count, body_size = int(raw_flags), int(raw_count), int(raw_body)
    if (
        (flags & _FW_LOW_MASK) != _FW_LOW_MASK
        or not (flags & _FLAG_FW_CRYPTO)
        or count == 0
    ):
        return False
    has_checksum = bool(flags & _FLAG_CHECKSUM)
    expected = (
        _NEW_HEADER_BYTES
        + _ENTRY_BYTES * count
        + body_size
        + (_SHA1_BYTES if has_checksum else 0)
    )
    return expected == size if exact else expected <= size


def _looks_like_westwood(head: bytes, size: int) -> bool:
    if size < _WESTWOOD_SIZE_BYTES_MIN or len(head) < _WESTWOOD_SIZE_BYTES_MIN:
        return False
    flags = int(_U32_LE.unpack_from(head, 0)[0])
    if not (flags & _FLAG_ENCRYPTED) or (flags & ~(_FLAG_ENCRYPTED | _FLAG_CHECKSUM)):
        return False
    return westwood_blowfish_key(head[4:_WESTWOOD_HEADER_END]) is not None


def _parse_standard_header_and_entries(
    source: _ByteSource,
    base: int,
    limit: int,
) -> tuple[int | None, int, int, list[MIXEntry]] | None:
    avail = limit - base
    if avail < _OLD_HEADER_BYTES:
        return None
    header = source.read(base, min(avail, _NEW_HEADER_BYTES))
    old_count, old_body_size = _HDR_OLD_STRUCT.unpack_from(header, 0)
    if old_count != 0:
        flags: int | None = None
        count = int(old_count)
        body_size = int(old_body_size)
        index_offset = base + _OLD_HEADER_BYTES
        has_checksum = False
    else:
        if len(header) < _NEW_HEADER_BYTES:
            return None
        raw_flags, raw_count, raw_body = _HDR_NEW_STRUCT.unpack_from(header, 0)
        flags_int = int(raw_flags)
        if (flags_int & _FLAG_ENCRYPTED) or (flags_int & ~_FLAG_CHECKSUM):
            return None
        flags = flags_int
        count = int(raw_count)
        body_size = int(raw_body)
        index_offset = base + _NEW_HEADER_BYTES
        has_checksum = bool(flags_int & _FLAG_CHECKSUM)

    body_offset = index_offset + _ENTRY_BYTES * count
    if body_offset + body_size + (_SHA1_BYTES if has_checksum else 0) != limit:
        return None

    index_bytes = source.read(index_offset, _ENTRY_BYTES * count)
    seen: set[int] = set()
    entries: list[MIXEntry] = []
    for entry_id, offset, size in _IDX_STRUCT.iter_unpack(index_bytes):
        if offset + size > body_size or entry_id in seen:
            return None
        seen.add(entry_id)
        entries.append(MIXEntry(entry_id, offset, size))
    return flags, body_offset, body_size, entries


def _probe_standard_index(source: _ByteSource, *, depth: int) -> MIXProbeKind | None:
    parsed = _parse_standard_header_and_entries(source, 0, source.size)
    if parsed is None:
        return None
    _, body_offset, _, entries = parsed
    if depth < _MIX_NESTING_DEPTH_MAX and _has_nested_encrypted_member(
        source,
        body_offset,
        entries,
        depth=depth,
    ):
        return MIXProbeKind.NESTED_ENCRYPTED
    return MIXProbeKind.STANDARD


def _has_nested_encrypted_member(
    source: _ByteSource,
    body_offset: int,
    entries: Sequence[MIXEntry],
    *,
    depth: int,
) -> bool:
    lmd_names: dict[int, str] = {}
    for entry in entries:
        if entry.id == LMD_ID and entry.size >= _LMD_HEADER_BYTES:
            names, _ = parse_lmd_blob(
                source.read(body_offset + entry.offset, entry.size)
            )
            for name in names:
                lmd_names[mix_id(name)] = name
            break

    for entry in entries:
        if entry.id == LMD_ID or entry.size < _OLD_HEADER_BYTES:
            continue
        member_head = source.read(
            body_offset + entry.offset,
            min(entry.size, _NEW_HEADER_BYTES),
        )
        if (
            len(member_head) >= _MVMX_MAGIC_BYTES
            and member_head[:_MVMX_MAGIC_BYTES] == _MVMX_MAGIC
        ):
            return True
        if _matches_fw_crypto_header(member_head, entry.size, exact=True):
            return True
        member_name = lmd_names.get(entry.id)
        if member_name is not None and member_name.casefold().endswith(_MIX_SUFFIX):
            sub_bytes = source.read(body_offset + entry.offset, entry.size)
            sub_probe = _probe_source(_MemorySource(sub_bytes), depth=depth + 1)
            if sub_probe.needs_decryption:
                return True
    return False


def _parse_sanitize_candidates(
    source: _ByteSource,
    base: int,
    limit: int,
) -> tuple[int | None, int, list[MIXEntry]] | None:
    if limit - base < _NEW_HEADER_BYTES:
        return None
    header = source.read(base, _NEW_HEADER_BYTES)
    old_count, _old_body_size = _HDR_OLD_STRUCT.unpack_from(header, 0)
    if old_count != 0:
        flags: int | None = None
        count = int(old_count)
        index_offset = base + _OLD_HEADER_BYTES
    else:
        raw_flags, raw_count, _header_body = _HDR_NEW_STRUCT.unpack_from(header, 0)
        flags_int = int(raw_flags)
        if (flags_int & _FLAG_ENCRYPTED) or (flags_int & ~_FLAG_CHECKSUM):
            return None
        flags = flags_int
        count = int(raw_count)
        index_offset = base + _NEW_HEADER_BYTES

    if count == 0 or index_offset + _ENTRY_BYTES * count > limit:
        return None

    body_offset = index_offset + _ENTRY_BYTES * count
    index_bytes = source.read(index_offset, _ENTRY_BYTES * count)
    in_bounds: list[MIXEntry] = []
    seen: set[int] = set()
    for entry_id, offset, size in _IDX_STRUCT.iter_unpack(index_bytes):
        if (
            _SENTINEL_U32 in (offset, size)
            or body_offset + offset + size > limit
            or entry_id in seen
        ):
            continue
        seen.add(entry_id)
        in_bounds.append(MIXEntry(entry_id, offset, size))

    if not in_bounds or len(in_bounds) < max(1, count // 2):
        return None
    return flags, body_offset, in_bounds


def _looks_like_sanitize(source: _ByteSource) -> bool:
    return _parse_sanitize_candidates(source, 0, source.size) is not None


def _looks_like_count_or_shifted(source: _ByteSource) -> bool:
    size = source.size
    for index_start in (_NEW_HEADER_BYTES, _OLD_HEADER_BYTES):
        if index_start + _ENTRY_BYTES <= size:
            candidates = _scan_monotonic_index(source, index_start, size)
            if (
                len(candidates) >= _CARVED_HITS_MIN
                and _pick_best_index_prefix(source, index_start, size, candidates)
                >= _CARVED_HITS_MIN
            ):
                return True

    scan_limit = min(size - _SHIFTED_TAIL_BYTES_MIN, _SHIFTED_SCAN_BYTES_MAX)
    for sig in (b"\x00\x00\x00\x00", b"\x00\x00\x01\x00"):
        pos = 1
        while pos < scan_limit and (hit := source.find(sig, pos, scan_limit)) >= 0:
            if _try_standard(None, source, hit, size) is not None:
                return True
            pos = hit + 4
    return False


# ----------------------------------------------------------------------
# Parsing Dispatch & Entry Reading
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ParseScope:
    source: _ByteSource
    source_path: Path | None
    base: int
    limit: int
    context: MIXContext
    crypto: MIXCrypto
    diag_path: Path


def _parse_source(
    source: _ByteSource,
    *,
    source_path: Path | None,
    context: MIXContext,
    raw_buffer: bytes | None,
) -> ParsedMIX:
    diag_path = Path("<memory.mix>") if source_path is None else source_path
    if _is_pe_source(source):
        detail = "file is a Windows PE executable/DLL disguised as .mix"
        raise OverlayError.invalid_mix(diag_path, detail)

    scope = _ParseScope(
        source=source,
        source_path=source_path,
        base=0,
        limit=source.size,
        context=context,
        crypto=default_crypto(),
        diag_path=diag_path,
    )
    parsed = _dispatch_strategies(scope)
    if parsed is None:
        detail = "unrecognised or corrupted MIX archive format"
        raise OverlayError.invalid_mix(diag_path, detail)

    if raw_buffer is not None and parsed.raw_buffer is None:
        return replace(parsed, raw_buffer=raw_buffer)
    return parsed


def _dispatch_strategies(scope: _ParseScope) -> ParsedMIX | None:
    if (
        scope.limit - scope.base >= _MVMX_MAGIC_BYTES
        and scope.source.read(scope.base, _MVMX_MAGIC_BYTES) == _MVMX_MAGIC
    ):
        return _parse_mvmx(scope)

    return (
        _try_standard(scope.source_path, scope.source, scope.base, scope.limit)
        or _try_fw_crypto(scope.source_path, scope.source, scope.base, scope.limit)
        or _try_westwood(
            scope.source_path,
            scope.source,
            scope.base,
            scope.limit,
            scope.crypto,
        )
        or _try_sanitize(scope.source_path, scope.source, scope.base, scope.limit)
        or _try_shifted(scope)
        or _try_count_recover(scope.source_path, scope.source, scope.base, scope.limit)
    )


def _read_raw_span(parsed: ParsedMIX, offset: int, size: int) -> bytes:
    if parsed.mvmx_stream is not None:
        crypto = default_crypto()
        if parsed.raw_buffer is not None:
            return _MVMXSource(
                _MemorySource(parsed.raw_buffer),
                parsed.mvmx_stream,
                crypto,
            ).read(offset, size)
        if parsed.source_path is None:
            return b""
        with (
            parsed.source_path.open("rb") as handle,
            mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping,
        ):
            file_size = parsed.source_path.stat().st_size
            mvmx_source = _MVMXSource(
                _MmapSource(mapping, file_size),
                parsed.mvmx_stream,
                crypto,
            )
            return mvmx_source.read(offset, size)

    if parsed.raw_buffer is not None:
        return parsed.raw_buffer[offset : offset + size]
    if parsed.source_path is None:
        return b""
    with parsed.source_path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(size)


# ----------------------------------------------------------------------
# Virtual Member Rendering & Recursive Composition
# ----------------------------------------------------------------------


def _render_member_bytes(
    *,
    base_parsed: ParsedMIX | None,
    mix_ops: Sequence[MIXOp],
    segments: tuple[str, ...],
    context: MIXContext,
) -> bytes | None:
    head = segments[0]
    tail = segments[1:]
    head_id = _resolve_name_to_id(head)

    current: bytes | None = (
        read_mix_entry_bytes(base_parsed, head_id) if base_parsed is not None else None
    )

    if not tail:
        return _apply_leaf_member_ops(
            initial=current,
            target_id=head_id,
            mix_ops=mix_ops,
            context=context,
        )

    nested_ops: list[MIXOp] = []
    for op in mix_ops:
        if isinstance(op, MIXArchiveOp) and not op.target_path:
            parsed = open_mix_archive(op.source_path, context=context)
            found = read_mix_entry_bytes(parsed, head_id)
            if found is not None:
                current = found
                nested_ops.clear()
        elif len(op.target_path) == 1 and _resolve_name_to_id(op.target_path[0]) == (
            head_id
        ):
            if isinstance(op, MIXFileOp):
                current = _read_file_op_bytes(op)
                nested_ops.clear()
            elif isinstance(op, MIXArchiveOp):
                nested_ops.append(_peel_op(op))
        elif len(op.target_path) > 1 and _resolve_name_to_id(op.target_path[0]) == (
            head_id
        ):
            nested_ops.append(_peel_op(op))

    child_parsed = (
        open_mix_bytes(current, label=Path(head), context=context)
        if current is not None
        else None
    )
    return _render_member_bytes(
        base_parsed=child_parsed,
        mix_ops=nested_ops,
        segments=tail,
        context=context,
    )


def _apply_leaf_member_ops(
    *,
    initial: bytes | None,
    target_id: int,
    mix_ops: Sequence[MIXOp],
    context: MIXContext,
) -> bytes | None:
    current = initial
    pending_patches: list[PatchSpec] = []

    def _flush_patches() -> None:
        nonlocal current
        if not pending_patches:
            return
        base_text = (
            current.decode("utf-8", errors="replace") if current is not None else ""
        )
        current = apply_patch_chain(base_text, pending_patches).encode("utf-8")
        pending_patches.clear()

    for op in mix_ops:
        if isinstance(op, MIXArchiveOp) and not op.target_path:
            parsed = open_mix_archive(op.source_path, context=context)
            found = read_mix_entry_bytes(parsed, target_id)
            if found is not None:
                pending_patches.clear()
                current = found
        elif len(op.target_path) == 1 and _resolve_name_to_id(op.target_path[0]) == (
            target_id
        ):
            if isinstance(op, MIXFileOp):
                pending_patches.clear()
                current = _read_file_op_bytes(op)
            elif isinstance(op, MIXPatchOp):
                pending_patches.append(op.patch)

    _flush_patches()
    return current


# Mutable assembly state scoped to a single compose_mix_archive call.
@dataclass(slots=True)
class _ComposedMIXState:
    parsed_archives: list[ParsedMIX]
    archive_refs: dict[int, tuple[int, MIXEntry]]
    memory_blobs: dict[int, bytes]
    known_names: dict[int, str]
    lmd_order: list[str]
    lmd_game: int = _LMD_GAME_DEFAULT


def _compose_state_to_bytes(
    *,
    base_parsed: ParsedMIX | None,
    mix_ops: Sequence[MIXOp],
    context: MIXContext,
    depth: int,
    diag_path: Path,
) -> bytes:
    state = _build_composed_state(
        base_parsed=base_parsed,
        mix_ops=mix_ops,
        context=context,
        depth=depth,
    )
    buffer = io.BytesIO()
    _write_standard_mix_to_stream(
        write_fn=buffer.write,
        state=state,
        diag_path=diag_path,
    )
    return buffer.getvalue()


def _build_composed_state(
    *,
    base_parsed: ParsedMIX | None,
    mix_ops: Sequence[MIXOp],
    context: MIXContext,
    depth: int,
) -> _ComposedMIXState:
    state = _ComposedMIXState(
        parsed_archives=[],
        archive_refs={},
        memory_blobs={},
        known_names={},
        lmd_order=[],
    )
    if base_parsed is not None:
        _merge_parsed_archive(state, base_parsed)

    idx = 0
    total = len(mix_ops)
    while idx < total:
        idx = _advance_mix_op(
            state,
            mix_ops,
            idx,
            context=context,
            depth=depth,
        )

    if depth < _MIX_NESTING_DEPTH_MAX:
        _decrypt_nested_archive_members(state, context=context, depth=depth)

    _rebuild_lmd_entry(state)
    return state


def _advance_mix_op(
    state: _ComposedMIXState,
    mix_ops: Sequence[MIXOp],
    idx: int,
    *,
    context: MIXContext,
    depth: int,
) -> int:
    op = mix_ops[idx]
    if isinstance(op, MIXArchiveOp) and not op.target_path:
        _merge_parsed_archive(state, open_mix_archive(op.source_path, context=context))
        return idx + 1
    if isinstance(op, MIXFileOp) and len(op.target_path) == 1:
        _apply_loose_file_op(state, op, context=context, depth=depth)
        return idx + 1
    if isinstance(op, MIXPatchOp) and len(op.target_path) == 1:
        return _consume_patch_batch(state, first=op, mix_ops=mix_ops, start=idx)
    return _consume_nested_batch(state, mix_ops, idx, context=context, depth=depth)


def _consume_patch_batch(
    state: _ComposedMIXState,
    *,
    first: MIXPatchOp,
    mix_ops: Sequence[MIXOp],
    start: int,
) -> int:
    target_id = _resolve_name_to_id(first.target_path[0])
    batch: list[PatchSpec] = [first.patch]
    _record_known_name(state, target_id, first.target_path[0])
    cursor = start + 1
    while cursor < len(mix_ops):
        nxt = mix_ops[cursor]
        if (
            isinstance(nxt, MIXPatchOp)
            and len(nxt.target_path) == 1
            and _resolve_name_to_id(nxt.target_path[0]) == target_id
        ):
            batch.append(nxt.patch)
            cursor += 1
        else:
            break
    _apply_patch_batch(state, target_id, batch)
    return cursor


def _consume_nested_batch(
    state: _ComposedMIXState,
    mix_ops: Sequence[MIXOp],
    start: int,
    *,
    context: MIXContext,
    depth: int,
) -> int:
    first = mix_ops[start]
    child_name = first.target_path[0]
    child_id = _resolve_name_to_id(child_name)
    child_ops: list[MIXOp] = [_peel_op(first)]
    cursor = start + 1
    while cursor < len(mix_ops):
        nxt = mix_ops[cursor]
        if (
            nxt.target_path
            and _resolve_name_to_id(nxt.target_path[0]) == child_id
            and not (isinstance(nxt, MIXFileOp) and len(nxt.target_path) == 1)
        ):
            child_ops.append(_peel_op(nxt))
            cursor += 1
        else:
            break
    _apply_nested_mix_ops(
        state,
        child_name=child_name,
        child_ops=child_ops,
        context=context,
        depth=depth,
    )
    return cursor


def _merge_parsed_archive(state: _ComposedMIXState, parsed: ParsedMIX) -> None:
    arch_idx = len(state.parsed_archives)
    state.parsed_archives.append(parsed)
    state.lmd_game = parsed.lmd_game
    state.lmd_order.extend(parsed.lmd_order)
    state.known_names.update(parsed.lmd_names)
    for entry in parsed.entries:
        if entry.id == LMD_ID:
            continue
        state.archive_refs[entry.id] = (arch_idx, entry)
        state.memory_blobs.pop(entry.id, None)


def _apply_loose_file_op(
    state: _ComposedMIXState,
    op: MIXFileOp,
    *,
    context: MIXContext,
    depth: int,
) -> None:
    target_name = op.target_path[0]
    entry_id = _resolve_name_to_id(target_name)
    if entry_id == LMD_ID:
        return
    if (
        depth < _MIX_NESTING_DEPTH_MAX
        and target_name.casefold().endswith(_MIX_SUFFIX)
        and probe_mix_file(op.source_path).needs_decryption
    ):
        payload = _compose_state_to_bytes(
            base_parsed=open_mix_archive(op.source_path, context=context),
            mix_ops=(),
            context=context,
            depth=depth + 1,
            diag_path=op.source_path,
        )
    else:
        payload = _read_file_op_bytes(op)

    state.memory_blobs[entry_id] = payload
    state.archive_refs.pop(entry_id, None)
    _record_known_name(state, entry_id, target_name)


def _apply_patch_batch(
    state: _ComposedMIXState,
    entry_id: int,
    patches: Sequence[PatchSpec],
) -> None:
    raw_base = _extract_current_member(state, entry_id)
    base_text = (
        raw_base.decode("utf-8", errors="replace") if raw_base is not None else ""
    )
    merged = apply_patch_chain(base_text, patches)
    state.memory_blobs[entry_id] = merged.encode("utf-8")
    state.archive_refs.pop(entry_id, None)


def _apply_nested_mix_ops(
    state: _ComposedMIXState,
    *,
    child_name: str,
    child_ops: Sequence[MIXOp],
    context: MIXContext,
    depth: int,
) -> None:
    if depth >= _MIX_NESTING_DEPTH_MAX:
        detail = f"MIX nesting depth exceeds limit ({_MIX_NESTING_DEPTH_MAX})"
        raise OverlayError.invalid_mix(Path(child_name), detail)
    child_id = _resolve_name_to_id(child_name)
    current = _extract_current_member(state, child_id)
    child_label = Path(child_name)
    child_parsed = (
        open_mix_bytes(current, label=child_label, context=context)
        if current is not None
        else None
    )
    composed = _compose_state_to_bytes(
        base_parsed=child_parsed,
        mix_ops=child_ops,
        context=context,
        depth=depth + 1,
        diag_path=child_label,
    )
    state.memory_blobs[child_id] = composed
    state.archive_refs.pop(child_id, None)
    _record_known_name(state, child_id, child_name)


def _decrypt_nested_archive_members(
    state: _ComposedMIXState,
    *,
    context: MIXContext,
    depth: int,
) -> None:
    for entry_id in list(state.archive_refs):
        if entry_id == LMD_ID or entry_id in state.memory_blobs:
            continue
        arch_idx, entry = state.archive_refs[entry_id]
        if entry.size < _OLD_HEADER_BYTES:
            continue
        parsed = state.parsed_archives[arch_idx]
        known_name = state.known_names.get(entry_id)
        is_named_mix = known_name is not None and known_name.casefold().endswith(
            _MIX_SUFFIX
        )
        head = _read_entry_prefix(parsed, entry, min(entry.size, _NEW_HEADER_BYTES))
        is_custom_magic = (
            len(head) >= _MVMX_MAGIC_BYTES and head[:_MVMX_MAGIC_BYTES] == _MVMX_MAGIC
        ) or _matches_fw_crypto_header(head, entry.size, exact=True)
        if not (is_named_mix or is_custom_magic):
            continue

        raw_member = read_mix_entry_bytes(parsed, entry_id)
        if raw_member is None:
            continue
        if not _probe_source(
            _MemorySource(raw_member), depth=depth + 1
        ).needs_decryption:
            continue
        member_label = Path(known_name or f"_{entry_id:08X}.mix")
        try:
            decrypted = _compose_state_to_bytes(
                base_parsed=open_mix_bytes(
                    raw_member,
                    label=member_label,
                    context=context,
                ),
                mix_ops=(),
                context=context,
                depth=depth + 1,
                diag_path=member_label,
            )
        except OverlayError:
            if is_named_mix:
                raise
            continue
        state.memory_blobs[entry_id] = decrypted
        state.archive_refs.pop(entry_id, None)


def _read_entry_prefix(parsed: ParsedMIX, entry: MIXEntry, length: int) -> bytes:
    raw = _read_raw_span(parsed, parsed.body_offset + entry.offset, length)
    if parsed.body_xor_key is not None:
        return xor_key1024(raw, parsed.body_xor_key, entry.offset)
    return raw


def _extract_current_member(state: _ComposedMIXState, entry_id: int) -> bytes | None:
    if entry_id in state.memory_blobs:
        return state.memory_blobs[entry_id]
    ref = state.archive_refs.get(entry_id)
    if ref is None:
        return None
    arch_idx, entry = ref
    return read_mix_entry_bytes(state.parsed_archives[arch_idx], entry.id)


def _read_file_op_bytes(op: MIXFileOp) -> bytes:
    try:
        return op.source_path.read_bytes()
    except OSError as exc:
        raise OverlayError.unreadable_file(op.source_path, str(exc)) from exc


def _peel_op(op: MIXOp) -> MIXOp:
    match op:
        case MIXArchiveOp():
            return replace(op, target_path=op.target_path[1:])
        case MIXFileOp():
            return replace(op, target_path=op.target_path[1:])
        case MIXPatchOp():
            return replace(op, target_path=op.target_path[1:])
        case _:
            assert_never(op)


def _record_known_name(state: _ComposedMIXState, entry_id: int, name: str) -> None:
    if _is_valid_mix_name(name) and not _RAW_ID_RE.match(name):
        state.known_names[entry_id] = name


def _resolve_name_to_id(name: str) -> int:
    raw_match = _RAW_ID_RE.match(name)
    if raw_match is not None:
        return int(raw_match.group(1), 16)
    return mix_id(name)


def _rebuild_lmd_entry(state: _ComposedMIXState) -> None:
    all_ids = set(state.archive_refs) | set(state.memory_blobs)
    present = {
        state.known_names[entry_id].casefold(): state.known_names[entry_id]
        for entry_id in all_ids
        if entry_id in state.known_names and entry_id != LMD_ID
    }
    if not present:
        return
    ordered: list[str] = []
    for name in state.lmd_order:
        folded = name.casefold()
        if folded in present:
            ordered.append(present.pop(folded))
    ordered.extend(sorted(present.values(), key=str.casefold))
    state.memory_blobs[LMD_ID] = build_lmd_blob(ordered, game=state.lmd_game)
    state.archive_refs.pop(LMD_ID, None)


# ----------------------------------------------------------------------
# Standard MIX Streaming Writer
# ----------------------------------------------------------------------


def _plan_body_layout(
    state: _ComposedMIXState,
) -> tuple[list[int], dict[int, tuple[int, int]]]:
    archived_ids = sorted(
        (
            entry_id
            for entry_id in state.archive_refs
            if entry_id not in state.memory_blobs
        ),
        key=lambda entry_id: (
            state.archive_refs[entry_id][0],
            state.archive_refs[entry_id][1].offset,
        ),
    )
    memory_ids = sorted(state.memory_blobs, key=signed_id)
    write_order = [*archived_ids, *memory_ids]

    layout: dict[int, tuple[int, int]] = {}
    cursor = 0
    for entry_id in write_order:
        if entry_id in state.memory_blobs:
            size = len(state.memory_blobs[entry_id])
        else:
            _, entry = state.archive_refs[entry_id]
            size = entry.size
        layout[entry_id] = (cursor, size)
        cursor += size
    return write_order, layout


def _write_standard_mix_to_stream(
    *,
    write_fn: Callable[[bytes], object],
    state: _ComposedMIXState,
    diag_path: Path,
) -> None:
    write_order, layout = _plan_body_layout(state)
    index_order = sorted(layout, key=signed_id)
    if len(index_order) > _MIX_ENTRIES_MAX:
        detail = f"too many MIX entries ({len(index_order)} > {_MIX_ENTRIES_MAX})"
        raise OverlayError.invalid_mix(diag_path, detail)

    total_body = sum(size for _, size in layout.values())
    header_and_index = bytearray(_NEW_HEADER_BYTES + _ENTRY_BYTES * len(index_order))
    _HDR_NEW_STRUCT.pack_into(header_and_index, 0, 0, len(index_order), total_body)
    for idx, entry_id in enumerate(index_order):
        out_offset, out_size = layout[entry_id]
        _IDX_STRUCT.pack_into(
            header_and_index,
            _NEW_HEADER_BYTES + _ENTRY_BYTES * idx,
            entry_id,
            out_offset,
            out_size,
        )
    write_fn(bytes(header_and_index))
    _stream_mix_bodies(write_fn=write_fn, write_order=write_order, state=state)


def _write_standard_mix_atomic(
    *,
    target_path: Path,
    state: _ComposedMIXState,
) -> None:
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
            _write_standard_mix_to_stream(
                write_fn=out_handle.write,
                state=state,
                diag_path=target_path,
            )
        temp_path.replace(target_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _open_archive_reader(
    stack: ExitStack,
    arch: ParsedMIX,
    crypto: MIXCrypto,
) -> tuple[io.BufferedReader | None, _MVMXSource | None]:
    if arch.raw_buffer is not None:
        mvmx_reader = (
            _MVMXSource(_MemorySource(arch.raw_buffer), arch.mvmx_stream, crypto)
            if arch.mvmx_stream is not None
            else None
        )
        return None, mvmx_reader
    if arch.source_path is None:
        return None, None
    handle = stack.enter_context(arch.source_path.open("rb"))
    if arch.mvmx_stream is None:
        return handle, None
    mapping = stack.enter_context(
        mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
    )
    mvmx_reader = _MVMXSource(
        _MmapSource(mapping, arch.source_path.stat().st_size),
        arch.mvmx_stream,
        crypto,
    )
    return handle, mvmx_reader


def _stream_mix_bodies(
    *,
    write_fn: Callable[[bytes], object],
    write_order: Sequence[int],
    state: _ComposedMIXState,
) -> None:
    crypto = default_crypto()
    with ExitStack() as stack:
        readers = [
            _open_archive_reader(stack, arch, crypto) for arch in state.parsed_archives
        ]
        for entry_id in write_order:
            blob = state.memory_blobs.get(entry_id)
            if blob is not None:
                if blob:
                    write_fn(blob)
                continue

            arch_idx, entry = state.archive_refs[entry_id]
            if entry.size == 0:
                continue
            source_handle, mvmx_reader = readers[arch_idx]
            _stream_single_entry(
                write_fn=write_fn,
                parsed=state.parsed_archives[arch_idx],
                entry=entry,
                source_handle=source_handle,
                mvmx_reader=mvmx_reader,
            )


def _stream_single_entry(
    *,
    write_fn: Callable[[bytes], object],
    parsed: ParsedMIX,
    entry: MIXEntry,
    source_handle: io.BufferedReader | None,
    mvmx_reader: _MVMXSource | None,
) -> None:
    remaining = entry.size
    rel_offset = entry.offset
    abs_offset = parsed.body_offset + entry.offset
    chunk_limit = (
        _XOR_CHUNK_BYTES if parsed.body_xor_key is not None else _IO_CHUNK_BYTES
    )

    if source_handle is not None and mvmx_reader is None:
        source_handle.seek(abs_offset)

    while remaining > 0:
        step = min(chunk_limit, remaining)
        if mvmx_reader is not None:
            chunk = mvmx_reader.read(abs_offset, step)
        elif parsed.raw_buffer is not None:
            chunk = parsed.raw_buffer[abs_offset : abs_offset + step]
        elif source_handle is not None:
            chunk = source_handle.read(step)
        else:
            chunk = b""

        if not chunk:
            diag = parsed.source_path or Path("<memory.mix>")
            detail = f"unexpected EOF while streaming {diag}"
            raise OverlayError.invalid_mix(diag, detail)

        if parsed.body_xor_key is not None:
            chunk = xor_key1024(chunk, parsed.body_xor_key, rel_offset)
        write_fn(chunk)
        nbytes = len(chunk)
        abs_offset += nbytes
        rel_offset += nbytes
        remaining -= nbytes


# ----------------------------------------------------------------------
# Strategy S1..S5 Parsers & Decryptors
# ----------------------------------------------------------------------


def _try_standard(
    source_path: Path | None,
    source: _ByteSource,
    base: int,
    limit: int,
) -> ParsedMIX | None:
    parsed = _parse_standard_header_and_entries(source, base, limit)
    if parsed is None:
        return None
    flags, body_offset, body_size, entries = parsed
    entries.sort(key=lambda item: signed_id(item.id))
    lmd_names, lmd_order, lmd_game = _extract_lmd(
        _LMDExtractRequest(
            source=source,
            body_offset=body_offset,
            limit=limit,
            entries=entries,
        )
    )
    return ParsedMIX(
        source_path=source_path,
        strategy=MIXStrategy.STANDARD,
        flags=flags,
        body_offset=body_offset,
        body_size=body_size,
        entries=tuple(entries),
        lmd_names=frozendict(lmd_names),
        lmd_order=lmd_order,
        lmd_game=lmd_game,
    )


def _parse_mvmx(scope: _ParseScope) -> ParsedMIX:
    spec = _parse_mvmx_spec(scope)
    mvmx_source = _MVMXSource(scope.source, spec, scope.crypto)
    inner_scope = replace(
        scope,
        source=mvmx_source,
        base=0,
        limit=spec.original_size,
    )
    try:
        inner = _dispatch_strategies(inner_scope)
    except (ValueError, zlib.error) as exc:
        raise OverlayError.invalid_mix(scope.diag_path, str(exc)) from exc

    if inner is None:
        detail = "decrypted MVMXV1 payload is not a valid MIX archive"
        raise OverlayError.invalid_mix(scope.diag_path, detail)

    return replace(inner, strategy=MIXStrategy.MVMX, mvmx_stream=spec)


def _parse_mvmx_spec(scope: _ParseScope) -> _MVMXStreamSpec:
    source = scope.source
    base = scope.base
    limit = scope.limit
    diag_path = scope.diag_path
    if limit - base < _MVMX_HEADER_BYTES:
        detail = "truncated MVMXV1 header"
        raise OverlayError.invalid_mix(diag_path, detail)
    header = source.read(base, _MVMX_HEADER_BYTES)
    if header[:_MVMX_MAGIC_BYTES] != _MVMX_MAGIC:
        detail = "invalid MVMXV1 magic"
        raise OverlayError.invalid_mix(diag_path, detail)

    (
        version,
        _reserved,
        header_size,
        flags,
        _chunk_size,
        chunk_count,
        original_size,
        meta_size,
        policy_size,
    ) = _MVMX_HDR_STRUCT.unpack_from(header, _MVMX_MAGIC_BYTES)
    if version != _MVMX_VERSION or header_size != _MVMX_HEADER_BYTES:
        detail = f"unsupported MVMXV1 version/header ({version}/{header_size})"
        raise OverlayError.invalid_mix(diag_path, detail)
    expected_crc = int(_U32_LE.unpack_from(header, _MVMX_SHA_END)[0])
    if expected_crc != (binascii.crc32(header[:_MVMX_SHA_END]) & _MASK_32):
        detail = "MVMXV1 header CRC32 mismatch"
        raise OverlayError.invalid_mix(diag_path, detail)

    policy_start = base + _MVMX_HEADER_BYTES
    meta_start = policy_start + int(policy_size)
    chunks_start = meta_start + int(meta_size)
    if chunks_start > limit:
        detail = "MVMXV1 policy/metadata extends past EOF"
        raise OverlayError.invalid_mix(diag_path, detail)

    policy_bytes = source.read(policy_start, int(policy_size))
    header_hash = hashlib.sha256(
        header[:_MVMX_SHA_SPLIT] + _MVMX_SHA_ZERO_PAD + policy_bytes
    ).digest()
    if header_hash != header[_MVMX_SHA_SPLIT:_MVMX_SHA_END]:
        detail = "MVMXV1 header/policy SHA-256 mismatch"
        raise OverlayError.invalid_mix(diag_path, detail)

    salt = header[_MVMX_SALT_START:_MVMX_SALT_END]
    nonce_prefix = header[_MVMX_SALT_END:_MVMX_NONCE_END]
    header_aad = header[_MVMX_NONCE_END:_MVMX_SHA_END]

    try:
        secret = resolve_mvmx_secret(
            scope.context.search_dirs,
            explicit_hex=scope.context.mvmx_secret_hex,
        )
        meta_key, data_key = derive_mvmx_keys(secret, salt)
        meta_ciphertext = source.read(meta_start, int(meta_size))
        meta_plain = scope.crypto.aes_gcm_decrypt(
            meta_key,
            nonce_prefix + _MVMX_META_NONCE_TAIL,
            _MVMX_META_AAD_PREFIX + header_aad,
            meta_ciphertext,
        )
        _ = json.loads(meta_plain.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        detail = f"MVMXV1 metadata decryption failed: {exc}"
        raise OverlayError.invalid_mix(diag_path, detail) from exc

    chunks = _build_mvmx_chunk_table(
        scope,
        start=chunks_start,
        chunk_count=int(chunk_count),
        original_size=int(original_size),
    )
    return _MVMXStreamSpec(
        data_key=data_key,
        nonce_prefix=nonce_prefix,
        header_aad=header_aad,
        compressed=bool(flags & _MVMX_FLAG_COMPRESSED),
        original_size=int(original_size),
        chunks=chunks,
    )


def _build_mvmx_chunk_table(
    scope: _ParseScope,
    *,
    start: int,
    chunk_count: int,
    original_size: int,
) -> tuple[_MVMXChunk, ...]:
    source = scope.source
    limit = scope.limit
    diag_path = scope.diag_path
    pos = start
    plain_cursor = 0
    chunks: list[_MVMXChunk] = []
    for idx in range(chunk_count):
        if pos + _MVMX_CHUNK_HEADER_BYTES > limit:
            detail = f"MVMXV1 chunk {idx} header truncated"
            raise OverlayError.invalid_mix(diag_path, detail)
        plain_size, stored_size, cipher_size = _MVMX_CHUNK_STRUCT.unpack(
            source.read(pos, _MVMX_CHUNK_HEADER_BYTES)
        )
        cipher_offset = pos + _MVMX_CHUNK_HEADER_BYTES
        if cipher_size < _MVMX_GCM_TAG_BYTES or cipher_offset + cipher_size > limit:
            detail = f"MVMXV1 chunk {idx} ciphertext out of bounds"
            raise OverlayError.invalid_mix(diag_path, detail)
        chunks.append(
            _MVMXChunk(
                idx,
                plain_cursor,
                plain_size,
                cipher_offset,
                stored_size,
                cipher_size,
            )
        )
        plain_cursor += plain_size
        pos = cipher_offset + cipher_size

    if plain_cursor != original_size:
        detail = (
            f"MVMXV1 chunk total ({plain_cursor}) != header orig_size ({original_size})"
        )
        raise OverlayError.invalid_mix(diag_path, detail)
    return tuple(chunks)


def _try_fw_crypto(
    source_path: Path | None,
    source: _ByteSource,
    base: int,
    limit: int,
) -> ParsedMIX | None:
    if limit - base < _NEW_HEADER_BYTES:
        return None
    header = source.read(base, _NEW_HEADER_BYTES)
    if not _matches_fw_crypto_header(header, limit - base):
        return None
    raw_flags, raw_count, raw_body = _HDR_NEW_STRUCT.unpack_from(header, 0)
    flags, count, body_size = int(raw_flags), int(raw_count), int(raw_body)
    index_offset = base + _NEW_HEADER_BYTES
    body_offset = index_offset + _ENTRY_BYTES * count

    rc4_key = base64.b64encode(header[4:_NEW_HEADER_BYTES])
    raw_index = source.read(index_offset, _ENTRY_BYTES * count)
    decrypted_index = rc4_sub_decrypt(raw_index, rc4_key)
    body_key = mt19937_key1024(fnv1a_32(raw_index))

    seen: set[int] = set()
    entries: list[MIXEntry] = []
    for entry_id, offset, size in _IDX_STRUCT.iter_unpack(decrypted_index):
        if offset + size > body_size:
            return None
        if entry_id not in seen:
            seen.add(entry_id)
            entries.append(MIXEntry(entry_id, offset, size))
    if not entries:
        return None

    entries.sort(key=lambda item: signed_id(item.id))
    lmd_names, lmd_order, lmd_game = _extract_lmd(
        _LMDExtractRequest(
            source=source,
            body_offset=body_offset,
            limit=limit,
            entries=entries,
            body_xor_key=body_key,
        )
    )
    return ParsedMIX(
        source_path=source_path,
        strategy=MIXStrategy.FW_CRYPTO,
        flags=flags,
        body_offset=body_offset,
        body_size=body_size,
        entries=tuple(entries),
        lmd_names=frozendict(lmd_names),
        lmd_order=lmd_order,
        lmd_game=lmd_game,
        body_xor_key=body_key,
    )


def _try_westwood(
    source_path: Path | None,
    source: _ByteSource,
    base: int,
    limit: int,
    crypto: MIXCrypto,
) -> ParsedMIX | None:
    if limit - base < _WESTWOOD_SIZE_BYTES_MIN:
        return None
    lead = source.read(base, _WESTWOOD_SIZE_BYTES_MIN)
    flags = int(_U32_LE.unpack_from(lead, 0)[0])
    if not (flags & _FLAG_ENCRYPTED) or (flags & ~(_FLAG_ENCRYPTED | _FLAG_CHECKSUM)):
        return None
    has_checksum = bool(flags & _FLAG_CHECKSUM)

    blowfish_key = westwood_blowfish_key(lead[4:_WESTWOOD_HEADER_END])
    if blowfish_key is None:
        return None
    first_block = crypto.blowfish_ecb_decrypt(
        blowfish_key,
        lead[_WESTWOOD_HEADER_END:_WESTWOOD_SIZE_BYTES_MIN],
    )
    count, body_size = _HDR_OLD_STRUCT.unpack_from(first_block, 0)
    encrypted_total = (
        (_OLD_HEADER_BYTES + _ENTRY_BYTES * count + _WESTWOOD_BF_BLOCK_BYTES - 1)
        // _WESTWOOD_BF_BLOCK_BYTES
    ) * _WESTWOOD_BF_BLOCK_BYTES
    body_offset = base + _WESTWOOD_HEADER_END + encrypted_total
    if count == 0 or body_offset > limit:
        return None

    rest = (
        crypto.blowfish_ecb_decrypt(
            blowfish_key,
            source.read(
                base + _WESTWOOD_SIZE_BYTES_MIN,
                encrypted_total - _WESTWOOD_BF_BLOCK_BYTES,
            ),
        )
        if encrypted_total > _WESTWOOD_BF_BLOCK_BYTES
        else b""
    )
    decrypted_index = first_block + rest

    in_bounds: list[MIXEntry] = []
    has_oob_or_dups = False
    seen: set[int] = set()
    index_slice = memoryview(decrypted_index)[
        _OLD_HEADER_BYTES : _OLD_HEADER_BYTES + _ENTRY_BYTES * count
    ]
    for entry_id, offset, size in _IDX_STRUCT.iter_unpack(index_slice):
        if (
            _SENTINEL_U32 in (offset, size)
            or body_offset + offset + size > limit
            or entry_id in seen
        ):
            has_oob_or_dups = True
        else:
            seen.add(entry_id)
            in_bounds.append(MIXEntry(entry_id, offset, size))

    if not in_bounds:
        return None

    expected = body_offset + body_size + (_SHA1_BYTES if has_checksum else 0)
    strategy = MIXStrategy.WESTWOOD
    carved_lmd: tuple[dict[int, str], tuple[str, ...], int] | None = None
    if has_oob_or_dups or expected != limit:
        strategy = MIXStrategy.WESTWOOD_SANITIZE
        carved_lmd = _carve_orphaned_lmds(
            source,
            body_offset,
            limit,
            frozenset(item.id for item in in_bounds),
        )
        in_bounds = _resolve_overlapping_decoys(
            in_bounds,
            source,
            body_offset,
            frozenset(carved_lmd[0]),
        )
        body_size = max((item.offset + item.size for item in in_bounds), default=0)
    else:
        in_bounds.sort(key=lambda item: signed_id(item.id))

    lmd_names, lmd_order, lmd_game = _extract_lmd(
        _LMDExtractRequest(
            source=source,
            body_offset=body_offset,
            limit=limit,
            entries=in_bounds,
            precarved=carved_lmd,
        )
    )
    return ParsedMIX(
        source_path=source_path,
        strategy=strategy,
        flags=flags,
        body_offset=body_offset,
        body_size=body_size,
        entries=tuple(in_bounds),
        lmd_names=frozendict(lmd_names),
        lmd_order=lmd_order,
        lmd_game=lmd_game,
    )


def _try_sanitize(
    source_path: Path | None,
    source: _ByteSource,
    base: int,
    limit: int,
) -> ParsedMIX | None:
    parsed = _parse_sanitize_candidates(source, base, limit)
    if parsed is None:
        return None
    flags, body_offset, in_bounds = parsed

    carved = _carve_orphaned_lmds(
        source,
        body_offset,
        limit,
        frozenset(item.id for item in in_bounds),
    )
    clean = _resolve_overlapping_decoys(
        in_bounds,
        source,
        body_offset,
        frozenset(carved[0]),
    )
    max_end = max((item.offset + item.size for item in clean), default=0)
    lmd_names, lmd_order, lmd_game = _extract_lmd(
        _LMDExtractRequest(
            source=source,
            body_offset=body_offset,
            limit=limit,
            entries=clean,
            precarved=carved,
        )
    )
    return ParsedMIX(
        source_path=source_path,
        strategy=MIXStrategy.SANITIZE,
        flags=flags,
        body_offset=body_offset,
        body_size=max_end,
        entries=tuple(clean),
        lmd_names=frozendict(lmd_names),
        lmd_order=lmd_order,
        lmd_game=lmd_game,
    )


def _try_shifted(scope: _ParseScope) -> ParsedMIX | None:
    source = scope.source
    base = scope.base
    limit = scope.limit
    scan_end = min(limit, base + _SHIFTED_SCAN_BYTES_MAX)
    hit_mvmx = source.find(_MVMX_MAGIC, base + 1, scan_end)
    if hit_mvmx > base:
        inner = _parse_mvmx(replace(scope, base=hit_mvmx))
        return replace(inner, strategy=MIXStrategy.SHIFTED)

    scan_limit = min(limit - _SHIFTED_TAIL_BYTES_MIN, base + _SHIFTED_SCAN_BYTES_MAX)
    for sig in (b"\x00\x00\x00\x00", b"\x00\x00\x01\x00"):
        pos = base + 1
        while pos < scan_limit and (hit := source.find(sig, pos, scan_limit)) >= 0:
            found = _try_standard(scope.source_path, source, hit, limit) or (
                _try_sanitize(scope.source_path, source, hit, limit)
            )
            if found is not None and found.entries:
                return replace(found, strategy=MIXStrategy.SHIFTED)
            pos = hit + 4
    return None


def _try_count_recover(
    source_path: Path | None,
    source: _ByteSource,
    base: int,
    limit: int,
) -> ParsedMIX | None:
    for index_start in (base + _NEW_HEADER_BYTES, base + _OLD_HEADER_BYTES):
        if index_start + _ENTRY_BYTES > limit:
            continue
        candidates = _scan_monotonic_index(source, index_start, limit)
        if len(candidates) < _CARVED_HITS_MIN:
            continue
        best_count = _pick_best_index_prefix(source, index_start, limit, candidates)
        if best_count >= _CARVED_HITS_MIN:
            body_offset = index_start + _ENTRY_BYTES * best_count
            in_bounds = [
                item
                for item in candidates[:best_count]
                if _SENTINEL_U32 not in (item.offset, item.size)
                and body_offset + item.offset + item.size <= limit
            ]
            carved = _carve_orphaned_lmds(
                source,
                body_offset,
                limit,
                frozenset(item.id for item in in_bounds),
            )
            clean = _resolve_overlapping_decoys(
                in_bounds,
                source,
                body_offset,
                frozenset(carved[0]),
            )
            max_end = max(
                (item.offset + item.size for item in clean),
                default=0,
            )
            lmd_names, lmd_order, lmd_game = _extract_lmd(
                _LMDExtractRequest(
                    source=source,
                    body_offset=body_offset,
                    limit=limit,
                    entries=clean,
                    precarved=carved,
                )
            )
            return ParsedMIX(
                source_path=source_path,
                strategy=MIXStrategy.COUNT_RECOVER,
                flags=0 if index_start == base + _NEW_HEADER_BYTES else None,
                body_offset=body_offset,
                body_size=max_end,
                entries=tuple(clean),
                lmd_names=frozendict(lmd_names),
                lmd_order=lmd_order,
                lmd_game=lmd_game,
            )
    return None


def _scan_monotonic_index(
    source: _ByteSource,
    index_start: int,
    limit: int,
) -> list[MIXEntry]:
    candidates: list[MIXEntry] = []
    prev_signed_id = -_MOD_32
    pos = index_start
    while pos + _ENTRY_BYTES <= limit and len(candidates) < _MIX_ENTRIES_MAX:
        entry_id, offset, size = _IDX_STRUCT.unpack(source.read(pos, _ENTRY_BYTES))
        current_signed = signed_id(entry_id)
        if current_signed <= prev_signed_id:
            break
        is_sentinel = offset == _SENTINEL_U32 and size == _SENTINEL_U32
        if not is_sentinel and (
            offset > limit or size > limit or offset + size > limit
        ):
            break
        candidates.append(MIXEntry(entry_id, offset, size))
        prev_signed_id = current_signed
        pos += _ENTRY_BYTES
    return candidates


def _pick_best_index_prefix(
    source: _ByteSource,
    index_start: int,
    limit: int,
    candidates: Sequence[MIXEntry],
) -> int:
    best_count = 0
    best_score = -1
    for count in range(_CARVED_HITS_MIN, len(candidates) + 1):
        body_offset = index_start + _ENTRY_BYTES * count
        if body_offset > limit:
            break
        subset = candidates[:count]
        in_bounds_count = sum(
            1
            for item in subset
            if item.offset != _SENTINEL_U32
            and body_offset + item.offset + item.size <= limit
        )
        sentinel_count = sum(
            1
            for item in subset
            if item.offset == _SENTINEL_U32 and item.size == _SENTINEL_U32
        )
        out_of_bounds_count = count - in_bounds_count - sentinel_count
        if in_bounds_count < _CARVED_HITS_MIN or out_of_bounds_count > _CARVED_HITS_MIN:
            continue
        score = in_bounds_count * 100 - out_of_bounds_count * 500
        if any(item.offset == 0 for item in subset):
            score += 500
        max_end = max(
            (
                item.offset + item.size
                for item in subset
                if item.offset != _SENTINEL_U32
                and body_offset + item.offset + item.size <= limit
            ),
            default=0,
        )
        if body_offset + max_end in {limit, limit - _SHA1_BYTES}:
            score += 2000
        if any(
            item.id == LMD_ID
            and item.offset != _SENTINEL_U32
            and body_offset + item.offset + _XCC_ID_BYTES <= limit
            and source.read(body_offset + item.offset, _XCC_ID_BYTES) == _XCC_ID
            for item in subset
        ):
            score += 5000
        if score > best_score:
            best_score = score
            best_count = count
    return best_count


# ----------------------------------------------------------------------
# S4 Weighted Interval Scheduling DP, Content Magic & LMD Carving
# ----------------------------------------------------------------------


def _has_known_magic(head: bytes, size: int) -> bool:
    if size == 0 or not head:
        return True
    head_length = len(head)
    if _matches_simple_magic(head, head_length, size):
        return True
    if _matches_structured_magic(head, head_length, size):
        return True
    if b"\x00" not in head:
        printable = sum(
            1
            for byte in head
            if _ASCII_PRINTABLE_MIN <= byte < _ASCII_PRINTABLE_MAX
            or byte in {9, 10, 13}
            or byte >= _ASCII_HIGH_BIT
        )
        return printable >= head_length * _PRINTABLE_RATIO
    return False


def _matches_simple_magic(head: bytes, head_length: int, size: int) -> bool:
    if (
        (
            head_length >= _MAGIC_VXL_BYTES
            and head[:_MAGIC_VXL_BYTES] == b"Voxel Animation\x00"
        )
        or (
            head_length >= _MAGIC_WAV_BYTES
            and head[:_MAGIC_TAG_BYTES] == b"RIFF"
            and head[_MAGIC_SHP_BYTES:_MAGIC_WAV_BYTES] == b"WAVE"
        )
        or (
            head_length >= _MAGIC_TAG_BYTES
            and head[:_MAGIC_TAG_BYTES] in {b" FSC", b"GABA", b"DDS "}
        )
        or (head_length >= _MAGIC_BIK_BYTES and head[:_MAGIC_BIK_BYTES] == b"BIK")
        or (
            head_length >= _MVMX_MAGIC_BYTES
            and head[:_MVMX_MAGIC_BYTES] in {_MVMX_MAGIC, b"\x89PNG\r\n\x1a\n"}
        )
        or (head_length >= _XCC_ID_BYTES and head[:_XCC_ID_BYTES] == _XCC_ID)
    ):
        return True
    if size == _PALETTE_BYTES and max(head) <= _PALETTE_VALUE_MAX:
        return True
    return (
        head_length >= _MAGIC_TAG_BYTES
        and head[0] == _PCX_MAGIC_BYTE
        and head[1] in {0, 2, 3, 5}
        and head[2] == 1
        and head[3] in {1, 2, 4, 8}
    )


def _matches_structured_magic(head: bytes, head_length: int, size: int) -> bool:
    return _matches_media_header(head, head_length, size) or _matches_mix_header(
        head,
        head_length,
        size,
    )


def _matches_media_header(head: bytes, head_length: int, size: int) -> bool:
    if head_length >= _HVA_HEADER_BYTES_MIN:
        frames, sections = _U32_2_LE.unpack_from(head, _MAGIC_VXL_BYTES)
        if (
            0 < frames <= _HVA_FRAMES_MAX
            and 0 < sections <= _HVA_SECTIONS_MAX
            and _HVA_HEADER_BYTES_MIN + 16 * sections + 48 * frames * sections == size
        ):
            return True
    if head_length >= _TMP_HEADER_BYTES_MIN:
        block_x, block_y, tile_width, tile_height = _U32_4_LE.unpack_from(head, 0)
        if (
            (tile_width, tile_height) in {(48, 24), (60, 30)}
            and 1 <= block_x <= _TMP_DIMENSION_MAX
            and 1 <= block_y <= _TMP_DIMENSION_MAX
        ):
            return True
    if head_length >= _MAGIC_SHP_BYTES and head[:2] == b"\x00\x00":
        width, height, frames = _U16_3_LE.unpack_from(head, 2)
        if (
            0 < width <= _SHP_DIMENSION_MAX
            and 0 < height <= _SHP_DIMENSION_MAX
            and 0 < frames <= _SHP_FRAMES_MAX
            and _MAGIC_SHP_BYTES + 24 * frames <= size
        ):
            return True
    return False


def _matches_mix_header(head: bytes, head_length: int, size: int) -> bool:
    if head_length >= _NEW_HEADER_BYTES:
        flags, count, body_size = _HDR_NEW_STRUCT.unpack_from(head, 0)
        checksum_bytes = _SHA1_BYTES if (flags & _FLAG_CHECKSUM) else 0
        if (
            flags in {0, _FLAG_CHECKSUM}
            and count > 0
            and _NEW_HEADER_BYTES + _ENTRY_BYTES * count + body_size + checksum_bytes
            == size
        ):
            return True
        if _matches_fw_crypto_header(head, size, exact=True):
            return True
        if (
            flags in {_FLAG_ENCRYPTED, _FLAG_ENCRYPTED | _FLAG_CHECKSUM}
            and size >= _WESTWOOD_SIZE_BYTES_MIN
            and (
                head_length < _WW_ENTROPY_SLICE_END
                or sum(1 for byte in head[4:_WW_ENTROPY_SLICE_END] if byte)
                >= _WW_NON_ZERO_KEY_BYTES_MIN
            )
        ):
            return True
    if head_length >= _OLD_HEADER_BYTES:
        old_count, old_body_size = _HDR_OLD_STRUCT.unpack_from(head, 0)
        if (
            old_count > 0
            and _OLD_HEADER_BYTES + _ENTRY_BYTES * old_count + old_body_size == size
        ):
            return True
    return False


@dataclass(frozen=True, slots=True)
class _IntervalContext:
    source: _ByteSource
    body_offset: int
    trusted_ids: frozenset[int]
    majority_a16: bool
    all_starts: frozenset[int]
    all_ends: frozenset[int]
    all_ends_a16: frozenset[int]


def _resolve_overlapping_decoys(
    entries: Sequence[MIXEntry],
    source: _ByteSource,
    body_offset: int,
    trusted_ids: frozenset[int],
) -> list[MIXEntry]:
    if len(entries) <= 1:
        return list(entries)

    zero_entries: list[MIXEntry] = []
    range_groups: dict[tuple[int, int], list[MIXEntry]] = {}
    for entry in entries:
        if entry.size == 0:
            zero_entries.append(entry)
        else:
            range_groups.setdefault((entry.offset, entry.size), []).append(entry)

    intervals = sorted(
        (
            (offset, offset + size, group)
            for (offset, size), group in range_groups.items()
        ),
        key=lambda item: (item[0], -(item[1] - item[0])),
    )
    if not intervals:
        return zero_entries

    ctx = _IntervalContext(
        source=source,
        body_offset=body_offset,
        trusted_ids=trusted_ids,
        majority_a16=(
            sum(1 for offset, _, _ in intervals if (offset & _ALIGN_16_MASK) == 0)
            / len(intervals)
        )
        >= _MAJORITY_A16_RATIO,
        all_starts=frozenset(offset for offset, _, _ in intervals),
        all_ends=frozenset(end for _, end, _ in intervals),
        all_ends_a16=frozenset(
            (end + _ALIGN_16_MASK) & ~_ALIGN_16_MASK for _, end, _ in intervals
        ),
    )
    kept = list(zero_entries)

    component = [intervals[0]]
    component_max = intervals[0][1]
    for item in intervals[1:]:
        if item[0] < component_max:
            component.append(item)
            component_max = max(component_max, item[1])
        else:
            kept.extend(_solve_interval_component(component, ctx))
            component = [item]
            component_max = item[1]
    kept.extend(_solve_interval_component(component, ctx))
    kept.sort(key=lambda item: signed_id(item.id))
    return kept


def _score_interval(
    offset: int,
    end: int,
    group: Sequence[MIXEntry],
    ctx: _IntervalContext,
) -> int:
    size = end - offset
    weight = size
    in_lmd = any(item.id in ctx.trusted_ids for item in group)
    if in_lmd:
        weight += _WEIGHT_LMD
    left_ok = (
        offset == 0
        or offset in ctx.all_ends
        or (ctx.majority_a16 and offset in ctx.all_ends_a16)
    )
    right_ok = end in ctx.all_starts or (
        ctx.majority_a16
        and ((end + _ALIGN_16_MASK) & ~_ALIGN_16_MASK) in ctx.all_starts
    )
    if left_ok and right_ok:
        weight += _WEIGHT_BOTH_ADJ
    elif left_ok or right_ok:
        weight += _WEIGHT_ONE_ADJ
    if ctx.majority_a16 and (offset & _ALIGN_16_MASK) == 0:
        weight += _WEIGHT_A16
    head = ctx.source.read(ctx.body_offset + offset, min(_MAGIC_HEAD_BYTES, size))
    if _has_known_magic(head, size):
        weight += _WEIGHT_MAGIC
    if (
        offset < _DECOY_SMALL_BYTES_MAX
        and size < _DECOY_SMALL_BYTES_MAX
        and not in_lmd
        and ctx.majority_a16
        and (offset & _ALIGN_16_MASK) != 0
    ):
        weight -= _WEIGHT_SMALL_PENALTY
    return max(1, weight)


def _solve_interval_component(
    component: Sequence[tuple[int, int, list[MIXEntry]]],
    ctx: _IntervalContext,
) -> list[MIXEntry]:
    if len(component) == 1:
        return list(component[0][2])

    by_end = sorted(component, key=lambda item: (item[1], item[0]))
    count = len(by_end)
    ends = [item[1] for item in by_end]
    weights = [
        _score_interval(offset, end, group, ctx) for offset, end, group in by_end
    ]

    prev_ok = [bisect.bisect_right(ends, by_end[i][0]) - 1 for i in range(count)]
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

    out: list[MIXEntry] = []
    for idx, (_, _, group) in enumerate(by_end):
        if idx in chosen:
            out.extend(group)
    return out


@dataclass(frozen=True, slots=True)
class _LMDExtractRequest:
    source: _ByteSource
    body_offset: int
    limit: int
    entries: Sequence[MIXEntry]
    body_xor_key: bytes | None = None
    precarved: tuple[dict[int, str], tuple[str, ...], int] | None = None


def _extract_lmd(
    request: _LMDExtractRequest,
) -> tuple[dict[int, str], tuple[str, ...], int]:
    entry_ids = frozenset(item.id for item in request.entries)
    for entry in request.entries:
        if entry.id == LMD_ID:
            raw_blob = request.source.read(
                request.body_offset + entry.offset,
                entry.size,
            )
            blob = (
                xor_key1024(raw_blob, request.body_xor_key, entry.offset)
                if request.body_xor_key is not None
                else raw_blob
            )
            if len(blob) >= _LMD_HEADER_BYTES and blob[:_XCC_ID_BYTES] == _XCC_ID:
                names, game = parse_lmd_blob(blob)
                matched: dict[int, str] = {LMD_ID: LMD_FILENAME}
                for name in names:
                    entry_id = mix_id(name)
                    if entry_id in entry_ids and entry_id not in matched:
                        matched[entry_id] = name
                return matched, names, game

    if request.body_xor_key is not None:
        return {}, (), _LMD_GAME_DEFAULT
    if request.precarved is not None:
        prev_map, prev_order, prev_game = request.precarved
        filtered = {
            entry_id: name
            for entry_id, name in prev_map.items()
            if entry_id in entry_ids
        }
        return filtered, prev_order, prev_game

    active_ranges = tuple(
        sorted(
            (
                request.body_offset + item.offset,
                request.body_offset + item.offset + item.size,
            )
            for item in request.entries
            if item.size > 0
        )
    )
    return _carve_orphaned_lmds(
        request.source,
        request.body_offset,
        request.limit,
        entry_ids,
        active_ranges=active_ranges,
    )


def _carve_orphaned_lmds(
    source: _ByteSource,
    body_offset: int,
    limit: int,
    entry_ids: frozenset[int],
    *,
    active_ranges: Sequence[tuple[int, int]] = (),
) -> tuple[dict[int, str], tuple[str, ...], int]:
    best_map: dict[int, str] = {}
    best_order: tuple[str, ...] = ()
    best_game = _LMD_GAME_DEFAULT
    best_score = 0

    def _is_inside_active(pos_file: int) -> bool:
        if not active_ranges:
            return False
        idx = bisect.bisect_right(active_ranges, (pos_file, 1 << 62)) - 1
        return idx >= 0 and active_ranges[idx][0] <= pos_file < active_ranges[idx][1]

    pos = body_offset
    while pos < limit and (hit := source.find(_XCC_ID, pos, limit)) >= 0:
        if hit + _LMD_HEADER_BYTES <= limit:
            lmd_size = int(_U32_LE.unpack(source.read(hit + _XCC_ID_BYTES, 4))[0])
            if _LMD_HEADER_BYTES <= lmd_size <= min(_LMD_SIZE_BYTES_MAX, limit - hit):
                names, game = parse_lmd_blob(source.read(hit, lmd_size))
                matched: dict[int, str] = {}
                for name in names:
                    entry_id = mix_id(name)
                    if entry_id in entry_ids and entry_id not in matched:
                        matched[entry_id] = name
                real_hits = len(matched) - (1 if LMD_ID in matched else 0)
                score = real_hits * (1 if _is_inside_active(hit) else 2)
                if real_hits >= _CARVED_HITS_MIN and score > best_score:
                    best_score = score
                    best_map = matched
                    best_order = names
                    best_game = game
        pos = hit + _XCC_ID_BYTES
    return best_map, best_order, best_game
