"""Tests for symlink/hardlink staging and fuse-overlayfs backends."""

import subprocess
from pathlib import Path

import pytest

from mentara.config import (
    BackendKind,
    MentaraConfig,
    PlatformKind,
    ProfileConfig,
    ResolvedProfile,
    resolve_profile,
)
from mentara.errors import MountError, OverlayError
from mentara.overlay import (
    FuseOverlayBackend,
    SymlinkStagingBackend,
    activate_workspace,
)


def _make_profile(
    tmp_path: Path,
    *,
    backend: BackendKind,
    platform: PlatformKind = PlatformKind.LINUX,
    persist_state: bool = True,
) -> ResolvedProfile:
    base_dir = tmp_path / "Mental Omega"
    layer_a = tmp_path / "overlays" / "a"
    layer_b = tmp_path / "overlays" / "b"
    (base_dir / "INI").mkdir(parents=True)
    (base_dir / "Saved Games").mkdir(parents=True)
    (base_dir / "ra2.mix").write_bytes(b"original-mix")
    (base_dir / "Ares.dll").write_bytes(b"base-ares")
    (base_dir / "RA2MO.ini").write_text("Speed=1\n", encoding="utf-8")
    (base_dir / "INI" / "base.ini").write_text("base-ini\n", encoding="utf-8")

    (layer_a / "INI").mkdir(parents=True)
    (layer_a / "Ares.dll").write_bytes(b"layer-a-ares")
    (layer_a / "INI" / "extra.ini").write_text("extra\n", encoding="utf-8")

    layer_b.mkdir(parents=True)
    (layer_b / "Phobos.dll").write_bytes(b"phobos-dll")

    config = MentaraConfig(
        base_dir=str(base_dir),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=str(tmp_path / "state"),
        backend=backend,
        profiles={
            "test": ProfileConfig(
                layers=(str(layer_a), str(layer_b)),
                persist_state=persist_state,
            ),
        },
        default_profile="test",
    )
    return resolve_profile(config, config_dir=tmp_path, platform=platform)


def test_symlink_backend_decouples_writes_and_persists_state(
    tmp_path: Path,
) -> None:
    profile = _make_profile(tmp_path, backend=BackendKind.SYMLINK)
    backend = SymlinkStagingBackend()

    workspace = backend.mount(profile)
    assert backend.is_mounted(profile)
    merged = workspace.merged_dir

    # Read-only asset is symlinked; INI is copied to isolate writes.
    assert (merged / "ra2.mix").is_symlink()
    assert (merged / "Ares.dll").is_symlink()
    assert (merged / "Ares.dll").read_bytes() == b"layer-a-ares"
    assert (merged / "Phobos.dll").read_bytes() == b"phobos-dll"
    assert not (merged / "RA2MO.ini").is_symlink()
    assert (merged / "INI" / "base.ini").exists()
    assert (merged / "INI" / "extra.ini").exists()

    # Simulate game editing INI, saving a file, and replacing a DLL.
    (merged / "RA2MO.ini").write_text("Speed=6\n", encoding="utf-8")
    (merged / "Saved Games" / "slot1.sav").write_bytes(b"save-bytes")
    (merged / "Phobos.dll").unlink()
    (merged / "Phobos.dll").write_bytes(b"hotpatched-dll")

    # Original base and overlay files remain untouched.
    assert (profile.base_dir / "RA2MO.ini").read_text(encoding="utf-8") == "Speed=1\n"
    assert not (profile.base_dir / "Saved Games" / "slot1.sav").exists()

    backend.unmount(profile, workspace)
    assert not backend.is_mounted(profile)
    assert not merged.exists()

    # Remounting replays persisted state from state/upper.
    workspace_two = backend.mount(profile)
    try:
        assert (workspace_two.merged_dir / "RA2MO.ini").read_text(
            encoding="utf-8"
        ) == "Speed=6\n"
        assert (
            workspace_two.merged_dir / "Saved Games" / "slot1.sav"
        ).read_bytes() == b"save-bytes"
        assert (
            workspace_two.merged_dir / "Phobos.dll"
        ).read_bytes() == b"hotpatched-dll"
    finally:
        backend.unmount(profile, workspace_two)


def test_symlink_backend_windows_hardlink_fallback_skips_untouched_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _make_profile(
        tmp_path,
        backend=BackendKind.SYMLINK,
        platform=PlatformKind.WINDOWS,
    )
    backend = SymlinkStagingBackend()

    def _deny_symlink(_self: Path, _target: Path) -> None:
        msg = "WinError 1314: symlink privilege not held"
        raise OSError(msg)

    monkeypatch.setattr(Path, "symlink_to", _deny_symlink)

    workspace = backend.mount(profile)
    merged = workspace.merged_dir
    assert not (merged / "ra2.mix").is_symlink()
    assert (merged / "ra2.mix").stat().st_nlink > 1

    (merged / "RA2MO.ini").write_text("Speed=9\n", encoding="utf-8")
    backend.unmount(profile, workspace)

    # Hardlinked read-only assets must NOT be copied into state/upper.
    upper = profile.state_dir / "upper"
    assert (upper / "RA2MO.ini").read_text(encoding="utf-8") == "Speed=9\n"
    assert not (upper / "ra2.mix").exists()
    assert not (upper / "Ares.dll").exists()


def test_symlink_backend_ephemeral_discards_writes(tmp_path: Path) -> None:
    profile = _make_profile(
        tmp_path,
        backend=BackendKind.SYMLINK,
        persist_state=False,
    )
    with activate_workspace(profile) as workspace:
        (workspace.merged_dir / "RA2MO.ini").write_text(
            "Temporary=yes\n",
            encoding="utf-8",
        )

    assert not (profile.state_dir / "upper").exists()
    assert (profile.base_dir / "RA2MO.ini").read_text(encoding="utf-8") == "Speed=1\n"


def test_activate_workspace_unmounts_even_on_exception(tmp_path: Path) -> None:
    profile = _make_profile(tmp_path, backend=BackendKind.SYMLINK)
    backend = SymlinkStagingBackend()

    def _run_failing_session() -> None:
        with activate_workspace(profile) as workspace:
            assert workspace.merged_dir.is_dir()
            msg = "boom"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="boom"):
        _run_failing_session()

    assert not backend.is_mounted(profile)


def test_symlink_backend_rejects_already_active_and_non_empty(
    tmp_path: Path,
) -> None:
    profile = _make_profile(tmp_path, backend=BackendKind.SYMLINK)
    backend = SymlinkStagingBackend()

    merged = profile.runtime_dir / "merged"
    merged.mkdir(parents=True)
    (merged / "stray.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(OverlayError, match="already contains files"):
        backend.mount(profile)

    (merged / "stray.txt").unlink()
    workspace = backend.mount(profile)
    try:
        with pytest.raises(OverlayError, match="already active"):
            backend.mount(profile)
    finally:
        backend.unmount(profile, workspace)

    with pytest.raises(OverlayError, match="No active virtual workspace"):
        backend.unmount(profile)


def test_fuse_backend_rejects_windows_platform(tmp_path: Path) -> None:
    profile = _make_profile(
        tmp_path,
        backend=BackendKind.FUSE_OVERLAYFS,
        platform=PlatformKind.WINDOWS,
    )
    backend = FuseOverlayBackend()

    with pytest.raises(MountError, match="not supported on platform 'windows'"):
        backend.mount(profile)


def test_fuse_backend_builds_reversed_lowerdir_and_unmounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _make_profile(tmp_path, backend=BackendKind.FUSE_OVERLAYFS)
    backend = FuseOverlayBackend()
    calls: list[tuple[str, ...]] = []
    mounted = False

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"fuse-overlayfs", "fusermount3"} else None

    def fake_run(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal mounted
        calls.append(command)
        if command[0].endswith("fuse-overlayfs"):
            mounted = True
            return subprocess.CompletedProcess(command, 0, "", "")
        if len(calls) == 2:
            return subprocess.CompletedProcess(command, 1, "", "Device busy")
        mounted = False
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("mentara.overlay.shutil.which", fake_which)
    monkeypatch.setattr("mentara.overlay.subprocess.run", fake_run)
    monkeypatch.setattr("mentara.overlay._is_mountpoint", lambda _p: mounted)
    monkeypatch.setattr("mentara.overlay.time.sleep", lambda _s: None)

    workspace = backend.mount(profile)
    assert backend.is_mounted(profile)
    mount_cmd = calls[0]
    assert mount_cmd[0] == "/usr/bin/fuse-overlayfs"
    expected_lower = (
        f"lowerdir={profile.layers[1]}:{profile.layers[0]}:{profile.base_dir},"
        f"upperdir={profile.state_dir / 'upper'},"
        f"workdir={profile.state_dir / 'work'}"
    )
    assert mount_cmd[2] == expected_lower

    backend.unmount(profile, workspace)
    assert not backend.is_mounted(profile)
    assert len(calls) == 3

    mounted = True
    backend.unmount(profile, workspace, lazy=True)
    assert calls[-1][1] == "-uz"


def test_fuse_backend_errors_when_tool_missing_or_mount_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _make_profile(
        tmp_path,
        backend=BackendKind.FUSE_OVERLAYFS,
        persist_state=False,
    )
    backend = FuseOverlayBackend()

    monkeypatch.setattr("mentara.overlay.shutil.which", lambda _n: None)
    with pytest.raises(MountError, match="fuse-overlayfs"):
        backend.mount(profile)

    monkeypatch.setattr(
        "mentara.overlay.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        "mentara.overlay.subprocess.run",
        lambda cmd, **_kw: subprocess.CompletedProcess(
            cmd,
            1,
            "",
            "fuse: failed to open /dev/fuse",
        ),
    )
    with pytest.raises(MountError, match="failed to open /dev/fuse"):
        backend.mount(profile)
    assert not (profile.runtime_dir / "ephemeral").exists()


def test_symlink_backend_rejects_corrupt_manifest(tmp_path: Path) -> None:
    profile = _make_profile(tmp_path, backend=BackendKind.SYMLINK)
    backend = SymlinkStagingBackend()
    profile.runtime_dir.mkdir(parents=True)
    manifest = profile.runtime_dir / ".mentara-staged.json"
    manifest.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(OverlayError, match="Corrupt staging manifest"):
        backend.unmount(profile)

    manifest.write_text('{"persist_state": "nope"}', encoding="utf-8")
    with pytest.raises(OverlayError, match="invalid schema"):
        backend.unmount(profile)
