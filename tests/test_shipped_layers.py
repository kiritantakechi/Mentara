"""Contract tests for the overlay layers and profiles in this repo."""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from mentara.assets import (
    AssetKind,
    AssetSource,
    compile_asset,
    find_asset_sources,
)
from mentara.config import load_config
from mentara.patcher import (
    PatchKind,
    parse_ini_patch,
    parse_patch_target,
    parse_toml_patch,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_DIR / "mentara.toml"
BASE_LAYER = "overlays/base"
PHOBOS_LAYER = "overlays/phobos"
_ENGINE_SUFFIXES = frozenset({".dll", ".exe", ".edb", ".pdb"})
_HIDE_VERSION_RE = re.compile(r"-HideVersionWarning=([^\s\"'`,\]]+)")
_EXPANSION_MIX_RE = re.compile(r"expandmo\d{2}\.mix")
_MIX_PATCH_SUFFIX = ".patch.mix"
_DEFINE_HOOK_RE = re.compile(r"DEFINE_HOOK\(\s*(0x[0-9A-Fa-f]+),\s*(\w+),\s*(\d+)\)")
_HOOK_SECTION = ".syhks00"
# Syringe's hookdecl is 16-byte aligned: address, size, name, padding.
_HOOK_STRIDE = 16

type _Hook = tuple[int, str, int]


def _layer_files(layer: str) -> list[Path]:
    return sorted(path for path in (PROJECT_DIR / layer).rglob("*") if path.is_file())


def _patch_files(layer: str) -> list[tuple[Path, PatchKind]]:
    return [
        (path, target[1])
        for path in _layer_files(layer)
        if (target := parse_patch_target(Path(path.name))) is not None
    ]


def _c_string(image: bytes, offset: int) -> str:
    return image[offset : image.index(b"\0", offset)].decode("ascii")


@dataclass(frozen=True, slots=True)
class _Section:
    name: str
    rva: int
    virtual_size: int
    raw_offset: int
    raw_size: int

    def contains(self, rva: int) -> bool:
        # Some linkers leave VirtualSize at 0 and rely on the raw size.
        return self.rva <= rva < self.rva + max(self.virtual_size, self.raw_size)


def _u32(image: bytes, offset: int) -> int:
    return int.from_bytes(image[offset : offset + 4], "little")


def _syringe_hooks(image: bytes) -> tuple[set[_Hook], set[str]]:
    pe = _u32(image, 0x3C)
    section_count = int.from_bytes(image[pe + 6 : pe + 8], "little")
    optional_size = int.from_bytes(image[pe + 20 : pe + 22], "little")
    optional = pe + 24
    image_base = _u32(image, optional + 28)
    table = optional + optional_size
    sections = [
        _Section(
            name=image[header : header + 8].rstrip(b"\0").decode("ascii"),
            rva=_u32(image, header + 12),
            virtual_size=_u32(image, header + 8),
            raw_offset=_u32(image, header + 20),
            raw_size=_u32(image, header + 16),
        )
        for header in range(table, table + 40 * section_count, 40)
    ]

    def file_offset(rva: int) -> int:
        section = next(section for section in sections if section.contains(rva))
        return rva - section.rva + section.raw_offset

    hooks = {
        (
            _u32(image, entry),
            _c_string(image, file_offset(_u32(image, entry + 8) - image_base)),
            _u32(image, entry + 4),
        )
        for section in sections
        if section.name == _HOOK_SECTION
        for entry in range(
            section.raw_offset, section.raw_offset + section.virtual_size, _HOOK_STRIDE
        )
        if _u32(image, entry)  # zero entries pad the table
    }
    export_dir = file_offset(_u32(image, optional + 96))
    names = file_offset(_u32(image, export_dir + 32))
    exports = {
        _c_string(image, file_offset(_u32(image, names + 4 * index)))
        for index in range(_u32(image, export_dir + 24))
    }
    return hooks, exports


def test_every_profile_stacks_base_directly_below_phobos() -> None:
    config = load_config(CONFIG_PATH)

    for name, profile in config.profiles.items():
        layers = list(profile.layers)
        if PHOBOS_LAYER not in layers:
            continue
        assert BASE_LAYER in layers, name
        assert layers.index(BASE_LAYER) + 1 == layers.index(PHOBOS_LAYER), name


def test_base_layer_ships_none_of_the_phobos_engine_files() -> None:
    engine_names = {
        path.name.casefold()
        for path in (PROJECT_DIR / PHOBOS_LAYER).iterdir()
        if path.is_file() and path.suffix.casefold() in _ENGINE_SUFFIXES
    }

    assert engine_names
    assert not engine_names & {
        path.name.casefold() for path in _layer_files(BASE_LAYER)
    }


@pytest.mark.parametrize("layer", [BASE_LAYER, PHOBOS_LAYER])
def test_new_archives_load_with_the_expansion_mixes(layer: str) -> None:
    # The engine parses CSF string tables and rules right after it
    # loads the EXPANDMO##.MIX archives. Archives found later (ECACHE*,
    # ELOCAL*) left every Phobos label missing, and Phobos crashed
    # formatting one.
    base_dir = (PROJECT_DIR / load_config(CONFIG_PATH).base_dir).resolve()
    existing = (
        {path.name.casefold() for path in base_dir.glob("*.mix")}
        if base_dir.is_dir()
        else set()
    )

    for path in (PROJECT_DIR / layer).iterdir():
        name = path.name.casefold()
        archive = (
            name.removesuffix(_MIX_PATCH_SUFFIX) + ".mix"
            if name.endswith(_MIX_PATCH_SUFFIX)
            else name
        )
        if archive.endswith(".mix"):
            assert archive in existing or _EXPANSION_MIX_RE.fullmatch(archive), path


@pytest.mark.parametrize("layer", [BASE_LAYER, PHOBOS_LAYER])
def test_every_shipped_patch_parses(layer: str) -> None:
    patches = _patch_files(layer)

    assert patches
    for path, kind in patches:
        text = path.read_text(encoding="utf-8")
        match kind:
            case PatchKind.INI:
                assert parse_ini_patch(text, source_path=path).operations, path
            case PatchKind.TOML:
                assert parse_toml_patch(text, source_path=path), path


def test_hide_version_warning_matches_the_shipped_phobos_build() -> None:
    # Phobos only honours the flag when it names its own FileVersion,
    # and the flag is repeated in the client patch and in mentara.toml.
    sources = [CONFIG_PATH, *(path for path, _ in _patch_files(PHOBOS_LAYER))]
    versions = {
        match.group(1)
        for source in sources
        for match in _HIDE_VERSION_RE.finditer(source.read_text(encoding="utf-8"))
    }
    phobos_dll = (PROJECT_DIR / PHOBOS_LAYER / "Phobos.dll").read_bytes()

    assert len(versions) == 1
    (version,) = versions
    assert f"-HideVersionWarning={version}".encode("ascii") in phobos_dll


def _shipped_asset_sources() -> tuple[AssetSource, ...]:
    source_root, output_root = load_config(CONFIG_PATH).assets.resolve(PROJECT_DIR)
    return find_asset_sources(source_root, output_root)


def test_generated_layer_files_match_their_sources() -> None:
    # `just assets` builds these. A source edited without a rebuild, or
    # a hand-edited output, fails here. Hook DLL bytes depend on the
    # clang version, so DLLs are checked against their declarations.
    sources = [s for s in _shipped_asset_sources() if s.kind is not AssetKind.HOOK_DLL]

    assert sources
    for source in sources:
        assert source.output.read_bytes() == compile_asset(source), source.output


def test_hook_dlls_declare_exactly_the_hooks_in_their_sources() -> None:
    # DLLs are committed so players need no compiler; each Syringe hook
    # table must match the DEFINE_HOOKs in the C sources it came from.
    dlls = [s for s in _shipped_asset_sources() if s.kind is AssetKind.HOOK_DLL]

    assert dlls
    for source in dlls:
        declared = {
            (int(address, 16), name, int(size))
            for c_file in sorted(source.path.glob("*.c"))
            for address, name, size in _DEFINE_HOOK_RE.findall(
                c_file.read_text(encoding="utf-8")
            )
        }
        hooks, exports = _syringe_hooks(source.output.read_bytes())
        assert declared, source.path
        assert hooks == declared, source.output
        assert {name for _, name, _ in declared} <= exports, source.output


def test_base_layer_ships_ares_with_its_matching_hook_list() -> None:
    # Ares.dll and Ares.dll.inj must come from one release: the .inj
    # schedules every hook the DLL exports. (Both official releases
    # also list a few hooks Ares never built; Syringe skips those.)
    base = PROJECT_DIR / BASE_LAYER
    dll = (base / "Ares.dll").read_bytes()
    _, exports = _syringe_hooks(dll)
    hook_names = {
        line.partition("=")[2].partition(",")[0].strip()
        for line in (base / "Ares.dll.inj").read_text(encoding="latin-1").splitlines()
        if "=" in line and not line.lstrip().startswith(";")
    }

    assert "3.0p1".encode("utf-16-le") in dll
    assert exports - hook_names == {"SyringeHandshake"}
