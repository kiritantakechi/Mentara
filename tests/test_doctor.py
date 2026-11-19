"""Tests for cross-platform virtual overlay and runner diagnostics."""

import sys
lazy from pathlib import Path

lazy import pytest

from mentara.config import (
    BackendKind,
    MentaraConfig,
    PlatformKind,
    ProfileConfig,
    RunnerConfig,
    resolve_profile,
)
from mentara.doctor import Severity, run_doctor


def _populate_base(base_dir: Path) -> None:
    base_dir.mkdir(parents=True)
    (base_dir / "app.exe").write_bytes(b"stub")
    (base_dir / "settings.ini").write_text("[General]\nKey=1\n", encoding="utf-8")


def test_doctor_reports_healthy_linux_and_windows_profiles(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    _populate_base(base_dir)
    layer_dir.mkdir()
    (layer_dir / "settings.patch.ini").write_text(
        "[General]\nKey=2\n",
        encoding="utf-8",
    )

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerConfig(
            command=(sys.executable,),
            executable="app.exe",
        ),
        profiles={"default": ProfileConfig(layers=(str(layer_dir),))},
    )

    for platform in (PlatformKind.LINUX, PlatformKind.WINDOWS):
        profile = resolve_profile(
            config,
            config_dir=tmp_path,
            platform=platform,
        )
        report = run_doctor(profile)
        assert not report.has_errors
        assert not report.has_warnings


def test_doctor_errors_when_windows_uses_fuse_backend(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    _populate_base(base_dir)
    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.FUSE_OVERLAYFS,
        runner=RunnerConfig(executable="app.exe"),
    )
    profile = resolve_profile(
        config,
        config_dir=tmp_path,
        platform=PlatformKind.WINDOWS,
    )
    report = run_doctor(profile)
    assert report.has_errors
    assert any(
        item.check == "backend" and item.severity is Severity.ERROR
        for item in report.diagnostics
    )


def test_doctor_warns_on_case_collision_and_errors_on_missing_exe(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    base_dir.mkdir()
    layer_dir.mkdir()
    (base_dir / "Config.ini").write_text("base", encoding="utf-8")
    (layer_dir / "config.ini").write_text("layer", encoding="utf-8")

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerConfig(
            command=(sys.executable,),
            executable="missing.exe",
        ),
        profiles={"default": ProfileConfig(layers=(str(layer_dir),))},
    )
    report = run_doctor(resolve_profile(config, config_dir=tmp_path))

    assert report.has_errors
    assert any(
        item.check == "executable" and item.severity is Severity.ERROR
        for item in report.diagnostics
    )
    assert any(
        item.check == "case-collisions" and item.severity is Severity.WARN
        for item in report.diagnostics
    )


def test_doctor_checks_fuse_backend_and_chained_runner_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = tmp_path / "base"
    _populate_base(base_dir)
    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.FUSE_OVERLAYFS,
        runner=RunnerConfig(
            command=("wrapper-a", "-f", "--", "wrapper-b"),
            executable="app.exe",
        ),
    )
    profile = resolve_profile(
        config,
        config_dir=tmp_path,
        platform=PlatformKind.LINUX,
    )

    monkeypatch.setattr(
        "mentara.doctor.shutil.which",
        lambda _name, **_kw: None,
    )
    monkeypatch.setattr(
        "mentara.runner.shutil.which",
        lambda _name, **_kw: None,
    )
    missing_report = run_doctor(profile)
    assert missing_report.has_errors
    assert any(
        item.check == "backend" and "fuse-overlayfs" in item.message
        for item in missing_report.diagnostics
    )
    assert any(
        item.check == "runner" and "wrapper-a" in item.message
        for item in missing_report.diagnostics
    )

    monkeypatch.setattr(
        "mentara.doctor.shutil.which",
        lambda name, **_kw: f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        "mentara.runner.shutil.which",
        lambda name, **_kw: f"/usr/bin/{name}",
    )
    ready_report = run_doctor(profile)
    assert not ready_report.has_errors
    assert any(
        item.check == "runner"
        and "/usr/bin/wrapper-a -> /usr/bin/wrapper-b" in item.message
        for item in ready_report.diagnostics
    )


def test_doctor_reports_malformed_patch_error(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    _populate_base(base_dir)
    layer_dir.mkdir()
    (layer_dir / "settings.patch.ini").write_text(
        "[General]\nInvalidLineWithoutEquals\n",
        encoding="utf-8",
    )

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerConfig(executable="app.exe"),
        profiles={"default": ProfileConfig(layers=(str(layer_dir),))},
    )
    report = run_doctor(resolve_profile(config, config_dir=tmp_path))
    assert report.has_errors
    assert any(
        item.check == "patches" and item.severity is Severity.ERROR
        for item in report.diagnostics
    )
