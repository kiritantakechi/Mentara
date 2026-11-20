"""Westwood CSF string tables (version 3): label to UTF-16 text."""

import struct
from typing import Final
lazy from collections.abc import Mapping

from mentara.errors import AssetError

__all__ = [
    "CSF_LANGUAGE_US",
    "decode_csf",
    "encode_csf",
]

CSF_LANGUAGE_US: Final[int] = 0
_FORMAT: Final[str] = "CSF"
_MAGIC: Final[bytes] = b" FSC"
_LABEL_TAG: Final[bytes] = b" LBL"
_STRING_TAG: Final[bytes] = b" RTS"
_WIDE_STRING_TAG: Final[bytes] = b"WRTS"
_VERSION: Final[int] = 3
_HEADER: Final[struct.Struct] = struct.Struct("<4s5I")
_LABEL: Final[struct.Struct] = struct.Struct("<4sII")
_STRING: Final[struct.Struct] = struct.Struct("<4sI")
_U32: Final[struct.Struct] = struct.Struct("<I")


def encode_csf(
    strings: Mapping[str, str],
    *,
    language: int = CSF_LANGUAGE_US,
) -> bytes:
    """Encode labels and their text as a version 3 CSF table.

    Args:
        strings: ASCII label to text, in file order.
        language: CSF language id.

    Returns:
        CSF file bytes.

    Raises:
        AssetError: If a label is not ASCII.
    """
    count = len(strings)
    parts = [_HEADER.pack(_MAGIC, _VERSION, count, count, 0, language)]
    for label, text in strings.items():
        if not label.isascii():
            detail = f"label {label!r} is not ASCII"
            raise AssetError.invalid_format(_FORMAT, detail)
        name = label.encode("ascii")
        value = _invert(text.encode("utf-16-le"))
        parts.append(_LABEL.pack(_LABEL_TAG, 1, len(name)) + name)
        parts.append(_STRING.pack(_STRING_TAG, len(value) // 2) + value)
    return b"".join(parts)


def decode_csf(data: bytes) -> dict[str, str]:
    """Decode a CSF table, keeping the first string of each label.

    Args:
        data: CSF file bytes.

    Returns:
        Label to text, in file order.

    Raises:
        AssetError: If the data is not a CSF table.
    """
    try:
        return _decode_labels(data)
    except (struct.error, UnicodeDecodeError) as exc:
        detail = f"truncated or corrupt table: {exc}"
        raise AssetError.invalid_format(_FORMAT, detail) from exc


def _decode_labels(data: bytes) -> dict[str, str]:
    magic, _, label_count, _, _, _ = _HEADER.unpack_from(data, 0)
    if magic != _MAGIC:
        detail = "missing ' FSC' signature"
        raise AssetError.invalid_format(_FORMAT, detail)
    offset = _HEADER.size
    strings: dict[str, str] = {}
    for _ in range(label_count):
        tag, count, name_length = _LABEL.unpack_from(data, offset)
        if tag != _LABEL_TAG:
            detail = f"expected a label at byte {offset}"
            raise AssetError.invalid_format(_FORMAT, detail)
        offset += _LABEL.size
        label = data[offset : offset + name_length].decode("ascii")
        offset += name_length
        for index in range(count):
            kind, length = _STRING.unpack_from(data, offset)
            offset += _STRING.size
            text = _invert(data[offset : offset + 2 * length]).decode("utf-16-le")
            offset += 2 * length
            if kind == _WIDE_STRING_TAG:
                (extra,) = _U32.unpack_from(data, offset)
                offset += _U32.size + extra
            if index == 0:
                strings[label] = text
    return strings


def _invert(data: bytes) -> bytes:
    # CSF stores every byte of the UTF-16 text bitwise inverted.
    return bytes(~byte & 0xFF for byte in data)
