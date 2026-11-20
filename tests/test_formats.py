"""Tests for the palette, indexed PNG, SHP and CSF codecs."""

import zlib

import pytest

from mentara.csf import decode_csf, encode_csf
from mentara.errors import AssetError
from mentara.palette import PALETTE_SIZE, Rgb, decode_palette, encode_palette
from mentara.png import IndexedImage, decode_indexed_png, encode_indexed_png
from mentara.shp import ShpImage, decode_shp, encode_shp

GREEN = Rgb(0x76, 0xEC, 0x8C)


def test_rgb_hex_round_trips_and_rejects_bad_text() -> None:
    assert Rgb.from_hex("#76EC8C") == GREEN
    assert Rgb.from_hex("76ec8c").to_hex() == "#76EC8C"
    with pytest.raises(AssetError, match="expected #RRGGBB"):
        Rgb.from_hex("#76EC8")
    with pytest.raises(AssetError, match="expected #RRGGBB"):
        Rgb.from_hex("#GGGGGG")


def test_palette_keeps_six_bits_per_channel_and_pads_with_black() -> None:
    data = encode_palette([Rgb(0, 0, 0), GREEN])

    assert len(data) == PALETTE_SIZE * 3
    assert data[3:6] == bytes((0x76 >> 2, 0xEC >> 2, 0x8C >> 2))
    assert set(data[6:]) == {0}
    colours = decode_palette(data)
    assert colours[1] == Rgb(117, 239, 142)  # (v << 2) | (v >> 4)
    assert encode_palette(colours) == data
    with pytest.raises(AssetError, match="exceed 256"):
        encode_palette([GREEN] * (PALETTE_SIZE + 1))


def test_indexed_png_round_trips_and_crops() -> None:
    image = IndexedImage(3, 2, bytes((0, 1, 2, 2, 1, 0)), (Rgb(0, 0, 0), GREEN))

    decoded = decode_indexed_png(encode_indexed_png(image))

    assert decoded == image
    assert decoded.crop(1, 0, 2, 2) == bytes((1, 2, 1, 0))
    with pytest.raises(AssetError, match="leaves 3x2"):
        decoded.crop(2, 0, 2, 2)


def test_indexed_png_rejects_other_formats_and_corruption() -> None:
    data = bytearray(encode_indexed_png(IndexedImage(1, 1, b"\0", (GREEN,))))
    data[25] = 2  # IHDR colour type: truecolour, re-signed below
    data[29:33] = zlib.crc32(data[12:29]).to_bytes(4, "big")

    with pytest.raises(AssetError, match="colour type 2"):
        decode_indexed_png(bytes(data))
    data[20] ^= 1
    with pytest.raises(AssetError, match="bad CRC"):
        decode_indexed_png(bytes(data))
    with pytest.raises(AssetError, match="missing PNG signature"):
        decode_indexed_png(b"GIF89a")


def test_shp_round_trips_with_rle_zero_frames() -> None:
    frames = (bytes((0, 0, 3, 0, 0, 0)), bytes((5, 0, 0, 0, 0, 6)))
    image = ShpImage(3, 2, frames)

    data = encode_shp(image)

    assert decode_shp(data) == image
    assert {data[8 + 24 * i + 8] for i in range(2)} == {3}
    with pytest.raises(AssetError, match="frame 1 has 5 pixels"):
        ShpImage(3, 2, (bytes(6), bytes(5)))


def test_csf_round_trips_unicode_and_empty_strings() -> None:
    strings = {"TXT_GAMETIME": "时间", "PHOBOS:PowerLabel": "", "A": "$"}

    data = encode_csf(strings)

    assert data.startswith(b" FSC")
    assert decode_csf(data) == strings
    with pytest.raises(AssetError, match="not ASCII"):
        encode_csf({"标签": "x"})
    with pytest.raises(AssetError, match="signature"):
        decode_csf(b"XXXX" + data[4:])
