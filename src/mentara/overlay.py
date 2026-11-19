"""Virtual workspace mounting, symlink staging, and teardown."""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
lazy from collections.abc import Generator, Mapping

from mentara.config import BackendKind, ResolvedProfile
from mentara.errors import MountError, OverlayError
from mentara.planner import (
    EntryOrigin,
    LayerSource,
    Materialization,
    OverlayPlan,
    build_overlay_plan,
)

__all__ = [
    "FuseOverlayBackend",
    "MountedWorkspace",
    "OverlayBackend",
    "SymlinkStagingBackend",
    "activate_workspace",
    "get_backend",
    "plan_profile",
    "profile_sources",
]

_LOGGER = logging.getLogger(__name__)
_MANIFEST_FILENAME = ".mentara-staged.json"
_MERGED_DIRNAME = "merged"
_EPHEMERAL_DIRNAME = "ephemeral"
_UPPER_DIRNAME = "upper"
_WORK_DIRNAME = "work"
_UNMOUNT_ATTEMPTS = 5
_UNMOUNT_RETRY_DELAY_SECONDS = 0.25
_HASH_CHUNK_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class MountedWorkspace:
    """Active virtual Mental Omega directory backed by an overlay."""

    profile_name: str
    backend: BackendKind
    merged_dir: Path
    upper_dir: Path | None
    base_dir: Path
    layers: tuple[Path, ...]
    ephemeral_root: Path | None = None


class OverlayBackend(Protocol):
    """Contract shared by every virtual directory backend."""

    kind: BackendKind

    def mount(self, profile: ResolvedProfile) -> MountedWorkspace:
        """Materialise or mount the virtual directory for `profile`.

        Args:
            profile: Resolved launcher profile.

        Returns:
            Metadata describing the active workspace.
        """
        ...

    def unmount(
        self,
        profile: ResolvedProfile,
        workspace: MountedWorkspace | None = None,
    ) -> None:
        """Tear down an active virtual workspace for `profile`.

        Args:
            profile: Resolved launcher profile.
            workspace: Workspace returned by `mount`, if known.
        """
        ...

    def is_mounted(self, profile: ResolvedProfile) -> bool:
        """Return whether a virtual workspace is active for `profile`.

        Args:
            profile: Resolved launcher profile.

        Returns:
            `True` when mounted or staged, otherwise `False`.
        """
        ...


class FuseOverlayBackend:
    """Zero-copy rootless union mount powered by `fuse-overlayfs`."""

    kind: BackendKind = BackendKind.FUSE_OVERLAYFS

    def mount(self, profile: ResolvedProfile) -> MountedWorkspace:
        """Mount `base_dir`, overlay layers, and upperdir via FUSE.

        Args:
            profile: Resolved launcher profile.

        Returns:
            A `MountedWorkspace` pointing at the mounted `merged` dir.

        Raises:
            MountError: If FUSE binaries are missing or mounting fails.
            OverlayError: If source directories are missing or target is
                busy or non-empty.
        """
        _validate_source_directories(profile)
        fuse_bin = _require_tool("fuse-overlayfs")
        merged_dir = _merged_dir_for(profile)

        if self.is_mounted(profile):
            raise OverlayError.already_active(merged_dir)
        _ensure_empty_directory(merged_dir)

        upper_dir, work_dir, ephemeral_root = _prepare_fuse_dirs(profile)
        lower_dirs = (*reversed(profile.layers), profile.base_dir)
        lower_opt = ":".join(_escape_overlay_opt(path) for path in lower_dirs)
        upper_opt = _escape_overlay_opt(upper_dir)
        work_opt = _escape_overlay_opt(work_dir)

        command = (
            fuse_bin,
            "-o",
            f"lowerdir={lower_opt},upperdir={upper_opt},workdir={work_opt}",
            str(merged_dir),
        )
        _LOGGER.debug("Mounting fuse-overlayfs: %s", command)
        result = subprocess.run(  # noqa: S603 - fixed binary from shutil.which
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            if ephemeral_root is not None:
                shutil.rmtree(ephemeral_root, ignore_errors=True)
            raise MountError.command_failed(
                command,
                result.returncode,
                result.stderr,
            )

        return MountedWorkspace(
            profile_name=profile.name,
            backend=self.kind,
            merged_dir=merged_dir,
            upper_dir=upper_dir if profile.persist_state else None,
            base_dir=profile.base_dir,
            layers=profile.layers,
            ephemeral_root=ephemeral_root,
        )

    def unmount(
        self,
        profile: ResolvedProfile,
        workspace: MountedWorkspace | None = None,
    ) -> None:
        """Unmount the FUSE overlay and clean up ephemeral dirs.

        Args:
            profile: Resolved launcher profile.
            workspace: Workspace returned by `mount`, if available.

        Raises:
            MountError: If `fusermount3`/`fusermount` fails or is
                absent.
            OverlayError: If no mount is active when called directly.
        """
        merged_dir = (
            workspace.merged_dir if workspace is not None else _merged_dir_for(profile)
        )
        ephemeral_root = (
            workspace.ephemeral_root
            if workspace is not None
            else profile.runtime_dir / _EPHEMERAL_DIRNAME
        )

        if not _is_mountpoint(merged_dir):
            if workspace is None:
                raise OverlayError.not_active(merged_dir)
            _cleanup_fuse_dirs(merged_dir, ephemeral_root)
            return

        unmount_bin = _find_unmount_tool()
        command = (unmount_bin, "-u", str(merged_dir))

        for attempt in range(1, _UNMOUNT_ATTEMPTS + 1):
            result = subprocess.run(  # noqa: S603 - fixed fusermount binary
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if result.returncode == 0:
                _cleanup_fuse_dirs(merged_dir, ephemeral_root)
                return
            _LOGGER.debug(
                "Unmount attempt %d/%d failed for %s: %s",
                attempt,
                _UNMOUNT_ATTEMPTS,
                merged_dir,
                result.stderr.strip(),
            )
            if attempt == _UNMOUNT_ATTEMPTS:
                raise MountError.command_failed(
                    command,
                    result.returncode,
                    result.stderr,
                )
            time.sleep(_UNMOUNT_RETRY_DELAY_SECONDS)

    def is_mounted(self, profile: ResolvedProfile) -> bool:
        """Return whether the FUSE mountpoint for `profile` is active.

        Args:
            profile: Resolved launcher profile.

        Returns:
            `True` if `merged` is an active mountpoint.
        """
        return _is_mountpoint(_merged_dir_for(profile))


class SymlinkStagingBackend:
    """Shadow directory tree using symlinks and isolated copies."""

    kind: BackendKind = BackendKind.SYMLINK

    def mount(self, profile: ResolvedProfile) -> MountedWorkspace:
        """Build a staged virtual directory tree for `profile`.

        Args:
            profile: Resolved launcher profile.

        Returns:
            A `MountedWorkspace` pointing at the staged `merged` dir.

        Raises:
            OverlayError: If already active, target non-empty, or source
                directories are missing.
        """
        _validate_source_directories(profile)
        merged_dir = _merged_dir_for(profile)
        manifest_path = _manifest_path_for(profile)

        if self.is_mounted(profile):
            raise OverlayError.already_active(merged_dir)
        _ensure_empty_directory(merged_dir)

        plan = plan_profile(profile)
        upper_dir = (
            profile.state_dir / _UPPER_DIRNAME if profile.persist_state else None
        )
        copied_hashes: dict[str, str] = {}
        symlinked_files: list[str] = []

        try:
            for rel_dir in plan.directories:
                (merged_dir / rel_dir).mkdir(parents=True, exist_ok=True)

            for entry in plan.entries:
                target = merged_dir / entry.relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                rel_posix = entry.relative_path.as_posix()
                if entry.materialization is Materialization.COPY:
                    shutil.copy2(entry.source_path, target)
                    copied_hashes[rel_posix] = _sha256_file(target)
                else:
                    target.symlink_to(entry.source_path)
                    symlinked_files.append(rel_posix)

            manifest_payload: dict[str, object] = {
                "profile_name": profile.name,
                "backend": self.kind.value,
                "persist_state": profile.persist_state,
                "upper_dir": str(upper_dir) if upper_dir is not None else None,
                "copied_hashes": copied_hashes,
                "symlinked_files": symlinked_files,
            }
            _write_json_atomic(manifest_path, manifest_payload)
        except Exception:
            shutil.rmtree(merged_dir, ignore_errors=True)
            manifest_path.unlink(missing_ok=True)
            raise

        return MountedWorkspace(
            profile_name=profile.name,
            backend=self.kind,
            merged_dir=merged_dir,
            upper_dir=upper_dir,
            base_dir=profile.base_dir,
            layers=profile.layers,
        )

    def unmount(
        self,
        profile: ResolvedProfile,
        workspace: MountedWorkspace | None = None,
    ) -> None:
        """Sync changed writable files to state and remove staged tree.

        Args:
            profile: Resolved launcher profile.
            workspace: Workspace returned by `mount`, if available.

        Raises:
            OverlayError: If no active staged workspace exists or the
                manifest is corrupt.
        """
        merged_dir = (
            workspace.merged_dir if workspace is not None else _merged_dir_for(profile)
        )
        manifest_path = _manifest_path_for(profile)

        if not manifest_path.is_file():
            if workspace is None:
                raise OverlayError.not_active(merged_dir)
            shutil.rmtree(merged_dir, ignore_errors=True)
            return

        manifest = _read_staging_manifest(manifest_path)
        if manifest.persist_state and manifest.upper_dir is not None:
            _sync_staged_changes(
                merged_dir=merged_dir,
                upper_dir=manifest.upper_dir,
                copied_hashes=manifest.copied_hashes,
            )

        if merged_dir.exists():
            shutil.rmtree(merged_dir)
        manifest_path.unlink(missing_ok=True)

    def is_mounted(self, profile: ResolvedProfile) -> bool:
        """Return whether a staged symlink tree is active for `profile`.

        Args:
            profile: Resolved launcher profile.

        Returns:
            `True` when the staging manifest and merged directory exist.
        """
        return (
            _manifest_path_for(profile).is_file() and _merged_dir_for(profile).is_dir()
        )


def get_backend(kind: BackendKind) -> OverlayBackend:
    """Return the backend implementation for `kind`.

    Args:
        kind: Requested backend enum value.

    Returns:
        An `OverlayBackend` instance matching `kind`.
    """
    match kind:
        case BackendKind.FUSE_OVERLAYFS:
            return FuseOverlayBackend()
        case BackendKind.SYMLINK:
            return SymlinkStagingBackend()


def profile_sources(
    profile: ResolvedProfile,
    *,
    include_state: bool = True,
) -> tuple[LayerSource, ...]:
    """Build ordered `LayerSource` entries for `profile`.

    Args:
        profile: Resolved launcher profile.
        include_state: Whether to include persistent `state_dir/upper`
            as the top read layer when `persist_state` is enabled.

    Returns:
        Bottom-to-top tuple of `LayerSource` values.
    """
    sources: list[LayerSource] = [
        LayerSource(
            label="base",
            root=profile.base_dir,
            origin=EntryOrigin.BASE,
            exclude=profile.exclude,
            required=True,
        ),
    ]
    sources.extend(
        LayerSource(
            label=_format_layer_label(layer, anchor=profile.config_dir),
            root=layer,
            origin=EntryOrigin.LAYER,
            exclude=profile.exclude,
            required=True,
        )
        for layer in profile.layers
    )
    if include_state and profile.persist_state:
        sources.append(
            LayerSource(
                label="state",
                root=profile.state_dir / _UPPER_DIRNAME,
                origin=EntryOrigin.STATE,
                exclude=(),
                required=False,
            ),
        )
    return tuple(sources)


def plan_profile(
    profile: ResolvedProfile,
    *,
    include_state: bool = True,
) -> OverlayPlan:
    """Compute the pure `OverlayPlan` for `profile` with no I/O writes.

    Args:
        profile: Resolved launcher profile.
        include_state: Whether to include persisted writable state.

    Returns:
        Resolved `OverlayPlan`.
    """
    return build_overlay_plan(
        profile_sources(profile, include_state=include_state),
        copy_patterns=profile.copy_patterns,
    )


@contextmanager
def activate_workspace(
    profile: ResolvedProfile,
) -> Generator[MountedWorkspace]:
    """Mount or stage a profile workspace and tear it down on exit.

    Args:
        profile: Resolved launcher profile.

    Yields:
        Active `MountedWorkspace`.
    """
    backend = get_backend(profile.backend)
    workspace = backend.mount(profile)
    try:
        yield workspace
    finally:
        backend.unmount(profile, workspace)


@dataclass(frozen=True, slots=True)
class _StagingManifest:
    persist_state: bool
    upper_dir: Path | None
    copied_hashes: frozendict[str, str]


def _merged_dir_for(profile: ResolvedProfile) -> Path:
    return profile.runtime_dir / _MERGED_DIRNAME


def _manifest_path_for(profile: ResolvedProfile) -> Path:
    return profile.runtime_dir / _MANIFEST_FILENAME


def _format_layer_label(layer: Path, *, anchor: Path) -> str:
    if layer.is_relative_to(anchor):
        return f"layer:{layer.relative_to(anchor).as_posix()}"
    return f"layer:{layer}"


def _validate_source_directories(profile: ResolvedProfile) -> None:
    if not profile.base_dir.is_dir():
        role = "base_dir"
        raise OverlayError.missing_directory(role, profile.base_dir)
    layer_role = "overlay layer"
    for layer in profile.layers:
        if not layer.is_dir():
            raise OverlayError.missing_directory(layer_role, layer)


def _ensure_empty_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise OverlayError.non_empty_target(path)
        return
    path.mkdir(parents=True, exist_ok=True)


def _prepare_fuse_dirs(
    profile: ResolvedProfile,
) -> tuple[Path, Path, Path | None]:
    if profile.persist_state:
        upper_dir = profile.state_dir / _UPPER_DIRNAME
        work_dir = profile.state_dir / _WORK_DIRNAME
        ephemeral_root = None
    else:
        ephemeral_root = profile.runtime_dir / _EPHEMERAL_DIRNAME
        upper_dir = ephemeral_root / _UPPER_DIRNAME
        work_dir = ephemeral_root / _WORK_DIRNAME

    upper_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    return upper_dir, work_dir, ephemeral_root


def _cleanup_fuse_dirs(
    merged_dir: Path,
    ephemeral_root: Path | None,
) -> None:
    if ephemeral_root is not None and ephemeral_root.exists():
        shutil.rmtree(ephemeral_root, ignore_errors=True)
    with suppress(OSError):
        merged_dir.rmdir()


def _escape_overlay_opt(path: Path) -> str:
    text = str(path)
    return text.replace("\\", "\\\\").replace(":", "\\:").replace(",", "\\,")


def _require_tool(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise MountError.tool_missing(name)
    return resolved


def _find_unmount_tool() -> str:
    candidates = ("fusermount3", "fusermount")
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    raise MountError.tool_missing(candidates[0])


def _is_mountpoint(path: Path) -> bool:
    return path.exists() and path.is_mount()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2)
        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _read_staging_manifest(path: Path) -> _StagingManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverlayError.corrupt_manifest(path, str(exc)) from exc

    if not isinstance(raw, dict):
        raise OverlayError.invalid_manifest_schema(path)

    persist_state = raw.get("persist_state")
    upper_raw = raw.get("upper_dir")
    copied_raw = raw.get("copied_hashes")
    if not isinstance(persist_state, bool) or not isinstance(copied_raw, dict):
        raise OverlayError.invalid_manifest_schema(path)
    if upper_raw is not None and not isinstance(upper_raw, str):
        raise OverlayError.invalid_manifest_schema(path)

    copied_hashes: dict[str, str] = {}
    for key, value in copied_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise OverlayError.invalid_manifest_schema(path)
        copied_hashes[key] = value

    return _StagingManifest(
        persist_state=persist_state,
        upper_dir=Path(upper_raw) if upper_raw is not None else None,
        copied_hashes=frozendict(copied_hashes),
    )


def _sync_staged_changes(
    *,
    merged_dir: Path,
    upper_dir: Path,
    copied_hashes: frozendict[str, str],
) -> None:
    if not merged_dir.is_dir():
        return

    for dirpath, _dirnames, filenames in os.walk(merged_dir):
        current_dir = Path(dirpath)
        rel_dir = current_dir.relative_to(merged_dir)
        for filename in filenames:
            full_path = current_dir / filename
            if full_path.is_symlink() or not full_path.is_file():
                continue

            rel_path = Path(filename) if rel_dir == Path() else rel_dir / filename
            rel_posix = rel_path.as_posix()
            recorded_hash = copied_hashes.get(rel_posix)
            if recorded_hash is not None and _sha256_file(full_path) == recorded_hash:
                continue

            destination = upper_dir / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(full_path, destination)
            _LOGGER.debug("Persisted modified file to state: %s", rel_posix)
