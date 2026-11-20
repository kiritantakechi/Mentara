"""Tests for building layer files from the asset source tree."""

import io
import shutil
from pathlib import Path

import pytest

from mentara.assets import (
    AssetKind,
    compile_asset,
    find_asset_sources,
    stale_assets,
    write_assets,
)
from mentara.cli import main
from mentara.csf import decode_csf
from mentara.errors import AssetError
from mentara.palette import Rgb
from mentara.png import IndexedImage, encode_indexed_png
from mentara.shp import decode_shp

HOOK_SOURCE = """\
typedef unsigned long DWORD;
typedef struct REGISTERS { DWORD origin, flags, regs[8]; } REGISTERS;
typedef struct __declspec(align(16)) HookDecl {
    unsigned int address, size; const char *name;
} HookDecl;
#pragma section(".syhks00", read, write)
__declspec(dllexport) DWORD __cdecl Probe(REGISTERS *R);
__declspec(allocate(".syhks00")) HookDecl hook_decl = {0x401000, 5, "Probe"};
__declspec(dllexport) DWORD __cdecl Probe(REGISTERS *R) { (void)R; return 0; }
"""


def _write_sources(root: Path) -> None:
    layer = root / "layer" / "data.mix"
    layer.mkdir(parents=True)
    (layer / "strings.csf.toml").write_text(
        '[strings]\n"TXT_A" = "甲"\n', encoding="utf-8"
    )
    (layer / "tones.pal.toml").write_text(
        'colours = ["#000000", "#76EC8C"]\n', encoding="utf-8"
    )
    sheet = IndexedImage(4, 2, bytes((0, 1, 1, 0, 1, 0, 0, 1)), (Rgb(0, 0, 0),))
    (layer / "dots.png").write_bytes(encode_indexed_png(sheet))
    (layer / "dots.shp.toml").write_text(
        'sheet = "dots.png"\nframe = [2, 2]\n', encoding="utf-8"
    )
    (layer / "notes.txt").write_text("not a source\n", encoding="utf-8")


def test_sources_mirror_the_layer_tree_by_suffix(tmp_path: Path) -> None:
    _write_sources(tmp_path / "assets")
    (tmp_path / "assets" / "layer" / "Fix.dll").mkdir()
    (tmp_path / "assets" / "layer" / "Fix.dll" / "a.pal.toml").write_text(
        "", encoding="utf-8"
    )

    sources = find_asset_sources(tmp_path / "assets", tmp_path / "out")

    assert [(s.kind, s.output.relative_to(tmp_path)) for s in sources] == [
        (AssetKind.HOOK_DLL, Path("out/layer/Fix.dll")),
        (AssetKind.SHAPE, Path("out/layer/data.mix/dots.shp")),
        (AssetKind.STRING_TABLE, Path("out/layer/data.mix/strings.csf")),
        (AssetKind.PALETTE, Path("out/layer/data.mix/tones.pal")),
    ]
    assert find_asset_sources(tmp_path / "missing", tmp_path / "out") == ()


def test_write_builds_each_kind_and_stale_tracks_changes(tmp_path: Path) -> None:
    _write_sources(tmp_path / "assets")
    sources = find_asset_sources(tmp_path / "assets", tmp_path / "out")

    assert stale_assets(sources) == sources
    assert write_assets(sources) == sources
    assert stale_assets(sources) == ()
    assert write_assets(sources) == ()

    out = tmp_path / "out" / "layer" / "data.mix"
    assert decode_csf((out / "strings.csf").read_bytes()) == {"TXT_A": "甲"}
    assert (out / "tones.pal").read_bytes()[3:6] == bytes((0x1D, 0x3B, 0x23))
    shape = decode_shp((out / "dots.shp").read_bytes())
    assert shape.frames == (bytes((0, 1, 1, 0)), bytes((1, 0, 0, 1)))

    (out / "tones.pal").write_bytes(b"stale")
    assert [s.output.name for s in stale_assets(sources)] == ["tones.pal"]


def test_invalid_sources_name_the_file(tmp_path: Path) -> None:
    layer = tmp_path / "assets" / "layer"
    layer.mkdir(parents=True)
    (layer / "bad.shp.toml").write_text(
        'sheet = "missing.png"\nframe = [2, 2]\n', encoding="utf-8"
    )
    (layer / "bad.pal.toml").write_text('colours = ["#12"]\n', encoding="utf-8")
    (layer / "bad.csf.toml").write_text("strings = 1\n", encoding="utf-8")

    for source in find_asset_sources(tmp_path / "assets", tmp_path / "out"):
        with pytest.raises(AssetError, match=r"Cannot build asset from .*bad\."):
            compile_asset(source)


@pytest.mark.skipif(shutil.which("clang") is None, reason="needs clang and lld")
def test_hook_dll_directories_compile_with_clang(tmp_path: Path) -> None:
    source_dir = tmp_path / "assets" / "layer" / "Probe.dll"
    source_dir.mkdir(parents=True)
    (source_dir / "probe.c").write_text(HOOK_SOURCE, encoding="utf-8")

    (source,) = find_asset_sources(tmp_path / "assets", tmp_path / "out")
    image = compile_asset(source)

    assert image.startswith(b"MZ")
    assert b".syhks00" in image
    assert b"Probe" in image


def test_cli_assets_builds_then_checks(tmp_path: Path) -> None:
    _write_sources(tmp_path / "assets")
    (tmp_path / "mentara.toml").write_text(
        '[assets]\nsource = "assets"\noutput = "out"\n', encoding="utf-8"
    )
    config = str(tmp_path / "mentara.toml")
    built, checked = io.StringIO(), io.StringIO()

    assert main(["-c", config, "assets"], stdout=built) == 0
    assert main(["-c", config, "assets", "--check"], stdout=checked) == 0

    assert built.getvalue().endswith("3 asset(s), 3 rebuilt\n")
    assert checked.getvalue() == "3 asset(s), 0 stale\n"
    (tmp_path / "out" / "layer" / "data.mix" / "tones.pal").unlink()
    assert main(["-c", config, "assets", "--check"], stdout=io.StringIO()) == 1
