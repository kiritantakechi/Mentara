"""Build generated layer files from editable sources.

The source tree mirrors the layer tree, and each source compiles to the
file named by dropping its source suffix:

- `<name>.csf.toml` -> `<name>.csf`: `[strings]` table, label = "text".
- `<name>.pal.toml` -> `<name>.pal`: `colours = ["#RRGGBB", ...]`.
- `<name>.shp.toml` -> `<name>.shp`: `sheet`, an indexed PNG beside it,
  cut into `frame = [width, height]` cells left to right, top to bottom
  (optionally only the first `count`).
- `<name>.dll/` -> `<name>.dll`: Zig sources of a Syringe hook DLL,
  rooted at `root.zig`, built with Zig for 32-bit Windows without a C
  runtime.

Other files in the source tree are inputs of these, such as sheets.
"""

import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, assert_never
lazy from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mentara.csf import encode_csf
from mentara.errors import AssetError
from mentara.palette import Rgb, encode_palette
from mentara.png import decode_indexed_png
from mentara.shp import ShpImage, encode_shp

__all__ = [
    "AssetKind",
    "AssetSource",
    "compile_asset",
    "find_asset_sources",
    "stale_assets",
    "write_assets",
]


class AssetKind(StrEnum):
    """Source suffix of each buildable asset kind."""

    STRING_TABLE = ".csf.toml"
    PALETTE = ".pal.toml"
    SHAPE = ".shp.toml"
    HOOK_DLL = ".dll"


_FILE_KINDS: Final[tuple[AssetKind, ...]] = (
    AssetKind.STRING_TABLE,
    AssetKind.PALETTE,
    AssetKind.SHAPE,
)
_TOML_SUFFIX: Final[str] = ".toml"
_SOURCE_FORMAT: Final[str] = "TOML source"
_SHEET_FORMAT: Final[str] = "shape sheet"
_DLL_FORMAT: Final[str] = "hook DLL"
_ZIG: Final[str] = "zig"
_HOOK_DLL_ROOT: Final[str] = "root.zig"
# The game is a 32-bit MSVC program. Safety checks stay on: the DLL's
# own panic handler traps, so a failed check stops the game in the hook
# that found it. Zig's output is reproducible: a rebuild changes no
# bytes.
_HOOK_DLL_FLAGS: Final[tuple[str, ...]] = (
    "build-lib",
    "-dynamic",
    "-target",
    "x86-windows-msvc",
    "-O",
    "ReleaseSafe",
    "-fsingle-threaded",
    "-fstrip",
)


@dataclass(frozen=True, slots=True)
class AssetSource:
    """One source and the layer file it builds."""

    kind: AssetKind
    path: Path
    output: Path


class _StringTableSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strings: dict[str, str]


class _PaletteSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    colours: tuple[str, ...] = Field(min_length=1)


class _ShapeSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sheet: str
    frame: tuple[int, int]
    count: int | None = Field(default=None, gt=0)


def find_asset_sources(
    source_root: Path,
    output_root: Path,
) -> tuple[AssetSource, ...]:
    """List every buildable source under `source_root`.

    Args:
        source_root: Root of the source tree.
        output_root: Root of the layer tree it mirrors.

    Returns:
        Sources in path order, each with its output path.
    """
    sources: list[AssetSource] = []
    if not source_root.is_dir():
        return ()
    for directory, dirnames, filenames in source_root.walk():
        target = output_root / directory.relative_to(source_root)
        dlls = [name for name in dirnames if name.endswith(AssetKind.HOOK_DLL)]
        sources.extend(
            AssetSource(AssetKind.HOOK_DLL, directory / name, target / name)
            for name in dlls
        )
        # A hook DLL directory is one source, not a tree to descend.
        dirnames[:] = sorted(set(dirnames) - set(dlls))
        for name in filenames:
            kind = next((kind for kind in _FILE_KINDS if name.endswith(kind)), None)
            if kind is not None:
                output = target / name.removesuffix(_TOML_SUFFIX)
                sources.append(AssetSource(kind, directory / name, output))
    return tuple(sorted(sources, key=lambda source: source.path.as_posix()))


def compile_asset(source: AssetSource) -> bytes:
    """Build the bytes of one asset.

    Args:
        source: Source to compile.

    Returns:
        Contents of the output file.

    Raises:
        AssetError: If the source is invalid or a build tool fails.
    """
    try:
        match source.kind:
            case AssetKind.STRING_TABLE:
                return encode_csf(_load(source.path, _StringTableSource).strings)
            case AssetKind.PALETTE:
                colours = _load(source.path, _PaletteSource).colours
                return encode_palette([Rgb.from_hex(colour) for colour in colours])
            case AssetKind.SHAPE:
                return _compile_shape(source.path)
            case AssetKind.HOOK_DLL:
                return _compile_hook_dll(source.path, source.output.name)
            case _:
                assert_never(source.kind)
    except AssetError as exc:
        raise AssetError.invalid_source(source.path, str(exc)) from exc


def stale_assets(sources: Sequence[AssetSource]) -> tuple[AssetSource, ...]:
    """Return the sources whose output is missing or out of date.

    Args:
        sources: Sources to check.

    Returns:
        Sources whose compiled bytes differ from their output file.
    """
    return tuple(
        source for source in sources if _read(source.output) != compile_asset(source)
    )


def write_assets(sources: Sequence[AssetSource]) -> tuple[AssetSource, ...]:
    """Build every source and write the outputs that changed.

    Args:
        sources: Sources to build.

    Returns:
        Sources whose output file was created or rewritten.
    """
    written: list[AssetSource] = []
    for source in sources:
        content = compile_asset(source)
        if _read(source.output) == content:
            continue
        source.output.parent.mkdir(parents=True, exist_ok=True)
        source.output.write_bytes(content)
        written.append(source)
    return tuple(written)


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _load[M: BaseModel](path: Path, model: type[M]) -> M:
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
        return model.model_validate(payload)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise AssetError.invalid_format(_SOURCE_FORMAT, str(exc)) from exc


def _compile_shape(path: Path) -> bytes:
    manifest = _load(path, _ShapeSource)
    try:
        sheet = decode_indexed_png((path.parent / manifest.sheet).read_bytes())
    except OSError as exc:
        raise AssetError.invalid_format(_SHEET_FORMAT, str(exc)) from exc
    width, height = manifest.frame
    if width <= 0 or height <= 0 or sheet.width % width or sheet.height % height:
        detail = f"{sheet.width}x{sheet.height} does not split into {width}x{height}"
        raise AssetError.invalid_format(_SHEET_FORMAT, detail)
    columns = sheet.width // width
    capacity = columns * (sheet.height // height)
    count = capacity if manifest.count is None else manifest.count
    if count > capacity:
        detail = f"{count} frames exceed the sheet's {capacity}"
        raise AssetError.invalid_format(_SHEET_FORMAT, detail)
    cells = ((i % columns * width, i // columns * height) for i in range(count))
    frames = tuple(sheet.crop(x, y, width, height) for x, y in cells)
    return encode_shp(ShpImage(width, height, frames))


def _compile_hook_dll(directory: Path, output_name: str) -> bytes:
    zig = shutil.which(_ZIG)
    if zig is None:
        purpose = "build Syringe hook DLLs"
        raise AssetError.missing_tool(_ZIG, purpose)
    root = directory / _HOOK_DLL_ROOT
    if not root.is_file():
        detail = f"no {_HOOK_DLL_ROOT}"
        raise AssetError.invalid_format(_DLL_FORMAT, detail)
    with tempfile.TemporaryDirectory() as scratch:
        # The export table embeds the output name, so build under it.
        target = Path(scratch) / output_name
        name = Path(output_name).stem
        emit = f"-femit-bin={target}"
        source = str(root.resolve())
        command = [zig, *_HOOK_DLL_FLAGS, "--name", name, emit, source]
        # Run from the scratch directory, so no cache lands in the tree.
        result = subprocess.run(  # noqa: S603 - zig from shutil.which, fixed flags
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=scratch,
        )
        if result.returncode:
            raise AssetError.invalid_format(_DLL_FORMAT, result.stderr.strip())
        return target.read_bytes()
