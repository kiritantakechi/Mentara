"""Tests for cross-platform Mental Omega environment diagnostics."""

import sys
lazy from pathlib import Path

lazy import pytest

from mentara.config import (
    BackendKind,
    MentaraConfig,
    PlatformKind,
    ProfileConfig,
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


def test_doctor_reports_healthy_linux_and_windows_profiles(
    tmp_path: Path,
) -> None:
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
        runner=RunnerOverrideConfig(command=(sys.executable,)),
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
        runner=RunnerOverrideConfig(command=(sys.executable,)),
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
        runner=RunnerOverrideConfig(command=(sys.executable,)),
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
        runner=RunnerOverrideConfig(
            command=("gamescope", "-f", "--", "umu-run"),
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
    missing_report = run_doctor(profile)
    assert missing_report.has_errors
    assert any(
        item.check == "backend" and "fuse-overlayfs" in item.message
        for item in missing_report.diagnostics
    )
    assert any(
        item.check == "runner" and "gamescope" in item.message
        for item in missing_report.diagnostics
    )

    monkeypatch.setattr(
        "mentara.doctor.shutil.which",
        lambda name, **_kw: f"/usr/bin/{name}",
    )
    ready_report = run_doctor(profile)
    assert not ready_report.has_errors
    assert any(
        item.check == "runner"
        and "/usr/bin/gamescope -> /usr/bin/umu-run" in item.message
        for item in ready_report.diagnostics
    )


def test_doctor_checks_syringeex_client_definitions_migration(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "base"
    layer_dir = tmp_path / "layer"
    _populate_base(base_dir)
    (base_dir / "Resources" / "ClientDefinitions.ini").write_text(
        "[Settings]\n"
        "GameExecutableNames=gamemd.exe\n"
        "GameLauncherExecutableName=Syringe.exe\n"
        "ExtraCommandLineParams=-CD -LOG\n",
        encoding="utf-8",
    )
    layer_dir.mkdir()
    (layer_dir / "Syringe.exe").write_bytes(b"MZ...SyringeEx 0.1.0.2...")

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=BackendKind.SYMLINK,
        runner=RunnerOverrideConfig(command=(sys.executable,)),
        profiles={"default": ProfileConfig(layers=(str(layer_dir),))},
    )

    legacy_report = run_doctor(resolve_profile(config, config_dir=tmp_path))
    assert any(
        item.check == "syringeex-client-defs" and item.severity is Severity.WARN
        for item in legacy_report.diagnostics
    )

    (layer_dir / "Resources").mkdir()
    (layer_dir / "Resources" / "ClientDefinitions.ini").write_text(
        "[Settings]\n"
        "GameExecutableNames=Syringe.exe\n"
        "GameLauncherExecutableName=\n"
        'ExtraCommandLineParams=gamemd.exe --args="-SPAWN -CD -LOG"\n',
        encoding="utf-8",
    )
    migrated_report = run_doctor(resolve_profile(config, config_dir=tmp_path))
    assert any(
        item.check == "syringeex-client-defs" and item.severity is Severity.OK
        for item in migrated_report.diagnostics
    )
