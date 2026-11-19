"""Tests for Mental Omega environment and overlay diagnostics."""

import sys
lazy from pathlib import Path

lazy import pytest

from mentara.config import (
    BackendKind,
    MentaraConfig,
    ProfileConfig,
    RunnerConfig,
    RunnerOverrideConfig,
    resolve_profile,
)
from mentara.doctor import Severity, run_doctor

_REQUIRED = (
    "gamemd.exe",
    "Syringe.exe",
    "MentalOmegaClient.exe",
    "Ares.dll",
    "BINKW32.DLL",
    "Blowfish.dll",
    "ra2.mix",
    "ra2md.mix",
    "language.mix",
    "langmd.mix",
)


def _populate_base(base_dir: Path) -> None:
    (base_dir / "Resources").mkdir(parents=True)
    for filename in _REQUIRED:
        (base_dir / filename).write_bytes(b"stub")
    (base_dir / "Resources" / "ClientDefinitions.ini").write_text(
        "[Settings]\nForbiddenFiles=rulesmo.ini,artmo.ini\n",
        encoding="utf-8",
    )


def test_doctor_reports_healthy_profile(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    _populate_base(base_dir)
    layer_dir.mkdir()
    (layer_dir / "ddraw.ini").write_text("[ddraw]\n", encoding="utf-8")

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerConfig(command=(sys.executable,)),
        profiles={"default": ProfileConfig(layers=(str(layer_dir),))},
    )
    profile = resolve_profile(config, config_dir=tmp_path)

    report = run_doctor(profile)
    assert not report.has_errors
    assert not report.has_warnings


def test_doctor_warns_on_forbidden_files_and_clears_for_syringe(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    _populate_base(base_dir)
    layer_dir.mkdir()
    (layer_dir / "rulesmo.ini").write_text("[General]\n", encoding="utf-8")

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerConfig(command=(sys.executable,)),
        profiles={
            "client": ProfileConfig(layers=(str(layer_dir),)),
            "syringe": ProfileConfig(
                layers=(str(layer_dir),),
                runner=RunnerOverrideConfig(executable="Syringe.exe"),
            ),
        },
        default_profile="client",
    )

    client_report = run_doctor(
        resolve_profile(config, config_dir=tmp_path, profile_name="client"),
    )
    forbidden = [
        item for item in client_report.diagnostics if item.check == "forbidden-files"
    ]
    assert len(forbidden) == 1
    assert forbidden[0].severity is Severity.WARN
    assert "rulesmo.ini" in forbidden[0].message

    syringe_report = run_doctor(
        resolve_profile(config, config_dir=tmp_path, profile_name="syringe"),
    )
    assert not any(
        item.check == "forbidden-files" for item in syringe_report.diagnostics
    )


def test_doctor_warns_on_case_collision_and_errors_on_missing_exe(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    base_dir.mkdir()
    layer_dir.mkdir()
    (base_dir / "RA2MO.ini").write_text("base", encoding="utf-8")
    (layer_dir / "ra2mo.ini").write_text("layer", encoding="utf-8")

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerConfig(command=(sys.executable,)),
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


def test_doctor_checks_fuse_backend_tools(
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
        runner=RunnerConfig(command=(sys.executable,)),
    )
    profile = resolve_profile(config, config_dir=tmp_path)

    monkeypatch.setattr("mentara.doctor.shutil.which", lambda _name: None)
    missing_report = run_doctor(profile)
    assert missing_report.has_errors
    assert any(
        item.check == "backend" and "fuse-overlayfs" in item.message
        for item in missing_report.diagnostics
    )

    monkeypatch.setattr(
        "mentara.doctor.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    ready_report = run_doctor(profile)
    assert not ready_report.has_errors
