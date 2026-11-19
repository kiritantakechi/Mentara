"""Tests for configuration loading, validation, and profile paths."""

lazy from pathlib import Path

import pytest

from mentara.config import (
    BackendKind,
    MentaraConfig,
    ProfileOverrides,
    find_config_path,
    load_config,
    resolve_profile,
)
from mentara.errors import ConfigError


def test_load_config_parses_profiles_and_merges_runner(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "mentara.toml"
    base_dir = tmp_path / "game"
    layer_a = tmp_path / "layers" / "a"
    layer_b = tmp_path / "layers" / "b"
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "state"
    for directory in (base_dir, layer_a, layer_b):
        directory.mkdir(parents=True)

    config_file.write_text(
        f"""
base_dir = "{base_dir}"
runtime_dir = "{runtime_dir}"
state_dir = "{state_dir}"
default_profile = "modded"
backend = "fuse-overlayfs"

[runner]
command = ["umu-run"]
executable = "MentalOmegaClient.exe"
env = {{ WINEDLLOVERRIDES = "ddraw=n,b", SHARED = "1" }}

[profiles.modded]
description = "Stacked layers"
layers = ["layers/a", "layers/b"]
backend = "symlink"

[profiles.modded.runner]
executable = "Syringe.exe"
args = ["gamemd.exe", "-LOG"]
env = {{ WINEDLLOVERRIDES = "ddraw=n,b;Phobos=n,b" }}
""",
        encoding="utf-8",
    )

    loaded = load_config(config_file)
    resolved = resolve_profile(
        loaded,
        config_dir=tmp_path,
        overrides=ProfileOverrides(extra_args=("-CD",)),
    )

    assert resolved.name == "modded"
    assert resolved.backend is BackendKind.SYMLINK
    assert resolved.layers == (layer_a.resolve(), layer_b.resolve())
    assert resolved.runtime_dir == (runtime_dir / "modded").resolve()
    assert resolved.state_dir == (state_dir / "modded").resolve()
    assert resolved.runner.command == ("umu-run",)
    assert resolved.runner.executable == "Syringe.exe"
    assert resolved.runner.args == ("gamemd.exe", "-LOG", "-CD")
    assert resolved.runner.env == frozendict(
        {
            "WINEDLLOVERRIDES": "ddraw=n,b;Phobos=n,b",
            "SHARED": "1",
        }
    )


def test_load_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config_file = tmp_path / "mentara.toml"
    config_file.write_text('bogus_option = "nope"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid configuration"):
        load_config(config_file)


def test_load_config_rejects_invalid_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "mentara.toml"
    config_file.write_text("[runner\ncommand = ", encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_config(config_file)


def test_load_config_rejects_missing_default_profile(tmp_path: Path) -> None:
    config_file = tmp_path / "mentara.toml"
    config_file.write_text(
        """
default_profile = "missing"

[profiles.default]
layers = []
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="default_profile"):
        load_config(config_file)


def test_resolve_profile_rejects_unknown_profile(tmp_path: Path) -> None:
    config = MentaraConfig(
        base_dir=str(tmp_path / "base"),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
    )

    with pytest.raises(ConfigError, match="Unknown profile 'ghost'"):
        resolve_profile(config, config_dir=tmp_path, profile_name="ghost")


def test_resolve_profile_rejects_nested_runtime_inside_base(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "game"
    base_dir.mkdir()
    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(base_dir / "Mentara" / "runtime"),
        state_dir=str(tmp_path / "state"),
    )

    with pytest.raises(ConfigError, match="must not overlap"):
        resolve_profile(config, config_dir=tmp_path)


def test_resolve_profile_allows_layers_under_base_mentara_dir(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "game"
    mentara_dir = base_dir / "Mentara"
    layer_dir = mentara_dir / "overlays" / "custom"
    layer_dir.mkdir(parents=True)

    config_file = mentara_dir / "mentara.toml"
    config_file.write_text(
        f"""
base_dir = ".."
runtime_dir = "{tmp_path / "runtime"}"
state_dir = "{tmp_path / "state"}"

[profiles.default]
layers = ["overlays/custom"]
""",
        encoding="utf-8",
    )

    config = load_config(config_file)
    resolved = resolve_profile(config, config_dir=mentara_dir)

    assert resolved.base_dir == base_dir.resolve()
    assert resolved.layers == (layer_dir.resolve(),)


def test_resolve_profile_rejects_duplicate_or_base_layer(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "game"
    layer_dir = tmp_path / "layer"
    base_dir.mkdir()
    layer_dir.mkdir()

    dup_file = tmp_path / "dup.toml"
    dup_file.write_text(
        f"""
base_dir = "{base_dir}"
runtime_dir = "{tmp_path / "rt"}"
state_dir = "{tmp_path / "st"}"

[profiles.default]
layers = ["{layer_dir}", "{layer_dir}"]
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate overlay layer"):
        resolve_profile(load_config(dup_file), config_dir=tmp_path)

    same_file = tmp_path / "same.toml"
    same_file.write_text(
        f"""
base_dir = "{base_dir}"
runtime_dir = "{tmp_path / "rt"}"
state_dir = "{tmp_path / "st"}"

[profiles.default]
layers = ["{base_dir}"]
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="must not equal base_dir"):
        resolve_profile(load_config(same_file), config_dir=tmp_path)


def test_find_config_path_walks_upward(tmp_path: Path) -> None:
    config_file = tmp_path / "mentara.toml"
    config_file.write_text("", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    found = find_config_path(cwd=nested)
    assert found == config_file.resolve()

    with pytest.raises(ConfigError, match="Configuration file not found"):
        find_config_path(explicit=tmp_path / "missing.toml")
