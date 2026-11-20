"""Contract tests for the overlay layers and profiles in this repo."""

import re
from pathlib import Path

import pytest

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


def _layer_files(layer: str) -> list[Path]:
    return sorted(path for path in (PROJECT_DIR / layer).rglob("*") if path.is_file())


def _patch_files(layer: str) -> list[tuple[Path, PatchKind]]:
    return [
        (path, target[1])
        for path in _layer_files(layer)
        if (target := parse_patch_target(Path(path.name))) is not None
    ]


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
