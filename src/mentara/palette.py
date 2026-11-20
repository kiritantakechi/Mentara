"""Westwood `.pal` palettes: 256 colours stored as 6-bit VGA triples."""

from dataclasses import dataclass
from typing import Final, Self
lazy from collections.abc import Sequence

from mentara.errors import AssetError

__all__ = [
    "PALETTE_SIZE",
    "Rgb",
    "decode_palette",
    "encode_palette",
]

PALETTE_SIZE: Final[int] = 256
_FORMAT: Final[str] = "palette"
_COLOUR: Final[str] = "colour"
_CHANNEL_MAX: Final[int] = 255
_HEX_DIGITS: Final[int] = 6
# 8-bit channels keep their top six bits; widening repeats the top two.
_VGA_SHIFT: Final[int] = 2
_VGA_REFILL_SHIFT: Final[int] = 4
_PAL_BYTES: Final[int] = PALETTE_SIZE * 3


@dataclass(frozen=True, slots=True)
class Rgb:
    """An 8-bit-per-channel colour."""

    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        """Reject channels outside 0-255.

        Raises:
            AssetError: If any channel is out of range.
        """
        channels = (self.red, self.green, self.blue)
        if not all(0 <= channel <= _CHANNEL_MAX for channel in channels):
            detail = f"channels must be 0-255, got {channels}"
            raise AssetError.invalid_format(_COLOUR, detail)

    @classmethod
    def from_hex(cls, text: str) -> Self:
        """Parse a `#RRGGBB` colour, the inverse of `to_hex`.

        Args:
            text: Colour such as `#76EC8C` (the `#` is optional).

        Returns:
            The parsed colour.

        Raises:
            AssetError: If `text` is not six hex digits.
        """
        digits = text.removeprefix("#")
        detail = f"expected #RRGGBB, got {text!r}"
        if len(digits) != _HEX_DIGITS:
            raise AssetError.invalid_format(_COLOUR, detail)
        try:
            value = int(digits, 16)
        except ValueError as exc:
            raise AssetError.invalid_format(_COLOUR, detail) from exc
        return cls(value >> 16, (value >> 8) & 0xFF, value & 0xFF)

    def to_hex(self) -> str:
        """Format as `#RRGGBB`, the inverse of `from_hex`."""
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


def encode_palette(colours: Sequence[Rgb]) -> bytes:
    """Encode up to 256 colours as a `.pal` file, padding with black.

    The game stores 6-bit channels, so the two low bits of each channel
    are dropped; `decode_palette` widens them back.

    Args:
        colours: Colours in palette-index order.

    Returns:
        768 bytes of 6-bit VGA triples.

    Raises:
        AssetError: If more than 256 colours are given.
    """
    if len(colours) > PALETTE_SIZE:
        detail = f"{len(colours)} colours exceed {PALETTE_SIZE} entries"
        raise AssetError.invalid_format(_FORMAT, detail)
    black = Rgb(0, 0, 0)
    padded = (*colours, *(black for _ in range(PALETTE_SIZE - len(colours))))
    return bytes(
        channel >> _VGA_SHIFT
        for colour in padded
        for channel in (colour.red, colour.green, colour.blue)
    )


def decode_palette(data: bytes) -> tuple[Rgb, ...]:
    """Decode a `.pal` file, widening 6-bit channels to 8 bits.

    Args:
        data: 768 bytes of 6-bit VGA triples.

    Returns:
        256 colours in palette-index order.

    Raises:
        AssetError: If `data` is not a 768-byte 6-bit palette.
    """
    if len(data) != _PAL_BYTES:
        detail = f"expected {_PAL_BYTES} bytes, got {len(data)}"
        raise AssetError.invalid_format(_FORMAT, detail)
    widened = [(value << _VGA_SHIFT) | (value >> _VGA_REFILL_SHIFT) for value in data]
    return tuple(Rgb(*widened[i : i + 3]) for i in range(0, _PAL_BYTES, 3))
