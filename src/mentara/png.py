"""8-bit indexed PNG images, the editable source of palette artwork.

Only colour type 3 at 8 bits per pixel without interlacing is supported:
that is what pixel editors export for palette art, and it maps one byte
to one palette index, exactly like the game's SHP frames.
"""

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from mentara.errors import AssetError
from mentara.palette import Rgb

__all__ = [
    "IndexedImage",
    "decode_indexed_png",
    "encode_indexed_png",
]

_FORMAT: Final[str] = "PNG"
_SIGNATURE: Final[bytes] = b"\x89PNG\r\n\x1a\n"
_CHUNK_HEADER: Final[struct.Struct] = struct.Struct(">I4s")
_CRC: Final[struct.Struct] = struct.Struct(">I")
_IHDR: Final[struct.Struct] = struct.Struct(">IIBBBBB")
_BIT_DEPTH: Final[int] = 8
_COLOUR_TYPE_INDEXED: Final[int] = 3
_REQUIRED_CHUNKS: Final[tuple[bytes, ...]] = (b"IHDR", b"PLTE", b"IDAT")
_ZLIB_LEVEL: Final[int] = 9


class _Filter(IntEnum):
    NONE = 0
    SUB = 1
    UP = 2
    AVERAGE = 3
    PAETH = 4


@dataclass(frozen=True, slots=True)
class IndexedImage:
    """An image of palette indices, one byte per pixel, row by row."""

    width: int
    height: int
    pixels: bytes
    palette: tuple[Rgb, ...]

    def __post_init__(self) -> None:
        """Reject pixel buffers that do not match the dimensions.

        Raises:
            AssetError: If the size is not positive or does not match.
        """
        if self.width <= 0 or self.height <= 0:
            detail = f"image size must be positive, got {self.width}x{self.height}"
            raise AssetError.invalid_format(_FORMAT, detail)
        if len(self.pixels) != self.width * self.height:
            detail = f"{len(self.pixels)} pixels for {self.width}x{self.height}"
            raise AssetError.invalid_format(_FORMAT, detail)

    def crop(self, left: int, top: int, width: int, height: int) -> bytes:
        """Return the indices of a rectangle, row by row.

        Args:
            left: Left edge in pixels.
            top: Top edge in pixels.
            width: Rectangle width.
            height: Rectangle height.

        Returns:
            `width * height` palette indices.

        Raises:
            AssetError: If the rectangle leaves the image.
        """
        inside = 0 <= left <= self.width - width and 0 <= top <= self.height - height
        if not inside:
            detail = f"{width}x{height}+{left}+{top} leaves {self.width}x{self.height}"
            raise AssetError.invalid_format(_FORMAT, detail)
        starts = ((top + row) * self.width + left for row in range(height))
        return b"".join(self.pixels[start : start + width] for start in starts)


def encode_indexed_png(image: IndexedImage) -> bytes:
    """Encode an indexed image as a PNG with its palette.

    Args:
        image: Image to encode.

    Returns:
        PNG file bytes, every row unfiltered.
    """
    rows = b"".join(
        bytes((_Filter.NONE,)) + image.pixels[start : start + image.width]
        for start in range(0, len(image.pixels), image.width)
    )
    header = _IHDR.pack(
        image.width, image.height, _BIT_DEPTH, _COLOUR_TYPE_INDEXED, 0, 0, 0
    )
    palette = b"".join(bytes((c.red, c.green, c.blue)) for c in image.palette)
    return (
        _SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"PLTE", palette)
        + _chunk(b"IDAT", zlib.compress(rows, _ZLIB_LEVEL))
        + _chunk(b"IEND", b"")
    )


def decode_indexed_png(data: bytes) -> IndexedImage:
    """Decode an 8-bit indexed, non-interlaced PNG.

    Args:
        data: PNG file bytes.

    Returns:
        The image's palette indices and palette.

    Raises:
        AssetError: If the file is not a supported indexed PNG.
    """
    if not data.startswith(_SIGNATURE):
        detail = "missing PNG signature"
        raise AssetError.invalid_format(_FORMAT, detail)
    chunks = _read_chunks(data)
    if any(kind not in chunks for kind in _REQUIRED_CHUNKS):
        detail = "an indexed PNG needs IHDR, PLTE and IDAT chunks"
        raise AssetError.invalid_format(_FORMAT, detail)
    width, height, depth, colour_type, _, _, interlace = _IHDR.unpack(chunks[b"IHDR"])
    if (depth, colour_type, interlace) != (_BIT_DEPTH, _COLOUR_TYPE_INDEXED, 0):
        detail = (
            f"need 8-bit indexed non-interlaced, got depth {depth}, "
            f"colour type {colour_type}, interlace {interlace}"
        )
        raise AssetError.invalid_format(_FORMAT, detail)
    plte = chunks[b"PLTE"]
    palette = tuple(Rgb(*plte[i : i + 3]) for i in range(0, len(plte) - 2, 3))
    try:
        raw = zlib.decompress(chunks[b"IDAT"])
    except zlib.error as exc:
        detail = f"bad image data: {exc}"
        raise AssetError.invalid_format(_FORMAT, detail) from exc
    return IndexedImage(width, height, _unfilter(raw, width, height), palette)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = _CRC.pack(zlib.crc32(kind + payload))
    return _CHUNK_HEADER.pack(len(payload), kind) + payload + crc


def _read_chunks(data: bytes) -> dict[bytes, bytes]:
    chunks: dict[bytes, bytes] = {}
    offset = len(_SIGNATURE)
    while offset + _CHUNK_HEADER.size + _CRC.size <= len(data):
        length, kind = _CHUNK_HEADER.unpack_from(data, offset)
        start = offset + _CHUNK_HEADER.size
        payload = data[start : start + length]
        if start + length + _CRC.size > len(data):
            detail = f"truncated {kind!r} chunk"
            raise AssetError.invalid_format(_FORMAT, detail)
        (crc,) = _CRC.unpack_from(data, start + length)
        if zlib.crc32(kind + payload) != crc:
            detail = f"bad CRC in {kind!r} chunk"
            raise AssetError.invalid_format(_FORMAT, detail)
        # IDAT may span several chunks; every other chunk appears once.
        chunks[kind] = chunks.get(kind, b"") + payload
        offset = start + length + _CRC.size
        if kind == b"IEND":
            break
    return chunks


def _unfilter(raw: bytes, width: int, height: int) -> bytes:
    if len(raw) != (width + 1) * height:
        detail = f"{len(raw)} bytes of image data for {width}x{height}"
        raise AssetError.invalid_format(_FORMAT, detail)
    pixels = bytearray()
    previous = bytes(width)
    for start in range(0, len(raw), width + 1):
        kind = raw[start]
        line = bytearray(raw[start + 1 : start + 1 + width])
        for x in range(width):
            line[x] = (line[x] + _predict(kind, line, previous, x)) & 0xFF
        pixels.extend(line)
        previous = bytes(line)
    return bytes(pixels)


def _predict(kind: int, line: bytearray, previous: bytes, x: int) -> int:
    left = line[x - 1] if x else 0
    up = previous[x]
    upper_left = previous[x - 1] if x else 0
    match kind:
        case _Filter.NONE:
            return 0
        case _Filter.SUB:
            return left
        case _Filter.UP:
            return up
        case _Filter.AVERAGE:
            return (left + up) // 2
        case _Filter.PAETH:
            return _paeth(left, up, upper_left)
        case _:
            detail = f"unknown filter type {kind}"
            raise AssetError.invalid_format(_FORMAT, detail)


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    near_left = abs(estimate - left)
    near_up = abs(estimate - up)
    near_upper_left = abs(estimate - upper_left)
    if near_left <= near_up and near_left <= near_upper_left:
        return left
    return up if near_up <= near_upper_left else upper_left
