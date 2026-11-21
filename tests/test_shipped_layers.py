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
from mentara.layout import (
    ArchivePlacement,
    PatchFormat,
    PatchPlacement,
    TextFormat,
    is_archive_name,
    parse_patch_name,
    place,
)
from mentara.patcher import (
    INIAppend,
    INIKeyOp,
    INIPatch,
    INISet,
    INIUpdateSection,
    PatchSpec,
    load_patch,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_DIR / "mentara.toml"
BASE_LAYER = "overlays/base"
PHOBOS_LAYER = "overlays/phobos"
ENHANCE_LAYER = "overlays/enhance"
# Bottom to top; each layer assumes the ones below it.
LAYERS = (BASE_LAYER, PHOBOS_LAYER, ENHANCE_LAYER)
_ENGINE_SUFFIXES = frozenset({".dll", ".exe", ".edb", ".pdb"})
_HIDE_VERSION_RE = re.compile(r"-HideVersionWarning=([^\s\"'`,\]]+)")
_EXPANSION_MIX_RE = re.compile(r"expandmo\d{2}\.mix")
_DEFINE_HOOK_RE = re.compile(r"DEFINE_HOOK\(\s*(0x[0-9A-Fa-f]+),\s*(\w+),\s*(\d+)\)")
_HOOK_SECTION = ".syhks00"
# Syringe's hookdecl is 16-byte aligned: address, size, name, padding.
_HOOK_STRIDE = 16

type _Hook = tuple[int, str, int]


def _layer_files(layer: str) -> list[Path]:
    return sorted(path for path in (PROJECT_DIR / layer).rglob("*") if path.is_file())


def _patch_files(layer: str) -> list[tuple[Path, Path, TextFormat]]:
    # (patch file or fragment, virtual path it patches, format)
    root = PROJECT_DIR / layer
    found: list[tuple[Path, Path, TextFormat]] = []
    for path in _layer_files(layer):
        match place(path.relative_to(root)):
            case PatchPlacement(path=target, patch=patch_format):
                found.append((path, target, patch_format))
            case ArchivePlacement(
                archive=archive,
                member=member,
                patch=PatchFormat.INI | PatchFormat.TOML as patch_format,
            ):
                found.append((path, archive.joinpath(*member), patch_format))
    return found


def _ini_patches(layer: str) -> dict[Path, list[INIPatch]]:
    # Every INI patch of a layer, grouped by target: a patch directory's
    # fragments, in name order, form one patch.
    patches: dict[Path, list[INIPatch]] = {}
    for path, target, patch_format in _patch_files(layer):
        patch = load_patch(PatchSpec(patch_format, path, layer))
        if isinstance(patch, INIPatch):
            patches.setdefault(target, []).append(patch)
    return patches


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


def test_every_profile_stacks_the_shipped_layers_in_order() -> None:
    # A profile may stop at any layer but never skips or reorders one:
    # each layer assumes everything below it.
    for name, profile in load_config(CONFIG_PATH).profiles.items():
        layers = list(profile.layers)
        shipped = [layer for layer in layers if layer in LAYERS]
        assert shipped == list(LAYERS[: len(shipped)]), name
        if shipped:
            start = layers.index(shipped[0])
            assert layers[start : start + len(shipped)] == shipped, name


def test_each_engine_file_ships_in_one_layer() -> None:
    # Ares belongs to base and Phobos to phobos; a layer above them
    # relies on the engine below instead of shipping its own copy.
    owners: dict[str, list[str]] = {}
    for layer in LAYERS:
        for path in _layer_files(layer):
            if path.suffix.casefold() in _ENGINE_SUFFIXES:
                owners.setdefault(path.name.casefold(), []).append(layer)

    assert {"ares.dll", "phobos.dll"} <= owners.keys()
    assert {name: found for name, found in owners.items() if len(found) > 1} == {}
    assert not any(ENHANCE_LAYER in found for found in owners.values())


@pytest.mark.parametrize("layer", LAYERS)
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
        patch = parse_patch_name(path.name)
        archive = (path.name if patch is None else patch.target).casefold()
        if is_archive_name(archive):
            assert archive in existing or _EXPANSION_MIX_RE.fullmatch(archive), path


@pytest.mark.parametrize("layer", LAYERS)
def test_every_shipped_patch_parses(layer: str) -> None:
    patches = _patch_files(layer)

    assert patches
    for path, _, patch_format in patches:
        patch = load_patch(PatchSpec(patch_format, path, layer))
        assert patch.operations if isinstance(patch, INIPatch) else patch.edits, path


@pytest.mark.parametrize("layer", LAYERS)
def test_each_patch_updates_a_section_in_one_place(layer: str) -> None:
    # A second update of the same section would split one object's
    # settings across the patch or its fragments. ([-X] then [X], which
    # replaces a duplicated definition, is one deletion and one update.)
    for target, patches in _ini_patches(layer).items():
        updated = [
            operation.section.casefold()
            for patch in patches
            for operation in patch.operations
            if isinstance(operation, INIUpdateSection) and operation.section is not None
        ]
        repeated = sorted({name for name in updated if updated.count(name) > 1})
        assert not repeated, (target, repeated)


def _ini_sections(layer: str, target: str) -> dict[str, tuple[INIKeyOp, ...]]:
    sections: dict[str, tuple[INIKeyOp, ...]] = {}
    for target_path, patches in _ini_patches(layer).items():
        if target_path.name.casefold() != f"{target}.ini":
            continue
        for operation in (op for patch in patches for op in patch.operations):
            # Keys above the first header (section None) name no type.
            if (
                isinstance(operation, INIUpdateSection)
                and operation.section is not None
            ):
                name = operation.section.casefold()
                sections[name] = sections.get(name, ()) + operation.operations
    return sections


@pytest.mark.parametrize("layer", LAYERS)
def test_registered_animations_ship_their_art(layer: str) -> None:
    # A layer that appends to [Animations] ships the art section and the
    # shape too; otherwise the type keeps every art default and draws
    # nothing.
    registered = [
        operation.value
        for operation in _ini_sections(layer, "rulesmo").get("animations", ())
        if isinstance(operation, INIAppend)
    ]
    art = _ini_sections(layer, "artmo")
    shapes = {
        path.stem.casefold() for path in _layer_files(layer) if path.suffix == ".shp"
    }

    for name in registered:
        assert name.casefold() in art, name
        image = next(
            (
                op.value
                for op in art[name.casefold()]
                if isinstance(op, INISet) and op.key.casefold() == "image"
            ),
            name,
        )
        assert image.casefold() in shapes, name


# Phobos loads a type's settings only if its list names it; a type that
# is merely referenced is created with every default (Enumerable.h).
_PHOBOS_TYPE_LISTS: dict[str, tuple[str, ...]] = {
    "attacheffecttypes": (
        "attacheffect.attachtypes",
        "attacheffect.removetypes",
        "attacheffect.requiredtypes",
        "attacheffect.disallowedtypes",
    ),
    "digitaldisplaytypes": (
        "digitaldisplaytypes",
        "infantry.defaultdigitaldisplaytypes",
        "vehicles.defaultdigitaldisplaytypes",
        "aircraft.defaultdigitaldisplaytypes",
        "buildings.defaultdigitaldisplaytypes",
    ),
    "selectboxtypes": (
        "selectbox",
        "defaultinfantryselectbox",
        "defaultunitselectbox",
    ),
    "shieldtypes": ("shieldtype",),
}


@pytest.mark.parametrize("depth", range(1, len(LAYERS) + 1))
def test_phobos_types_are_registered_and_defined(depth: int) -> None:
    stack = LAYERS[:depth]
    sections = {
        name: ops
        for layer in stack
        for name, ops in _ini_sections(layer, "rulesmo").items()
    }
    for listed, keys in _PHOBOS_TYPE_LISTS.items():
        registered = {
            op.value.casefold()
            for op in sections.get(listed, ())
            if isinstance(op, INIAppend)
        }
        referenced = {
            name.strip().casefold()
            for ops in sections.values()
            for op in ops
            if isinstance(op, INISet) and op.key.casefold() in keys
            for name in op.value.split(",")
            if name.strip()
        }
        assert referenced <= registered, (stack[-1], listed, referenced - registered)
        assert registered <= sections.keys(), (
            stack[-1],
            listed,
            registered - sections.keys(),
        )


# Objects the layers add (named Phobos* or Enhance*) and the YR list
# each kind must appear in; ExtraWarheads ignores an unlisted warhead.
_YR_TYPE_LISTS: dict[str, tuple[str, ...]] = {
    "weapontypes": (
        "primary",
        "secondary",
        "eliteprimary",
        "elitesecondary",
        "feedbackweapon",
        "deathweapon",
        "airburstweapon",
    ),
    "warheads": ("warhead", "extrawarheads", "sw.warhead"),
    "projectiles": ("projectile",),
}
_NEW_OBJECT_RE = re.compile(r"(?i)(phobos|enhance)\w*")


@pytest.mark.parametrize("depth", range(1, len(LAYERS) + 1))
def test_added_weapons_warheads_and_projectiles_are_listed(depth: int) -> None:
    sections = {
        name: ops
        for layer in LAYERS[:depth]
        for name, ops in _ini_sections(layer, "rulesmo").items()
    }
    for listed, keys in _YR_TYPE_LISTS.items():
        registered = {
            op.value.casefold()
            for op in sections.get(listed, ())
            if isinstance(op, INIAppend)
        }
        added = {
            name.strip().casefold()
            for ops in sections.values()
            for op in ops
            if isinstance(op, INISet) and op.key.casefold() in keys
            for name in op.value.split(",")
            if _NEW_OBJECT_RE.fullmatch(name.strip())
        }
        assert added <= registered, (LAYERS[depth - 1], listed, added - registered)


# The engine stores a type's ID in 24 characters. Ares reports a longer
# section or list entry as a fatal error and keeps it truncated, so the
# truncated type loses every setting its section gives it.
_ENGINE_INIS = ("rulesmo", "artmo", "aimo")
_MAX_TYPE_ID_LENGTH = 24


@pytest.mark.parametrize("target", _ENGINE_INIS)
@pytest.mark.parametrize("layer", LAYERS)
def test_type_ids_fit_the_engine(layer: str, target: str) -> None:
    sections = _ini_sections(layer, target)
    names = sections.keys() | {
        op.value.casefold()
        for ops in sections.values()
        for op in ops
        if isinstance(op, INIAppend)
    }
    too_long = sorted(name for name in names if len(name) > _MAX_TYPE_ID_LENGTH)
    assert not too_long, (layer, target, too_long)


def test_hide_version_warning_matches_the_shipped_phobos_build() -> None:
    # Phobos only honours the flag when it names its own FileVersion,
    # and the flag is repeated in the client patch and in mentara.toml.
    sources = [CONFIG_PATH, *(path for path, _, _ in _patch_files(PHOBOS_LAYER))]
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
