"""TS/RA2 SHP shapes: frames of palette indices on a shared canvas.

Frames are written as full-canvas RLE-zero scanlines (compression 3),
the encoding MO's own art uses and the one Phobos requires for shapes
it draws translucently.
"""

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from mentara.errors import AssetError

__all__ = [
    "ShpImage",
    "decode_shp",
    "encode_shp",
]

_FORMAT: Final[str] = "SHP"
_HEADER: Final[struct.Struct] = struct.Struct("<4H")
# x, y, width, height, compression, pad, RGBA radar colour, 0, offset
_FRAME: Final[struct.Struct] = struct.Struct("<4HB3x4BII")
_ROW_LENGTH: Final[struct.Struct] = struct.Struct("<H")
_RUN_MAX: Final[int] = 255


class _Compression(IntEnum):
    # Bit 1 prefixes each row with its byte length; both bits together
    # also run-length encode the zeros. 0 and 1 are both plain rows.
    RAW = 0
    RAW_ALT = 1
    SCANLINES = 2
    RLE_ZERO = 3


@dataclass(frozen=True, slots=True)
class ShpImage:
    """Equal-size frames of palette indices (0 is transparent)."""

    width: int
    height: int
    frames: tuple[bytes, ...]

    def __post_init__(self) -> None:
        """Reject frames that do not cover the canvas.

        Raises:
            AssetError: If the canvas is empty or a frame mis-sized.
        """
        if self.width <= 0 or self.height <= 0 or not self.frames:
            detail = f"need frames on a positive canvas, got {self.width}x{self.height}"
            raise AssetError.invalid_format(_FORMAT, detail)
        area = self.width * self.height
        for index, frame in enumerate(self.frames):
            if len(frame) != area:
                detail = f"frame {index} has {len(frame)} pixels, not {area}"
                raise AssetError.invalid_format(_FORMAT, detail)


def encode_shp(image: ShpImage) -> bytes:
    """Encode every frame as full-canvas RLE-zero scanlines.

    Args:
        image: Frames to encode.

    Returns:
        SHP file bytes, the inverse of `decode_shp`.
    """
    bodies = [
        b"".join(
            _encode_row(frame[start : start + image.width])
            for start in range(0, len(frame), image.width)
        )
        for frame in image.frames
    ]
    offset = _HEADER.size + _FRAME.size * len(bodies)
    headers: list[bytes] = []
    for body in bodies:
        headers.append(_frame_header(image.width, image.height, offset))
        offset += len(body)
    count = len(bodies)
    header = _HEADER.pack(0, image.width, image.height, count)
    return header + b"".join(headers) + b"".join(bodies)


def decode_shp(data: bytes) -> ShpImage:
    """Decode an SHP into full-canvas frames.

    Args:
        data: SHP file bytes using compression 0 to 3.

    Returns:
        Every frame placed on the shared canvas.

    Raises:
        AssetError: If the data is truncated or uses another encoding.
    """
    try:
        _, width, height, count = _HEADER.unpack_from(data, 0)
        headers = (
            _FRAME.unpack_from(data, _HEADER.size + _FRAME.size * index)
            for index in range(count)
        )
        frames = tuple(_decode_frame(data, h, width, height) for h in headers)
    except (struct.error, IndexError) as exc:
        detail = f"truncated data: {exc}"
        raise AssetError.invalid_format(_FORMAT, detail) from exc
    return ShpImage(width, height, frames)


def _frame_header(width: int, height: int, offset: int) -> bytes:
    no_radar_colour = (0, 0, 0, 0)
    return _FRAME.pack(
        0, 0, width, height, _Compression.RLE_ZERO, *no_radar_colour, 0, offset
    )


def _encode_row(row: bytes) -> bytes:
    encoded = bytearray()
    index = 0
    while index < len(row):
        if row[index]:
            encoded.append(row[index])
            index += 1
            continue
        start = index
        while index < len(row) and not row[index] and index - start < _RUN_MAX:
            index += 1
        encoded.extend((0, index - start))
    return _ROW_LENGTH.pack(len(encoded) + _ROW_LENGTH.size) + bytes(encoded)


def _decode_frame(
    data: bytes,
    header: tuple[int, ...],
    width: int,
    height: int,
) -> bytes:
    left, top, frame_width, frame_height, compression, *_, offset = header
    canvas = bytearray(width * height)
    if not frame_width or not frame_height:
        return bytes(canvas)
    match compression:
        case _Compression.RAW | _Compression.RAW_ALT:
            rows = [
                data[start : start + frame_width]
                for start in range(
                    offset, offset + frame_width * frame_height, frame_width
                )
            ]
        case _Compression.SCANLINES | _Compression.RLE_ZERO:
            expand = compression == _Compression.RLE_ZERO
            rows = _decode_rows(data, offset, frame_width, frame_height, expand=expand)
        case _:
            detail = f"unsupported compression {compression}"
            raise AssetError.invalid_format(_FORMAT, detail)
    for row, pixels in enumerate(rows):
        start = (top + row) * width + left
        canvas[start : start + frame_width] = pixels
    return bytes(canvas)


def _decode_rows(
    data: bytes,
    offset: int,
    width: int,
    height: int,
    *,
    expand: bool,
) -> list[bytes]:
    rows: list[bytes] = []
    for _ in range(height):
        length = int.from_bytes(data[offset : offset + _ROW_LENGTH.size], "little")
        encoded = data[offset + _ROW_LENGTH.size : offset + length]
        offset += length
        row = _expand_zero_runs(encoded) if expand else encoded
        if len(row) != width:
            detail = f"row decodes to {len(row)} pixels, expected {width}"
            raise AssetError.invalid_format(_FORMAT, detail)
        rows.append(row)
    return rows


def _expand_zero_runs(encoded: bytes) -> bytes:
    row = bytearray()
    index = 0
    while index < len(encoded):
        if encoded[index]:
            row.append(encoded[index])
            index += 1
        else:
            row.extend(bytes(encoded[index + 1]))
            index += 2
    return bytes(row)
