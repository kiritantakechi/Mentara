"""Tests for runner command assembly, wrapper chains, and execution."""

import sys
lazy from pathlib import Path

import pytest

from mentara.config import (
    BackendKind,
    MentaraConfig,
    ProfileConfig,
    RunnerConfig,
    resolve_profile,
)
from mentara.errors import RunnerError
from mentara.overlay import MountedWorkspace, activate_workspace
from mentara.runner import (
    build_launch_spec,
    execute_launch,
    extract_command_binaries,
)


def test_extract_command_binaries_handles_direct_and_chained_wrappers() -> None:
    assert extract_command_binaries(()) == ()
    assert extract_command_binaries(("umu-run",)) == ("umu-run",)
    assert extract_command_binaries(
        ("gamescope", "-W", "2560", "-H", "1440", "-f", "--", "umu-run")
    ) == ("gamescope", "umu-run")
    assert extract_command_binaries(
        ("mangohud", "--", "gamescope", "-f", "--", "wine")
    ) == ("mangohud", "gamescope", "wine")


def test_build_launch_spec_expands_templates_and_injects_mentara_env(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        runner=RunnerConfig(
            command=("gamescope", "-f", "--", "umu-run"),
            executable="MentalOmegaClient.exe",
            args=("-CD",),
            env={
                "WINEDLLOVERRIDES": "ddraw=n,b",
                "CUSTOM_PATH": "$MERGED_DIR/INI",
                "HOME_PREFIX": "~/prefixes/mo",
            },
        ),
        profiles={"default": ProfileConfig()},
    )
    profile = resolve_profile(config, config_dir=tmp_path)
    workspace = MountedWorkspace(
        profile_name="default",
        backend=BackendKind.SYMLINK,
        merged_dir=profile.runtime_dir / "merged",
        upper_dir=profile.state_dir / "upper",
        base_dir=profile.base_dir,
        layers=(),
    )

    spec = build_launch_spec(
        profile,
        workspace,
        base_env={"PATH": "/usr/bin"},
    )

    assert spec.argv == (
        "gamescope",
        "-f",
        "--",
        "umu-run",
        str(workspace.merged_dir / "MentalOmegaClient.exe"),
        "-CD",
    )
    assert spec.required_binaries == ("gamescope", "umu-run")
    assert spec.cwd == workspace.merged_dir
    assert spec.env["WINEDLLOVERRIDES"] == "ddraw=n,b"
    assert spec.env["CUSTOM_PATH"] == f"{workspace.merged_dir}/INI"
    assert spec.env["HOME_PREFIX"] == str(Path.home() / "prefixes" / "mo")
    assert spec.env["MENTARA_PROFILE"] == "default"
    assert spec.env["MENTARA_MERGED_DIR"] == str(workspace.merged_dir)


def test_execute_launch_runs_script_in_virtual_workspace(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    base_dir.mkdir()
    layer_dir.mkdir()
    (base_dir / "RA2MO.ini").write_text("from-base\n", encoding="utf-8")
    (layer_dir / "RA2MO.ini").write_text("from-layer\n", encoding="utf-8")

    script = base_dir / "mock_game.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "ini = Path('RA2MO.ini').read_text(encoding='utf-8').strip()\n"
        "Path('output.sav').write_text(ini + ':' + sys.argv[1], encoding='utf-8')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerConfig(
            command=(sys.executable,),
            executable="mock_game.py",
            args=("ok",),
        ),
        profiles={"default": ProfileConfig(layers=(str(layer_dir),))},
    )
    profile = resolve_profile(config, config_dir=tmp_path)

    with activate_workspace(profile) as workspace:
        spec = build_launch_spec(profile, workspace)
        result = execute_launch(spec)

    assert result.returncode == 7
    persisted = profile.state_dir / "upper" / "output.sav"
    assert persisted.read_text(encoding="utf-8") == "from-layer:ok"
    assert not (base_dir / "output.sav").exists()


def test_execute_launch_errors_on_missing_executable_or_chained_runner(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerConfig(
            command=(sys.executable, "--", "missing-second-stage-binary"),
            executable="MentalOmegaClient.exe",
        ),
    )
    profile = resolve_profile(config, config_dir=tmp_path)

    with activate_workspace(profile) as workspace:
        spec = build_launch_spec(profile, workspace)
        with pytest.raises(RunnerError, match="Target executable not found"):
            execute_launch(spec)

    (base_dir / "MentalOmegaClient.exe").write_bytes(b"exe")
    with activate_workspace(profile) as workspace:
        spec = build_launch_spec(profile, workspace)
        with pytest.raises(RunnerError, match="missing-second-stage-binary"):
            execute_launch(spec)
