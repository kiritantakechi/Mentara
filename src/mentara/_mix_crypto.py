"""Cryptographic primitives and PE helpers for MIX archive decryption.

Provides thread-safe AES-256-GCM and Blowfish-ECB decryption with
automatic OpenSSL `libcrypto` acceleration (via `ctypes`) and pure
Python fallbacks, plus Westwood RSA-320, CryptoRuntime RC4-sub / MT19937
XOR, and dynamic PE32 key extraction for MVMXV1 containers.
"""

import atexit
import ctypes
import ctypes.util
import hashlib
import hmac
import struct
import threading
from contextlib import contextmanager
from typing import Final
lazy from collections.abc import Buffer, Generator, Sequence
lazy from pathlib import Path

__all__ = [
    "MVMX_ROOT_LABEL",
    "MVMX_SECRET_HEX_DEFAULT",
    "WESTWOOD_KEY_SOURCE_BYTES",
    "MIXCrypto",
    "default_crypto",
    "derive_mvmx_keys",
    "extract_mvmx_secret_from_dll",
    "fnv1a_32",
    "is_pe_binary",
    "mt19937_key1024",
    "rc4_sub_decrypt",
    "resolve_mvmx_secret",
    "westwood_blowfish_key",
    "xor_key1024",
]

MVMX_ROOT_LABEL: Final[bytes] = b"MVMX-PROJECT-ROOT-V1\x00"
# Public format-level key embedded in open MVMXV1 loader binaries.
MVMX_SECRET_HEX_DEFAULT: Final[str] = (
    "5826d486360498d1a9f62afe94c53bc4b74c2ceaf83d7a4f2725a784567730dd"  # noqa: S105 - public MVMXV1 format constant
)
WESTWOOD_KEY_SOURCE_BYTES: Final[int] = 80

_MVMX_SECRET_BYTES: Final[int] = 32
_MVMX_META_INFO: Final[bytes] = b"MVX-METADATA-v1\x01"
_MVMX_DATA_INFO: Final[bytes] = b"MVX-DATA-v1\x01"
_MVLOADER_DLL_NAME: Final[str] = "MVLoader.dll"

# Decoded 320-bit Westwood public RSA modulus (from RA2/YR pubkey).
_WESTWOOD_EXP_E: Final[int] = 65537
_WESTWOOD_MODULUS: Final[int] = (
    0x51BCDA086D39FCE4565160D651713FA2E8AA54FA6682B04AABDD0E6AF8B0C1E6D1FB4F3DAA437F15
)
_WESTWOOD_RSA_BLOCK_IN_BYTES: Final[int] = 40
_WESTWOOD_RSA_BLOCK_OUT_BYTES: Final[int] = 39
_WESTWOOD_BLOWFISH_KEY_BYTES: Final[int] = 56

_MASK_32: Final[int] = 0xFFFFFFFF
_BYTE_MASK: Final[int] = 0xFF
_XOR_KEY_BYTES: Final[int] = 1024
_XOR_KEY_MASK: Final[int] = 1023
_XOR_CHUNK_BYTES: Final[int] = 256 << 10

_FNV1A_INIT: Final[int] = 0x811C9DC5
_FNV1A_PRIME: Final[int] = 0x01000193
_MT_STATE_WORDS: Final[int] = 624
_MT_PERIOD_OFFSET: Final[int] = 397
_MT_MULTIPLIER: Final[int] = 1812433253
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
_MT_OUTPUT_WORDS: Final[int] = 256
_RC4_STATE_BYTES: Final[int] = 256

_BF_ROUNDS: Final[int] = 16
_BF_P_WORDS: Final[int] = 18
_BF_S_BOXES: Final[int] = 4
_BF_S_ENTRIES: Final[int] = 256
_BF_TOTAL_WORDS: Final[int] = 1042
_BF_EXTRA_BITS: Final[int] = 64
_BF_BLOCK_BYTES: Final[int] = 8
_SHIFT_24: Final[int] = 24
_SHIFT_16: Final[int] = 16
_SHIFT_8: Final[int] = 8
_ARCCOT_5: Final[int] = 5
_ARCCOT_239: Final[int] = 239
_MACHIN_4: Final[int] = 4
_MACHIN_3: Final[int] = 3

_AES_KEY_BYTES: Final[int] = 32
_AES_BLOCK_BYTES: Final[int] = 16
_AES_GCM_NONCE_BYTES: Final[int] = 12
_AES_GCM_TAG_BYTES: Final[int] = 16
_AES_ROUND_KEY_WORDS: Final[int] = 60
_AES_ROUND_KEY_STRIDE: Final[int] = 8
_AES_ROUND_KEY_MID: Final[int] = 4
_AES_GF_POLY: Final[int] = 0x1B
_AES_SBOX_EXP: Final[int] = 254
_AES_SBOX_CONST: Final[int] = 0x63
_AES_GHASH_R: Final[int] = 0xE1000000000000000000000000000000
_AES_GHASH_BITS: Final[int] = 128
_AES_GHASH_NIBBLE_BITS: Final[int] = 4
_AES_GHASH_TABLE_ENTRIES: Final[int] = 16
_AES_GHASH_NIBBLE_MASK: Final[int] = 0xF
_AES_GHASH_R4_SHIFT: Final[int] = 112
_AES_GHASH_R4: Final[tuple[int, ...]] = (
    0x0000,
    0x1C20,
    0x3840,
    0x2460,
    0x7080,
    0x6CA0,
    0x48C0,
    0x54E0,
    0xE100,
    0xFD20,
    0xD940,
    0xC560,
    0x9180,
    0x8DA0,
    0xA9C0,
    0xB5E0,
)

_PE_DOS_BYTES_MIN: Final[int] = 0x40
_PE_LFANEW_OFFSET: Final[int] = 0x3C
_PE_OFFSET_BYTES_MAX: Final[int] = 1 << 20
_PE_DLL_BYTES_MIN: Final[int] = 0x100
_PE_MAGIC_PE32: Final[int] = 0x10B
_PE_SECTION_BYTES: Final[int] = 40
_PE_SECTION_COUNT_OFFSET: Final[int] = 6
_PE_OPTIONAL_SIZE_OFFSET: Final[int] = 20
_PE_OPTIONAL_HEADER_OFFSET: Final[int] = 24
_PE_IMAGE_BASE_OFFSET: Final[int] = 28
_PE_PUSH_SECRET_OPCODE: Final[bytes] = b"\x6a\x20\x68"
_PE_SCAN_WINDOW_BYTES: Final[int] = 64
_PE_OPCODE_VA_OFFSET: Final[int] = 3
_PE_OPCODE_BYTES: Final[int] = 7

_EVP_CTRL_GCM_SET_IVLEN: Final[int] = 0x9
_EVP_CTRL_GCM_SET_TAG: Final[int] = 0x11
_LIBCRYPTO_CANDIDATES: Final[tuple[str, ...]] = (
    "libcrypto.so.4",
    "libcrypto.so.3",
    "libcrypto.so.1.1",
    "libcrypto.dylib",
    "libcrypto-3-x64.dll",
    "libcrypto-1_1-x64.dll",
    "libcrypto.dll",
)

_U16_LE: Final[struct.Struct] = struct.Struct("<H")
_U32_LE: Final[struct.Struct] = struct.Struct("<I")
_U32_4_LE: Final[struct.Struct] = struct.Struct("<4I")
_U32_2_BE: Final[struct.Struct] = struct.Struct(">II")
_U32_3_BE: Final[struct.Struct] = struct.Struct(">3I")
_U32_4_BE: Final[struct.Struct] = struct.Struct(">4I")
_U32_8_BE: Final[struct.Struct] = struct.Struct(">8I")

type _AESTables = tuple[
    bytes,
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
]


class MIXCrypto:
    """Unified thread-safe cipher facade (OpenSSL -> pure Python)."""

    def __init__(self, *, force_pure: bool = False) -> None:
        """Initialise the cipher facade, probing OpenSSL unless pure."""
        self._ossl = None if force_pure else _OpenSSLBridge()
        self._cache_lock = threading.Lock()  # guards: _aes_cache and _bf_cache memos
        self._aes_cache: dict[bytes, _PureAES256GCM] = {}
        self._bf_cache: dict[bytes, _PureBlowfish] = {}

    @property
    def uses_openssl_aes(self) -> bool:
        """Return whether AES-256-GCM uses system OpenSSL."""
        return self._ossl is not None and self._ossl.available_aes_gcm

    @property
    def uses_openssl_blowfish(self) -> bool:
        """Return whether Blowfish-ECB uses system OpenSSL."""
        return self._ossl is not None and self._ossl.available_bf_ecb

    def aes_gcm_decrypt(
        self,
        key: bytes,
        nonce: bytes,
        aad: bytes,
        ciphertext_and_tag: Buffer,
    ) -> bytes:
        """Decrypt and verify an AES-256-GCM ciphertext + 16-byte tag.

        Args:
            key: 32-byte AES-256 key.
            nonce: 12-byte GCM nonce.
            aad: Additional authenticated data.
            ciphertext_and_tag: Concatenated ciphertext and 16-byte tag.

        Returns:
            Authenticated plaintext bytes.

        Raises:
            ValueError: If authentication fails or parameters are
                invalid.
        """
        if self._ossl is not None and self._ossl.available_aes_gcm:
            return self._ossl.aes_gcm_decrypt(key, nonce, aad, ciphertext_and_tag)
        with self._cache_lock:
            cipher = self._aes_cache.get(key)
            if cipher is None:
                cipher = _PureAES256GCM(key)
                self._aes_cache[key] = cipher
        return cipher.decrypt(nonce, aad, ciphertext_and_tag)

    def blowfish_ecb_decrypt(self, key: bytes, data: bytes) -> bytes:
        """Decrypt 8-byte-aligned Blowfish-ECB blocks.

        Args:
            key: Blowfish key (up to 56 bytes).
            data: Ciphertext whose length is a multiple of 8 bytes.

        Returns:
            Decrypted plaintext bytes.
        """
        if self._ossl is not None and self._ossl.available_bf_ecb:
            return self._ossl.blowfish_ecb_decrypt(key, data)
        with self._cache_lock:
            cipher = self._bf_cache.get(key)
            if cipher is None:
                cipher = _PureBlowfish(key)
                self._bf_cache[key] = cipher
        return cipher.decrypt_ecb(data)


_shared_crypto_lock: Final = threading.Lock()  # guards: _shared_crypto lazy singleton
_shared_crypto: MIXCrypto | None = None


def default_crypto() -> MIXCrypto:
    """Return the process-wide lazy `MIXCrypto` instance.

    Returns:
        Shared thread-safe `MIXCrypto` facade.
    """
    global _shared_crypto  # noqa: PLW0603 - lazy process-wide singleton
    with _shared_crypto_lock:
        if _shared_crypto is None:
            _shared_crypto = MIXCrypto()
        return _shared_crypto


def is_pe_binary(path: Path) -> bool:
    r"""Return whether `path` is a Windows PE executable or DLL.

    Some engine extensions ship as PE DLLs renamed to `.mix`; detecting
    them prevents misinterpreting executable binaries as MIX archives.

    Args:
        path: File path to inspect.

    Returns:
        `True` if `path` has valid `MZ` and `PE\x00\x00` signatures.
    """
    try:
        with path.open("rb") as handle:
            dos = handle.read(_PE_DOS_BYTES_MIN)
            if len(dos) < _PE_DOS_BYTES_MIN or dos[:2] != b"MZ":
                return False
            pe_offset = int(_U32_LE.unpack_from(dos, _PE_LFANEW_OFFSET)[0])
            if pe_offset < _PE_DOS_BYTES_MIN or pe_offset > _PE_OFFSET_BYTES_MAX:
                return False
            handle.seek(pe_offset)
            return handle.read(4) == b"PE\x00\x00"
    except OSError:
        return False


def extract_mvmx_secret_from_dll(dll_path: Path) -> bytes | None:
    """Extract a 32-byte MVMXV1 root secret from a PE32 loader DLL.

    Args:
        dll_path: Candidate loader DLL path (e.g. `MVLoader.dll`).

    Returns:
        32-byte secret if located, otherwise `None`.
    """
    if not dll_path.is_file():
        return None
    try:
        data = dll_path.read_bytes()
    except OSError:
        return None
    parsed = _parse_pe32_sections(data)
    if parsed is None:
        return None
    image_base, sections = parsed
    label_offset = data.find(MVMX_ROOT_LABEL)
    label_va = (
        _pe_offset_to_va(label_offset, image_base, sections)
        if label_offset >= 0
        else None
    )
    if label_va is None:
        return None
    return _scan_pe_text_for_secret(data, label_va, image_base, sections)


def resolve_mvmx_secret(
    search_dirs: Sequence[Path] = (),
    *,
    explicit_hex: str | None = None,
) -> bytes:
    """Resolve the 32-byte MVMXV1 root secret with 3-level fallback.

    Resolution order:
    1. Explicit 64-character hex string (`explicit_hex`).
    2. Dynamic PE32 extraction from `MVLoader.dll` in `search_dirs`.
    3. Built-in default MVMXV1 secret.

    Args:
        search_dirs: Ordered directories searched for `MVLoader.dll`.
        explicit_hex: Optional 64-hex-character secret override.

    Returns:
        32-byte raw MVMXV1 secret.

    Raises:
        ValueError: If `explicit_hex` is not a valid 32-byte hex string.
    """
    if explicit_hex is not None:
        raw = bytes.fromhex(explicit_hex.strip())
        if len(raw) != _MVMX_SECRET_BYTES:
            msg = "mvmx_secret must decode to exactly 32 bytes (64 hex chars)"
            raise ValueError(msg)
        return raw

    for directory in search_dirs:
        extracted = extract_mvmx_secret_from_dll(directory / _MVLOADER_DLL_NAME)
        if extracted is not None:
            return extracted

    return bytes.fromhex(MVMX_SECRET_HEX_DEFAULT)


def derive_mvmx_keys(root_secret: bytes, salt: bytes) -> tuple[bytes, bytes]:
    """Derive `(meta_key, data_key)` for an MVMXV1 archive.

    Args:
        root_secret: 32-byte MVMXV1 root secret.
        salt: 16-byte archive header salt.

    Returns:
        Tuple of `(meta_key, data_key)` 32-byte AES-256 keys.
    """
    root_key = hashlib.sha256(MVMX_ROOT_LABEL + root_secret).digest()
    prk = hmac.new(salt, root_key, hashlib.sha256).digest()
    meta_key = hmac.new(prk, _MVMX_META_INFO, hashlib.sha256).digest()
    data_key = hmac.new(prk, _MVMX_DATA_INFO, hashlib.sha256).digest()
    return meta_key, data_key


def westwood_blowfish_key(key_source: bytes) -> bytes | None:
    """Derive a 56-byte Westwood Blowfish key from an 80-byte RSA block.

    Args:
        key_source: 80-byte RSA-320 encrypted key material.

    Returns:
        56-byte Blowfish key, or `None` if RSA decryption overflows.
    """
    if len(key_source) != WESTWOOD_KEY_SOURCE_BYTES:
        return None
    out = bytearray()
    for offset in (0, _WESTWOOD_RSA_BLOCK_IN_BYTES):
        block_int = int.from_bytes(
            key_source[offset : offset + _WESTWOOD_RSA_BLOCK_IN_BYTES],
            "little",
        )
        decrypted = pow(block_int, _WESTWOOD_EXP_E, _WESTWOOD_MODULUS)
        try:
            out.extend(decrypted.to_bytes(_WESTWOOD_RSA_BLOCK_OUT_BYTES, "little"))
        except OverflowError:
            return None
    return bytes(out[:_WESTWOOD_BLOWFISH_KEY_BYTES])


def fnv1a_32(data: Buffer) -> int:
    """Compute the 32-bit FNV-1a digest used by CryptoRuntime MIXes.

    Args:
        data: Encrypted MIX index buffer.

    Returns:
        Unsigned 32-bit FNV-1a seed value.
    """
    digest = _FNV1A_INIT
    with memoryview(data) as view:
        for byte in view.cast("B"):
            digest = ((digest ^ byte) * _FNV1A_PRIME) & _MASK_32
    return digest


def mt19937_key1024(seed: int) -> bytes:
    """Generate a 1024-byte cyclic XOR key using C++ `std::mt19937`.

    Args:
        seed: Unsigned 32-bit MT19937 seed.

    Returns:
        1024-byte little-endian keystream table.
    """
    state = [0] * _MT_STATE_WORDS
    state[0] = seed & _MASK_32
    for idx in range(1, _MT_STATE_WORDS):
        prev = state[idx - 1]
        state[idx] = (_MT_MULTIPLIER * (prev ^ (prev >> _MT_SHIFT_INIT)) + idx) & (
            _MASK_32
        )
    for idx in range(_MT_STATE_WORDS):
        mixed = (state[idx] & _MT_UPPER_MASK) | (
            state[(idx + 1) % _MT_STATE_WORDS] & _MT_LOWER_MASK
        )
        state[idx] = (
            state[(idx + _MT_PERIOD_OFFSET) % _MT_STATE_WORDS]
            ^ (mixed >> 1)
            ^ (_MT_MATRIX_A if (mixed & 1) else 0)
        )
    out = bytearray(_XOR_KEY_BYTES)
    for idx in range(_MT_OUTPUT_WORDS):
        word = state[idx]
        word ^= word >> _MT_SHIFT_U
        word ^= (word << _MT_SHIFT_S) & _MT_TEMPER_B
        word ^= (word << _MT_SHIFT_T) & _MT_TEMPER_C
        word ^= word >> _MT_SHIFT_L
        _U32_LE.pack_into(out, idx * 4, word & _MASK_32)
    return bytes(out)


def rc4_sub_decrypt(data: Buffer, key: bytes) -> bytes:
    """Decrypt a CryptoRuntime MIX index via RC4 keystream subtraction.

    Args:
        data: Encrypted index buffer.
        key: Base64-encoded RC4 key bytes.

    Returns:
        Decrypted index bytes.
    """
    state = list(range(_RC4_STATE_BYTES))
    j_idx = 0
    key_length = len(key)
    for i_idx in range(_RC4_STATE_BYTES):
        j_idx = (j_idx + state[i_idx] + key[i_idx % key_length]) & _BYTE_MASK
        state[i_idx], state[j_idx] = state[j_idx], state[i_idx]
    with memoryview(data) as view:
        raw_bytes = view.cast("B")
        out = bytearray(len(raw_bytes))
        i_idx = 0
        j_idx = 0
        for pos, byte in enumerate(raw_bytes):
            i_idx = (i_idx + 1) & _BYTE_MASK
            j_idx = (j_idx + state[i_idx]) & _BYTE_MASK
            state[i_idx], state[j_idx] = state[j_idx], state[i_idx]
            ks_byte = state[(state[i_idx] + state[j_idx]) & _BYTE_MASK]
            out[pos] = (byte - ks_byte) & _BYTE_MASK
    return bytes(out)


def xor_key1024(
    data: Buffer,
    key1024: bytes,
    body_rel_offset: int = 0,
) -> bytes:
    """Apply a 1024-byte cyclic XOR keystream from `body_rel_offset`.

    Args:
        data: Ciphertext or plaintext buffer.
        key1024: 1024-byte cyclic XOR table.
        body_rel_offset: Byte offset relative to the MIX body start.

    Returns:
        XOR-transformed bytes of the same length as `data`.
    """
    with memoryview(data) as view:
        byte_view = view.cast("B")
        length = len(byte_view)
        if length == 0:
            return b""
        shift = body_rel_offset & _XOR_KEY_MASK
        rotated = (key1024[shift:] + key1024[:shift]) if shift else key1024
        if length <= _XOR_CHUNK_BYTES:
            repeated = (rotated * ((length // _XOR_KEY_BYTES) + 1))[:length]
            return (
                int.from_bytes(byte_view, "little") ^ int.from_bytes(repeated, "little")
            ).to_bytes(length, "little")

        key_chunk_int = int.from_bytes(
            rotated * (_XOR_CHUNK_BYTES // _XOR_KEY_BYTES),
            "little",
        )
        out = bytearray(length)
        pos = 0
        while pos + _XOR_CHUNK_BYTES <= length:
            chunk_int = int.from_bytes(
                byte_view[pos : pos + _XOR_CHUNK_BYTES],
                "little",
            )
            out[pos : pos + _XOR_CHUNK_BYTES] = (chunk_int ^ key_chunk_int).to_bytes(
                _XOR_CHUNK_BYTES,
                "little",
            )
            pos += _XOR_CHUNK_BYTES
        if pos < length:
            remaining = length - pos
            repeated = (rotated * ((remaining // _XOR_KEY_BYTES) + 1))[:remaining]
            out[pos:] = (
                int.from_bytes(byte_view[pos:], "little")
                ^ int.from_bytes(repeated, "little")
            ).to_bytes(remaining, "little")
        return bytes(out)


# ----------------------------------------------------------------------
# PE32 Helpers
# ----------------------------------------------------------------------


def _parse_pe32_sections(
    data: bytes,
) -> tuple[int, list[tuple[bytes, int, int, int]]] | None:
    if len(data) < _PE_DLL_BYTES_MIN or data[:2] != b"MZ":
        return None
    pe_offset = int(_U32_LE.unpack_from(data, _PE_LFANEW_OFFSET)[0])
    if (
        pe_offset + _PE_OPTIONAL_HEADER_OFFSET + _PE_IMAGE_BASE_OFFSET + 4 > len(data)
        or data[pe_offset : pe_offset + 4] != b"PE\x00\x00"
    ):
        return None

    section_count = int(
        _U16_LE.unpack_from(data, pe_offset + _PE_SECTION_COUNT_OFFSET)[0]
    )
    optional_header_size = int(
        _U16_LE.unpack_from(data, pe_offset + _PE_OPTIONAL_SIZE_OFFSET)[0]
    )
    optional_header_offset = pe_offset + _PE_OPTIONAL_HEADER_OFFSET
    if int(_U16_LE.unpack_from(data, optional_header_offset)[0]) != _PE_MAGIC_PE32:
        return None
    image_base = int(
        _U32_LE.unpack_from(data, optional_header_offset + _PE_IMAGE_BASE_OFFSET)[0]
    )
    section_table_offset = optional_header_offset + optional_header_size
    if section_table_offset + section_count * _PE_SECTION_BYTES > len(data):
        return None

    sections: list[tuple[bytes, int, int, int]] = []
    for idx in range(section_count):
        base = section_table_offset + idx * _PE_SECTION_BYTES
        section_name = data[base : base + 8].rstrip(b"\x00")
        _vsize, rva, raw_size, raw_offset = _U32_4_LE.unpack_from(data, base + 8)
        sections.append((section_name, int(rva), int(raw_size), int(raw_offset)))
    return image_base, sections


def _pe_offset_to_va(
    file_offset: int,
    image_base: int,
    sections: Sequence[tuple[bytes, int, int, int]],
) -> int | None:
    for _, rva, raw_size, raw_offset in sections:
        if raw_offset <= file_offset < raw_offset + raw_size:
            return image_base + rva + (file_offset - raw_offset)
    return None


def _pe_va_to_offset(
    va: int,
    image_base: int,
    sections: Sequence[tuple[bytes, int, int, int]],
) -> int | None:
    for _, rva, raw_size, raw_offset in sections:
        section_base = image_base + rva
        if section_base <= va < section_base + raw_size:
            return raw_offset + (va - section_base)
    return None


def _scan_pe_text_for_secret(
    data: bytes,
    label_va: int,
    image_base: int,
    sections: Sequence[tuple[bytes, int, int, int]],
) -> bytes | None:
    needle = _U32_LE.pack(label_va)
    for section_name, _rva, raw_size, raw_offset in sections:
        if section_name != b".text" or raw_offset + raw_size > len(data):
            continue
        code = data[raw_offset : raw_offset + raw_size]
        pos = 0
        while (hit := code.find(needle, pos)) >= 0:
            window = code[hit + 4 : hit + _PE_SCAN_WINDOW_BYTES]
            opcode_pos = window.find(_PE_PUSH_SECRET_OPCODE)
            if opcode_pos >= 0 and opcode_pos + _PE_OPCODE_BYTES <= len(window):
                secret_va = int(
                    _U32_LE.unpack_from(window, opcode_pos + _PE_OPCODE_VA_OFFSET)[0]
                )
                secret_offset = _pe_va_to_offset(secret_va, image_base, sections)
                if (
                    secret_offset is not None
                    and secret_offset + _MVMX_SECRET_BYTES <= len(data)
                ):
                    return data[secret_offset : secret_offset + _MVMX_SECRET_BYTES]
            pos = hit + 1
    return None


# ----------------------------------------------------------------------
# Pure-Python Blowfish-ECB & AES-256-GCM Fallbacks
# ----------------------------------------------------------------------


class _PureBlowfish:
    """Pure-Python Blowfish-ECB cipher with lazy Machin pi tables."""

    __slots__ = ("p_box", "s_box")
    _CACHE_LOCK: Final = threading.Lock()  # guards: _pi_cache lazy initialisation
    _pi_cache: tuple[tuple[int, ...], tuple[tuple[int, ...], ...]] | None = None

    @classmethod
    def _pi_tables(
        cls,
    ) -> tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]:
        with cls._CACHE_LOCK:
            if cls._pi_cache is not None:
                return cls._pi_cache
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
            cls._pi_cache = (
                tuple(words[:_BF_P_WORDS]),
                tuple(
                    tuple(
                        words[
                            _BF_P_WORDS + box * _BF_S_ENTRIES : _BF_P_WORDS
                            + (box + 1) * _BF_S_ENTRIES
                        ]
                    )
                    for box in range(_BF_S_BOXES)
                ),
            )
            return cls._pi_cache

    def __init__(self, key: bytes) -> None:
        p_init, s_init = self._pi_tables()
        p_box = list(p_init)
        s_box = [list(box) for box in s_init]
        key_length = len(key)
        cursor = 0
        for idx in range(_BF_P_WORDS):
            word = 0
            for _ in range(4):
                word = (word << _SHIFT_8) | key[cursor]
                cursor = (cursor + 1) % key_length
            p_box[idx] ^= word
        self.p_box = p_box
        self.s_box = s_box

        left = 0
        right = 0
        for idx in range(0, _BF_P_WORDS, 2):
            left, right = self.encrypt_pair(left, right)
            p_box[idx], p_box[idx + 1] = left, right
        for box in s_box:
            for idx in range(0, _BF_S_ENTRIES, 2):
                left, right = self.encrypt_pair(left, right)
                box[idx], box[idx + 1] = left, right

    def encrypt_pair(self, left: int, right: int) -> tuple[int, int]:
        p_box = self.p_box
        for idx in range(_BF_ROUNDS):
            left ^= p_box[idx]
            right ^= self._feistel(left)
            left, right = right, left
        return (
            (right ^ p_box[_BF_ROUNDS + 1]) & _MASK_32,
            (left ^ p_box[_BF_ROUNDS]) & _MASK_32,
        )

    def decrypt_ecb(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        offset = 0
        for left, right in _U32_2_BE.iter_unpack(data):
            dec_left, dec_right = self._decrypt_pair(left, right)
            _U32_2_BE.pack_into(out, offset, dec_left, dec_right)
            offset += _BF_BLOCK_BYTES
        return bytes(out)

    def _feistel(self, val: int) -> int:
        s0, s1, s2, s3 = self.s_box
        part = (s0[val >> _SHIFT_24] + s1[(val >> _SHIFT_16) & _BYTE_MASK]) & _MASK_32
        return (
            (part ^ s2[(val >> _SHIFT_8) & _BYTE_MASK]) + s3[val & _BYTE_MASK]
        ) & _MASK_32

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


def _aes_xtime(val: int) -> int:
    return (
        ((val << 1) ^ _AES_GF_POLY) & _BYTE_MASK
        if val & 0x80
        else (val << 1) & _BYTE_MASK
    )


def _aes_gf_mul(lhs: int, rhs: int) -> int:
    acc = 0
    for _ in range(8):
        if rhs & 1:
            acc ^= lhs
        lhs = _aes_xtime(lhs)
        rhs >>= 1
    return acc


def _aes_gf_inv(val: int) -> int:
    if val == 0:
        return 0
    base_v = val
    exp = _AES_SBOX_EXP
    acc = 1
    while exp:
        if exp & 1:
            acc = _aes_gf_mul(acc, base_v)
        base_v = _aes_gf_mul(base_v, base_v)
        exp >>= 1
    return acc


def _build_aes_tables() -> _AESTables:
    sbox = bytearray(_RC4_STATE_BYTES)
    for val in range(_RC4_STATE_BYTES):
        inv = _aes_gf_inv(val)
        s_val = inv
        for shift in (1, 2, 3, 4):
            s_val ^= ((inv << shift) | (inv >> (8 - shift))) & _BYTE_MASK
        sbox[val] = s_val ^ _AES_SBOX_CONST

    t0 = [0] * _RC4_STATE_BYTES
    t1 = [0] * _RC4_STATE_BYTES
    t2 = [0] * _RC4_STATE_BYTES
    t3 = [0] * _RC4_STATE_BYTES
    for idx in range(_RC4_STATE_BYTES):
        s_val = sbox[idx]
        s2 = _aes_xtime(s_val)
        word = (
            (s2 << _SHIFT_24)
            | (s_val << _SHIFT_16)
            | (s_val << _SHIFT_8)
            | (s2 ^ s_val)
        )
        t0[idx] = word
        t1[idx] = ((word >> _SHIFT_8) | (word << _SHIFT_24)) & _MASK_32
        t2[idx] = ((word >> _SHIFT_16) | (word << _SHIFT_16)) & _MASK_32
        t3[idx] = ((word >> _SHIFT_24) | (word << _SHIFT_8)) & _MASK_32
    return (bytes(sbox), tuple(t0), tuple(t1), tuple(t2), tuple(t3))


class _PureAES256GCM:
    """Pure-Python AES-256-GCM fallback with Shoup 4-bit GHASH."""

    __slots__ = ("_m_table", "rk", "sbox", "t0", "t1", "t2", "t3")
    _m_table: tuple[int, ...]
    rk: tuple[int, ...]
    sbox: bytes
    t0: tuple[int, ...]
    t1: tuple[int, ...]
    t2: tuple[int, ...]
    t3: tuple[int, ...]
    _CACHE_LOCK: Final = threading.Lock()  # guards: _tables lazy initialisation
    _tables: _AESTables | None = None

    @classmethod
    def _init_tables(cls) -> _AESTables:
        with cls._CACHE_LOCK:
            if cls._tables is None:
                cls._tables = _build_aes_tables()
            return cls._tables

    def __init__(self, key: bytes) -> None:
        if len(key) != _AES_KEY_BYTES:
            msg = "AES-256 requires a 32-byte key"
            raise ValueError(msg)
        sbox, t0, t1, t2, t3 = self._init_tables()
        self.sbox = sbox
        self.t0 = t0
        self.t1 = t1
        self.t2 = t2
        self.t3 = t3
        round_keys: list[int] = [int(word) for word in _U32_8_BE.unpack(key)]
        rcon = 1
        for idx in range(_AES_ROUND_KEY_STRIDE, _AES_ROUND_KEY_WORDS):
            temp = round_keys[idx - 1]
            if idx % _AES_ROUND_KEY_STRIDE == 0:
                temp = (
                    (sbox[(temp >> _SHIFT_16) & _BYTE_MASK] << _SHIFT_24)
                    | (sbox[(temp >> _SHIFT_8) & _BYTE_MASK] << _SHIFT_16)
                    | (sbox[temp & _BYTE_MASK] << _SHIFT_8)
                    | sbox[(temp >> _SHIFT_24) & _BYTE_MASK]
                ) ^ (rcon << _SHIFT_24)
                rcon = (
                    ((rcon << 1) ^ _AES_GF_POLY) & _BYTE_MASK
                    if rcon & 0x80
                    else (rcon << 1)
                )
            elif idx % _AES_ROUND_KEY_STRIDE == _AES_ROUND_KEY_MID:
                temp = (
                    (sbox[(temp >> _SHIFT_24) & _BYTE_MASK] << _SHIFT_24)
                    | (sbox[(temp >> _SHIFT_16) & _BYTE_MASK] << _SHIFT_16)
                    | (sbox[(temp >> _SHIFT_8) & _BYTE_MASK] << _SHIFT_8)
                    | sbox[temp & _BYTE_MASK]
                )
            round_keys.append(round_keys[idx - _AES_ROUND_KEY_STRIDE] ^ temp)
        self.rk = tuple(round_keys)
        h_val = int.from_bytes(
            _U32_4_BE.pack(*self._encrypt_block_words(0, 0, 0, 0)),
            "big",
        )
        self._m_table = self._build_ghash_table(h_val)

    def decrypt(
        self,
        nonce: bytes,
        aad: bytes,
        ciphertext_and_tag: Buffer,
    ) -> bytes:
        if len(nonce) != _AES_GCM_NONCE_BYTES:
            msg = "AES-GCM requires a 12-byte nonce"
            raise ValueError(msg)
        with memoryview(ciphertext_and_tag) as raw_view:
            byte_view = raw_view.cast("B")
            if len(byte_view) < _AES_GCM_TAG_BYTES:
                msg = "AES-GCM ciphertext shorter than 16-byte tag"
                raise ValueError(msg)
            ct_length = len(byte_view) - _AES_GCM_TAG_BYTES
            with byte_view[:ct_length] as ciphertext:
                tag = bytes(byte_view[ct_length:])
                j0_0, j0_1, j0_2 = _U32_3_BE.unpack(nonce)
                mask = _U32_4_BE.pack(*self._encrypt_block_words(j0_0, j0_1, j0_2, 1))
                calc_tag = bytes(
                    lhs ^ rhs
                    for lhs, rhs in zip(
                        self._ghash(aad, ciphertext),
                        mask,
                        strict=True,
                    )
                )
                if not hmac.compare_digest(calc_tag, tag):
                    msg = "AES-GCM authentication tag mismatch"
                    raise ValueError(msg)
                return self._ctr_crypt(j0_0, j0_1, j0_2, ciphertext)

    def encrypt(self, nonce: bytes, aad: bytes, plaintext: bytes) -> bytes:
        if len(nonce) != _AES_GCM_NONCE_BYTES:
            msg = "AES-GCM requires a 12-byte nonce"
            raise ValueError(msg)
        j0_0, j0_1, j0_2 = _U32_3_BE.unpack(nonce)
        with memoryview(plaintext) as pt_view:
            ciphertext = self._ctr_crypt(j0_0, j0_1, j0_2, pt_view)
        mask = _U32_4_BE.pack(*self._encrypt_block_words(j0_0, j0_1, j0_2, 1))
        with memoryview(ciphertext) as ct_view:
            tag = bytes(
                lhs ^ rhs
                for lhs, rhs in zip(self._ghash(aad, ct_view), mask, strict=True)
            )
        return ciphertext + tag

    def _encrypt_block_words(
        self,
        s0: int,
        s1: int,
        s2: int,
        s3: int,
    ) -> tuple[int, int, int, int]:
        rk: tuple[int, ...] = self.rk
        t0: tuple[int, ...] = self.t0
        t1: tuple[int, ...] = self.t1
        t2: tuple[int, ...] = self.t2
        t3: tuple[int, ...] = self.t3
        sbox: bytes = self.sbox
        s0 ^= rk[0]
        s1 ^= rk[1]
        s2 ^= rk[2]
        s3 ^= rk[3]
        for rnd in range(4, 56, 4):
            n0: int = (
                t0[s0 >> _SHIFT_24]
                ^ t1[(s1 >> _SHIFT_16) & _BYTE_MASK]
                ^ t2[(s2 >> _SHIFT_8) & _BYTE_MASK]
                ^ t3[s3 & _BYTE_MASK]
                ^ rk[rnd]
            )
            n1: int = (
                t0[s1 >> _SHIFT_24]
                ^ t1[(s2 >> _SHIFT_16) & _BYTE_MASK]
                ^ t2[(s3 >> _SHIFT_8) & _BYTE_MASK]
                ^ t3[s0 & _BYTE_MASK]
                ^ rk[rnd + 1]
            )
            n2: int = (
                t0[s2 >> _SHIFT_24]
                ^ t1[(s3 >> _SHIFT_16) & _BYTE_MASK]
                ^ t2[(s0 >> _SHIFT_8) & _BYTE_MASK]
                ^ t3[s1 & _BYTE_MASK]
                ^ rk[rnd + 2]
            )
            n3: int = (
                t0[s3 >> _SHIFT_24]
                ^ t1[(s0 >> _SHIFT_16) & _BYTE_MASK]
                ^ t2[(s1 >> _SHIFT_8) & _BYTE_MASK]
                ^ t3[s2 & _BYTE_MASK]
                ^ rk[rnd + 3]
            )
            s0, s1, s2, s3 = n0, n1, n2, n3
        return (
            (
                (sbox[s0 >> _SHIFT_24] << _SHIFT_24)
                | (sbox[(s1 >> _SHIFT_16) & _BYTE_MASK] << _SHIFT_16)
                | (sbox[(s2 >> _SHIFT_8) & _BYTE_MASK] << _SHIFT_8)
                | sbox[s3 & _BYTE_MASK]
            )
            ^ rk[56],
            (
                (sbox[s1 >> _SHIFT_24] << _SHIFT_24)
                | (sbox[(s2 >> _SHIFT_16) & _BYTE_MASK] << _SHIFT_16)
                | (sbox[(s3 >> _SHIFT_8) & _BYTE_MASK] << _SHIFT_8)
                | sbox[s0 & _BYTE_MASK]
            )
            ^ rk[57],
            (
                (sbox[s2 >> _SHIFT_24] << _SHIFT_24)
                | (sbox[(s3 >> _SHIFT_16) & _BYTE_MASK] << _SHIFT_16)
                | (sbox[(s0 >> _SHIFT_8) & _BYTE_MASK] << _SHIFT_8)
                | sbox[s1 & _BYTE_MASK]
            )
            ^ rk[58],
            (
                (sbox[s3 >> _SHIFT_24] << _SHIFT_24)
                | (sbox[(s0 >> _SHIFT_16) & _BYTE_MASK] << _SHIFT_16)
                | (sbox[(s1 >> _SHIFT_8) & _BYTE_MASK] << _SHIFT_8)
                | sbox[s2 & _BYTE_MASK]
            )
            ^ rk[59],
        )

    @staticmethod
    def _build_ghash_table(h_val: int) -> tuple[int, ...]:
        table = [0] * _AES_GHASH_TABLE_ENTRIES
        table[8] = h_val
        for bit in (4, 2, 1):
            val = table[bit << 1]
            table[bit] = (val >> 1) ^ (_AES_GHASH_R if val & 1 else 0)
        for idx in range(2, _AES_GHASH_TABLE_ENTRIES):
            if table[idx] == 0:
                low_bit = idx & -idx
                table[idx] = table[low_bit] ^ table[idx ^ low_bit]
        return tuple(table)

    def _ghash_mul(self, x_val: int) -> int:
        table: tuple[int, ...] = self._m_table
        r4: tuple[int, ...] = _AES_GHASH_R4
        acc: int = 0
        for shift in range(0, _AES_GHASH_BITS, _AES_GHASH_NIBBLE_BITS):
            low_nibble: int = acc & _AES_GHASH_NIBBLE_MASK
            r4_word: int = r4[low_nibble]
            table_word: int = table[(x_val >> shift) & _AES_GHASH_NIBBLE_MASK]
            acc = (
                (acc >> _AES_GHASH_NIBBLE_BITS) ^ (r4_word << _AES_GHASH_R4_SHIFT)
            ) ^ table_word
        return acc

    def _ghash(self, aad: bytes, ciphertext: memoryview) -> bytes:
        acc = 0
        with memoryview(aad) as aad_view:
            for data in (aad_view, ciphertext):
                length = len(data)
                full = length & ~(_AES_BLOCK_BYTES - 1)
                for offset in range(0, full, _AES_BLOCK_BYTES):
                    acc = self._ghash_mul(
                        acc
                        ^ int.from_bytes(
                            data[offset : offset + _AES_BLOCK_BYTES],
                            "big",
                        )
                    )
                if full < length:
                    padded = bytes(data[full:]) + b"\x00" * (
                        _AES_BLOCK_BYTES - (length - full)
                    )
                    acc = self._ghash_mul(acc ^ int.from_bytes(padded, "big"))
        lengths_block = ((len(aad) * 8) << 64) | (len(ciphertext) * 8)
        acc = self._ghash_mul(acc ^ lengths_block)
        return acc.to_bytes(_AES_BLOCK_BYTES, "big")

    def _ctr_crypt(
        self,
        j0_0: int,
        j0_1: int,
        j0_2: int,
        data: memoryview,
    ) -> bytes:
        length = len(data)
        out = bytearray(length)
        ctr = 2
        full = length & ~(_AES_BLOCK_BYTES - 1)
        for offset in range(0, full, _AES_BLOCK_BYTES):
            k0, k1, k2, k3 = self._encrypt_block_words(j0_0, j0_1, j0_2, ctr)
            c0, c1, c2, c3 = _U32_4_BE.unpack_from(data, offset)
            _U32_4_BE.pack_into(out, offset, c0 ^ k0, c1 ^ k1, c2 ^ k2, c3 ^ k3)
            ctr = (ctr + 1) & _MASK_32
        if full < length:
            keystream = _U32_4_BE.pack(
                *self._encrypt_block_words(j0_0, j0_1, j0_2, ctr)
            )
            for idx in range(length - full):
                out[full + idx] = data[full + idx] ^ keystream[idx]
        return bytes(out)


# ----------------------------------------------------------------------
# OpenSSL `libcrypto` ctypes Acceleration Bridge
# ----------------------------------------------------------------------


def _load_libcrypto() -> ctypes.CDLL | None:
    void_ptr = ctypes.c_void_p
    c_int = ctypes.c_int
    c_int_ptr = ctypes.POINTER(ctypes.c_int)
    signatures: tuple[tuple[str, tuple[object, ...], object], ...] = (
        ("EVP_CIPHER_CTX_new", (), void_ptr),
        ("EVP_CIPHER_CTX_free", (void_ptr,), None),
        ("EVP_CIPHER_CTX_reset", (void_ptr,), c_int),
        ("EVP_aes_256_gcm", (), void_ptr),
        (
            "EVP_DecryptInit_ex",
            (void_ptr, void_ptr, void_ptr, void_ptr, void_ptr),
            c_int,
        ),
        ("EVP_CIPHER_CTX_ctrl", (void_ptr, c_int, c_int, void_ptr), c_int),
        ("EVP_DecryptUpdate", (void_ptr, void_ptr, c_int_ptr, void_ptr, c_int), c_int),
        ("EVP_DecryptFinal_ex", (void_ptr, void_ptr, c_int_ptr), c_int),
        ("EVP_CIPHER_CTX_set_key_length", (void_ptr, c_int), c_int),
        ("EVP_CIPHER_CTX_set_padding", (void_ptr, c_int), c_int),
    )
    found = ctypes.util.find_library("crypto")
    candidates = (
        (found, *_LIBCRYPTO_CANDIDATES)
        if found is not None and found != ""
        else _LIBCRYPTO_CANDIDATES
    )
    for name in candidates:
        try:
            loaded = ctypes.CDLL(name)
            for fn_name, argtypes, restype in signatures:
                func = getattr(loaded, fn_name)
                func.argtypes = list(argtypes)
                func.restype = restype
        except OSError, AttributeError:
            continue
        return loaded
    return None


@contextmanager
def _evp_cipher_ctx(lib: ctypes.CDLL) -> Generator[int]:
    ctx = lib.EVP_CIPHER_CTX_new()
    if not ctx:
        msg = "EVP_CIPHER_CTX_new failed"
        raise RuntimeError(msg)
    try:
        yield int(ctx)
    finally:
        lib.EVP_CIPHER_CTX_free(ctx)


class _OpenSSLBridge:
    """Thread-safe `libcrypto` bridge for AES-256-GCM and Blowfish."""

    def __init__(self) -> None:
        self.lib: ctypes.CDLL | None = None
        self.available_aes_gcm = False
        self.available_bf_ecb = False
        self._aes_gcm_cipher: int = 0
        self._bf_ecb_cipher: int = 0
        self._tls = threading.local()
        self._lock = threading.Lock()  # guards: _ctxs lifecycle list and _closed flag
        self._ctxs: list[int] = []
        self._providers: list[int] = []
        self._closed = False
        self._init_lib()
        atexit.register(self.close)

    def close(self) -> None:
        with self._lock:
            if self._closed or self.lib is None:
                self._closed = True
                return
            for ctx in self._ctxs:
                self.lib.EVP_CIPHER_CTX_free(ctx)
            self._ctxs.clear()
            self._closed = True

    def aes_gcm_decrypt(
        self,
        key: bytes,
        nonce: bytes,
        aad: bytes,
        ciphertext_and_tag: Buffer,
    ) -> bytes:
        if self.lib is None:
            msg = "OpenSSL libcrypto is unavailable"
            raise RuntimeError(msg)
        raw = bytes(ciphertext_and_tag)
        if len(raw) < _AES_GCM_TAG_BYTES:
            msg = "AES-GCM ciphertext shorter than 16-byte tag"
            raise ValueError(msg)

        ct_length = len(raw) - _AES_GCM_TAG_BYTES
        tag_bytes = raw[ct_length:]
        out_buf = bytearray(ct_length)

        lib = self.lib
        ctx = self._get_gcm_ctx()
        if (
            lib.EVP_DecryptInit_ex(ctx, self._aes_gcm_cipher, None, None, None) != 1
            or lib.EVP_CIPHER_CTX_ctrl(ctx, _EVP_CTRL_GCM_SET_IVLEN, len(nonce), None)
            != 1
            or lib.EVP_DecryptInit_ex(
                ctx,
                None,
                None,
                ctypes.c_char_p(key),
                ctypes.c_char_p(nonce),
            )
            != 1
        ):
            msg = "OpenSSL AES-GCM initialization failed"
            raise ValueError(msg)

        outlen = ctypes.c_int(0)
        if (
            aad
            and lib.EVP_DecryptUpdate(
                ctx,
                None,
                ctypes.byref(outlen),
                ctypes.c_char_p(aad),
                len(aad),
            )
            != 1
        ):
            msg = "OpenSSL AES-GCM AAD processing failed"
            raise ValueError(msg)

        out_arr = (ctypes.c_ubyte * ct_length).from_buffer(out_buf)
        if ct_length > 0:
            if (
                lib.EVP_DecryptUpdate(
                    ctx,
                    out_arr,
                    ctypes.byref(outlen),
                    ctypes.c_char_p(raw),
                    ct_length,
                )
                != 1
            ):
                msg = "OpenSSL AES-GCM decrypt update failed"
                raise ValueError(msg)
        else:
            outlen.value = 0

        if (
            lib.EVP_CIPHER_CTX_ctrl(
                ctx,
                _EVP_CTRL_GCM_SET_TAG,
                _AES_GCM_TAG_BYTES,
                ctypes.c_char_p(tag_bytes),
            )
            != 1
        ):
            msg = "OpenSSL AES-GCM set tag failed"
            raise ValueError(msg)

        finlen = ctypes.c_int(0)
        tail_ptr = ctypes.byref(out_arr, outlen.value) if ct_length > 0 else None
        if lib.EVP_DecryptFinal_ex(ctx, tail_ptr, ctypes.byref(finlen)) != 1:
            msg = "AES-GCM authentication tag mismatch"
            raise ValueError(msg)
        return bytes(out_buf)

    def blowfish_ecb_decrypt(self, key: bytes, data: bytes) -> bytes:
        if self.lib is None:
            msg = "OpenSSL libcrypto is unavailable"
            raise RuntimeError(msg)
        if len(data) & (_BF_BLOCK_BYTES - 1):
            msg = "Blowfish-ECB input length must be a multiple of 8 bytes"
            raise ValueError(msg)
        lib = self.lib
        with _evp_cipher_ctx(lib) as ctx:
            if (
                lib.EVP_DecryptInit_ex(ctx, self._bf_ecb_cipher, None, None, None) != 1
                or lib.EVP_CIPHER_CTX_set_key_length(ctx, len(key)) != 1
                or lib.EVP_CIPHER_CTX_set_padding(ctx, 0) != 1
                or lib.EVP_DecryptInit_ex(
                    ctx,
                    None,
                    None,
                    ctypes.c_char_p(key),
                    None,
                )
                != 1
            ):
                msg = "OpenSSL Blowfish-ECB initialization failed"
                raise ValueError(msg)
            out = bytearray(len(data))
            out_arr = (ctypes.c_ubyte * len(data)).from_buffer(out)
            outlen = ctypes.c_int(0)
            if (
                lib.EVP_DecryptUpdate(
                    ctx,
                    out_arr,
                    ctypes.byref(outlen),
                    ctypes.c_char_p(data),
                    len(data),
                )
                != 1
            ):
                msg = "OpenSSL Blowfish-ECB decrypt failed"
                raise ValueError(msg)
            return bytes(out[: outlen.value])

    def _init_lib(self) -> None:
        lib = _load_libcrypto()
        if lib is None:
            return
        self._load_providers(lib)
        self.lib = lib
        aes_cipher = lib.EVP_aes_256_gcm()
        if aes_cipher:
            self._aes_gcm_cipher = int(aes_cipher)
            self.available_aes_gcm = True
        self._probe_blowfish(lib)

    def _load_providers(self, lib: ctypes.CDLL) -> None:
        if not hasattr(lib, "OSSL_PROVIDER_load"):
            return
        load_prov = lib.OSSL_PROVIDER_load
        load_prov.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        load_prov.restype = ctypes.c_void_p
        for prov_name in (b"default", b"legacy"):
            prov = load_prov(None, prov_name)
            if prov:
                self._providers.append(int(prov))

    def _probe_blowfish(self, lib: ctypes.CDLL) -> None:
        if not hasattr(lib, "EVP_bf_ecb"):
            return
        lib.EVP_bf_ecb.restype = ctypes.c_void_p
        bf_cipher = lib.EVP_bf_ecb()
        if not bf_cipher:
            return
        with _evp_cipher_ctx(lib) as ctx:
            if lib.EVP_DecryptInit_ex(ctx, bf_cipher, None, None, None) == 1:
                self._bf_ecb_cipher = int(bf_cipher)
                self.available_bf_ecb = True

    def _get_gcm_ctx(self) -> int:
        if self.lib is None:
            msg = "OpenSSL libcrypto is unavailable"
            raise RuntimeError(msg)
        raw_existing: object = getattr(self._tls, "gcm_ctx", None)
        if isinstance(raw_existing, int):
            self.lib.EVP_CIPHER_CTX_reset(raw_existing)
            return raw_existing
        raw_ctx = self.lib.EVP_CIPHER_CTX_new()
        if not raw_ctx:
            msg = "EVP_CIPHER_CTX_new failed"
            raise RuntimeError(msg)
        ctx = int(raw_ctx)
        self._tls.gcm_ctx = ctx
        with self._lock:
            self._ctxs.append(ctx)
        return ctx
