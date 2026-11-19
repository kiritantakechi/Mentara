"""End-to-end tests for the Mentara CLI commands."""

import io
import json
import sys
lazy from pathlib import Path

from mentara.cli import main


def _setup_project(tmp_path: Path) -> Path:
    base_dir = tmp_path / "game"
    project_dir = base_dir / "Mentara"
    layer_dir = project_dir / "overlays" / "custom"
    layer_dir.mkdir(parents=True)

    (base_dir / "RA2MO.ini").write_text("Speed=1\n", encoding="utf-8")
    (base_dir / "ddraw.dll").write_bytes(b"base-ddraw")
    (base_dir / "mock.py").write_text(
        "from pathlib import Path\n"
        "Path('ran.log').write_text("
        "Path('ddraw.dll').read_bytes().decode('utf-8'), encoding='utf-8')\n",
        encoding="utf-8",
    )
    (layer_dir / "ddraw.dll").write_bytes(b"custom-ddraw")
    (layer_dir / "ddraw.ini").write_text("[ddraw]\n", encoding="utf-8")

    config_path = project_dir / "mentara.toml"
    config_path.write_text(
        f"""
base_dir = ".."
runtime_dir = "{tmp_path / "runtime"}"
state_dir = "{tmp_path / "state"}"
default_profile = "default"
backend = "symlink"

[runner]
command = ["{sys.executable}"]
executable = "mock.py"

[profiles.default]
description = "Test profile"
layers = ["overlays/custom"]
""",
        encoding="utf-8",
    )
    return config_path


def test_cli_profiles_inspect_and_dry_run(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)

    out = io.StringIO()
    err = io.StringIO()
    assert main(["-c", str(config_path), "profiles"], stdout=out, stderr=err) == 0
    assert "* default [" in out.getvalue()
    assert ":symlink]" in out.getvalue()

    out = io.StringIO()
    assert (
        main(
            [
                "-c",
                str(config_path),
                "inspect",
                "--filter",
                "*.dll",
                "--json",
            ],
            stdout=out,
            stderr=err,
        )
        == 0
    )
    payload = json.loads(out.getvalue())
    assert payload["profile"] == "default"
    assert [item["path"] for item in payload["entries"]] == ["ddraw.dll"]
    assert payload["entries"][0]["shadowed_from"] == ["base"]

    out = io.StringIO()
    assert (
        main(
            ["-c", str(config_path), "launch", "--dry-run"],
            stdout=out,
            stderr=err,
        )
        == 0
    )
    assert "Platform:" in out.getvalue()
    assert "Command:" in out.getvalue()
    assert "mock.py" in out.getvalue()


def test_cli_mount_unmount_launch_and_init_layer(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)

    out = io.StringIO()
    err = io.StringIO()
    assert (
        main(
            ["-c", str(config_path), "init-layer", "phobos"],
            stdout=out,
            stderr=err,
        )
        == 0
    )
    assert (config_path.parent / "overlays" / "phobos" / ".gitkeep").is_file()

    # Manual mount and unmount round-trip.
    out = io.StringIO()
    assert main(["-c", str(config_path), "mount"], stdout=out, stderr=err) == 0
    merged = tmp_path / "runtime" / "default" / "merged"
    assert (merged / "ddraw.dll").read_bytes() == b"custom-ddraw"

    out = io.StringIO()
    assert main(["-c", str(config_path), "unmount"], stdout=out, stderr=err) == 0
    assert not merged.exists()

    # Full launch lifecycle: mount, read overlay DLL, persist log.
    out = io.StringIO()
    assert main(["-c", str(config_path), "launch"], stdout=out, stderr=err) == 0
    assert not merged.exists()
    persisted = tmp_path / "state" / "default" / "upper" / "ran.log"
    assert persisted.read_text(encoding="utf-8") == "custom-ddraw"


def test_cli_returns_nonzero_on_unknown_profile(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)
    out = io.StringIO()
    err = io.StringIO()

    code = main(
        ["-c", str(config_path), "inspect", "--profile", "nope"],
        stdout=out,
        stderr=err,
    )
    assert code == 1
    assert "Unknown profile 'nope'" in err.getvalue()


def test_cli_inspect_text_and_doctor(tmp_path: Path) -> None:
    config_path = _setup_project(tmp_path)

    out = io.StringIO()
    err = io.StringIO()
    assert (
        main(
            ["-c", str(config_path), "inspect", "--filter", "*.ini"],
            stdout=out,
            stderr=err,
        )
        == 0
    )
    assert "ddraw.ini" in out.getvalue()
    assert "ddraw.dll" not in out.getvalue()

    out = io.StringIO()
    err = io.StringIO()
    assert main(["-c", str(config_path), "doctor"], stdout=out, stderr=err) == 0
    assert "Doctor report for profile 'default'" in out.getvalue()

    out = io.StringIO()
    err = io.StringIO()
    assert (
        main(
            ["-c", str(config_path), "launch", "--dry-run", "-v"],
            stdout=out,
            stderr=err,
        )
        == 0
    )
    assert "Command:" in out.getvalue()
