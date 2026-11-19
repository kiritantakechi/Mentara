"""Tests for configuration loading, validation, and platform paths."""

lazy from pathlib import Path

import pytest

from mentara.config import (
    BackendKind,
    MentaraConfig,
    MIXDecryptMode,
    PlatformKind,
    ProfileOverrides,
    find_config_path,
    load_config,
    resolve_profile,
)
from mentara.errors import ConfigError


def test_load_config_resolves_linux_and_windows_symmetrically(
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

[linux]
backend = "fuse-overlayfs"

[linux.runner]
command = ["gamescope", "-f", "--", "umu-run"]
executable = "MentalOmegaClient.exe"
env = {{ WINEDLLOVERRIDES = "ddraw=n,b", SHARED = "1" }}

[windows]
backend = "symlink"

[windows.runner]
command = []
executable = "MentalOmegaClient.exe"
env = {{ SHARED = "win" }}

[profiles.modded]
description = "Stacked layers"
layers = ["layers/a", "layers/b"]

[profiles.modded.runner]
executable = "Syringe.exe"
args = ["gamemd.exe", "--args=-LOG"]

[profiles.modded.linux.runner]
env = {{ WINEDLLOVERRIDES = "ddraw=n,b;Phobos=n,b" }}
""",
        encoding="utf-8",
    )

    loaded = load_config(config_file)

    linux_resolved = resolve_profile(
        loaded,
        config_dir=tmp_path,
        platform=PlatformKind.LINUX,
        overrides=ProfileOverrides(extra_args=("-CD",)),
    )
    assert linux_resolved.name == "modded"
    assert linux_resolved.platform is PlatformKind.LINUX
    assert linux_resolved.backend is BackendKind.FUSE_OVERLAYFS
    assert linux_resolved.layers == (layer_a.resolve(), layer_b.resolve())
    assert linux_resolved.runtime_dir == (runtime_dir / "modded").resolve()
    assert linux_resolved.state_dir == (state_dir / "modded").resolve()
    assert linux_resolved.runner.command == (
        "gamescope",
        "-f",
        "--",
        "umu-run",
    )
    assert linux_resolved.runner.executable == "Syringe.exe"
    assert linux_resolved.runner.args == ("gamemd.exe", "--args=-LOG", "-CD")
    assert linux_resolved.runner.env == frozendict(
        {
            "WINEDLLOVERRIDES": "ddraw=n,b;Phobos=n,b",
            "SHARED": "1",
        }
    )

    win_resolved = resolve_profile(
        loaded,
        config_dir=tmp_path,
        platform=PlatformKind.WINDOWS,
    )
    assert win_resolved.platform is PlatformKind.WINDOWS
    assert win_resolved.backend is BackendKind.SYMLINK
    assert win_resolved.runner.command == ()
    assert win_resolved.runner.executable == "Syringe.exe"
    assert win_resolved.runner.args == ("gamemd.exe", "--args=-LOG")
    assert win_resolved.runner.env == frozendict({"SHARED": "win"})


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


def test_default_storage_roots_are_symmetric_across_linux_and_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_home = tmp_path / "xdg-cache"
    state_home = tmp_path / "xdg-state"
    local_app_data = tmp_path / "AppData" / "Local"
    base_dir = tmp_path / "game"
    base_dir.mkdir()
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    config = MentaraConfig(base_dir=str(base_dir))

    linux_resolved = resolve_profile(
        config,
        config_dir=tmp_path,
        platform=PlatformKind.LINUX,
    )
    expected_linux_rt = (cache_home / "mentara" / "runtime" / "default").resolve()
    assert linux_resolved.runtime_dir == expected_linux_rt
    assert linux_resolved.state_dir == (state_home / "mentara" / "default").resolve()

    win_resolved = resolve_profile(
        config,
        config_dir=tmp_path,
        platform=PlatformKind.WINDOWS,
    )
    expected_win_rt = (local_app_data / "mentara" / "runtime" / "default").resolve()
    expected_win_st = (local_app_data / "mentara" / "state" / "default").resolve()
    assert win_resolved.runtime_dir == expected_win_rt
    assert win_resolved.state_dir == expected_win_st


def test_mix_config_inherits_and_validates_mvmx_secret(tmp_path: Path) -> None:
    base_dir = tmp_path / "game"
    base_dir.mkdir()
    valid_secret = "a" * 64
    cfg_path = tmp_path / "mentara.toml"
    cfg_path.write_text(
        f"""
base_dir = "{base_dir}"
runtime_dir = "{tmp_path / "rt"}"
state_dir = "{tmp_path / "st"}"

[mix]
decrypt = "all"
mvmx_secret = "{valid_secret}"

[profiles.default]
layers = []

[profiles.raw]
layers = []

[profiles.raw.mix]
decrypt = "patched"
""",
        encoding="utf-8",
    )
    loaded = load_config(cfg_path)
    default_prof = resolve_profile(loaded, config_dir=tmp_path)
    assert default_prof.mix.decrypt is MIXDecryptMode.ALL
    assert default_prof.mix.mvmx_secret == valid_secret

    raw_prof = resolve_profile(loaded, config_dir=tmp_path, profile_name="raw")
    assert raw_prof.mix.decrypt is MIXDecryptMode.PATCHED
    assert raw_prof.mix.mvmx_secret == valid_secret

    bad_cfg = tmp_path / "bad.toml"
    bad_cfg.write_text('[mix]\nmvmx_secret = "short"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="64 hex characters"):
        load_config(bad_cfg)
