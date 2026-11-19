"""Virtual workspace mounting, staging, and teardown across OSes."""

import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
import time
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

from mentara.config import BackendKind, PlatformKind, ResolvedProfile
from mentara.errors import MountError, OverlayError
from mentara.planner import (
    EntryOrigin,
    FileEntry,
    LayerSource,
    Materialization,
    OverlayPlan,
    build_overlay_plan,
    render_entry_text,
)

__all__ = [
    "FuseOverlayBackend",
    "MountedWorkspace",
    "OverlayBackend",
    "SymlinkStagingBackend",
    "activate_workspace",
    "clean_state",
    "get_backend",
    "plan_profile",
    "profile_sources",
]

_LOGGER = logging.getLogger(__name__)
_MANIFEST_FILENAME = ".mentara-staged.json"
_SYNTHESIZED_DIRNAME = "synthesized"
_EPHEMERAL_DIRNAME = "ephemeral"
_UPPER_DIRNAME = "upper"
_WORK_DIRNAME = "work"
_UNMOUNT_ATTEMPTS = 20
_UNMOUNT_RETRY_DELAY_SECONDS = 0.25


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
        *,
        lazy: bool = False,
    ) -> None:
        """Tear down an active virtual workspace for `profile`.

        Args:
            profile: Resolved launcher profile.
            workspace: Workspace returned by `mount`, if known.
            lazy: Use lazy unmount (`fusermount3 -uz`) when supported.
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

        Any `.patch.ini` or `.patch.toml` entries are rendered into an
        ephemeral top-level read-only `lowerdir` (`synthesized`) so
        `state/upper` stays clean of unmodified files.

        Args:
            profile: Resolved launcher profile.

        Returns:
            A `MountedWorkspace` pointing at the mounted `merged` dir.

        Raises:
            MountError: If the host platform is not Linux, FUSE tools
                are missing, or mounting fails.
            OverlayError: If source directories are missing, patches
                fail to render, or target is busy/non-empty.
        """
        if profile.platform is not PlatformKind.LINUX:
            raise MountError.unsupported_platform(
                self.kind.value,
                profile.platform.value,
            )

        _validate_source_directories(profile)
        fuse_bin = _require_tool("fuse-overlayfs")
        merged_dir = profile.merged_dir
        synthesized_dir = _synthesized_dir_for(profile)

        if self.is_mounted(profile):
            raise OverlayError.already_active(merged_dir)
        _ensure_empty_directory(merged_dir)

        plan = plan_profile(profile)
        upper_dir, work_dir, ephemeral_root = _prepare_fuse_dirs(profile)
        patched_entries = plan.patched_entries()

        try:
            lower_list: list[Path] = []
            if patched_entries:
                _materialize_patched_files(
                    patched_entries,
                    target_root=synthesized_dir,
                    upper_dir=profile.upper_dir,
                )
                lower_list.append(synthesized_dir)
            lower_list.extend(reversed(profile.layers))
            lower_list.append(profile.base_dir)
        except Exception:
            _cleanup_fuse_dirs(merged_dir, ephemeral_root, synthesized_dir)
            raise

        lower_opt = ":".join(_escape_overlay_opt(path) for path in lower_list)
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
            _cleanup_fuse_dirs(merged_dir, ephemeral_root, synthesized_dir)
            raise MountError.command_failed(
                command,
                result.returncode,
                result.stderr,
            )

        return MountedWorkspace(
            profile_name=profile.name,
            backend=self.kind,
            merged_dir=merged_dir,
            upper_dir=profile.upper_dir,
            base_dir=profile.base_dir,
            layers=profile.layers,
            ephemeral_root=ephemeral_root,
        )

    def unmount(
        self,
        profile: ResolvedProfile,
        workspace: MountedWorkspace | None = None,
        *,
        lazy: bool = False,
    ) -> None:
        """Unmount the FUSE overlay and clean up ephemeral dirs.

        Args:
            profile: Resolved launcher profile.
            workspace: Workspace returned by `mount`, if available.
            lazy: Pass `-uz` to detach immediately if busy.

        Raises:
            MountError: If `fusermount3`/`fusermount` fails or is
                absent.
            OverlayError: If no mount is active when called directly.
        """
        if profile.platform is not PlatformKind.LINUX:
            raise MountError.unsupported_platform(
                self.kind.value,
                profile.platform.value,
            )

        merged_dir = (
            workspace.merged_dir if workspace is not None else profile.merged_dir
        )
        ephemeral_root = (
            workspace.ephemeral_root
            if workspace is not None
            else profile.runtime_dir / _EPHEMERAL_DIRNAME
        )
        synthesized_dir = _synthesized_dir_for(profile)

        if not _is_mountpoint(merged_dir):
            if workspace is None:
                raise OverlayError.not_active(merged_dir)
            _cleanup_fuse_dirs(merged_dir, ephemeral_root, synthesized_dir)
            return

        unmount_bin = _find_unmount_tool()
        unmount_flag = "-uz" if lazy else "-u"
        command = (unmount_bin, unmount_flag, str(merged_dir))

        for attempt in range(1, _UNMOUNT_ATTEMPTS + 1):
            result = subprocess.run(  # noqa: S603 - fixed fusermount binary
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if result.returncode == 0:
                _cleanup_fuse_dirs(merged_dir, ephemeral_root, synthesized_dir)
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
        return _is_mountpoint(profile.merged_dir)


class SymlinkStagingBackend:
    """Cross-platform shadow tree using links and isolated copies."""

    kind: BackendKind = BackendKind.SYMLINK

    def mount(self, profile: ResolvedProfile) -> MountedWorkspace:
        """Build a staged virtual directory tree for `profile`.

        Read-only assets are symlinked (falling back to hardlinks on
        Windows when unprivileged), files matching `copy_patterns` are
        copied, and `.patch.ini`/`.patch.toml` targets are rendered into
        isolated copies.

        Args:
            profile: Resolved launcher profile.

        Returns:
            A `MountedWorkspace` pointing at the staged `merged` dir.

        Raises:
            OverlayError: If already active, target non-empty, or source
                directories/patches are invalid.
        """
        _validate_source_directories(profile)
        merged_dir = profile.merged_dir
        manifest_path = _manifest_path_for(profile)

        if self.is_mounted(profile):
            raise OverlayError.already_active(merged_dir)
        _ensure_empty_directory(merged_dir)

        plan = plan_profile(profile)
        upper_dir = profile.upper_dir
        copied_hashes: dict[str, str] = {}
        linked_files: list[str] = []

        try:
            for rel_dir in plan.directories:
                (merged_dir / rel_dir).mkdir(parents=True, exist_ok=True)

            for entry in plan.entries:
                _stage_entry(
                    entry,
                    merged_dir=merged_dir,
                    copied_hashes=copied_hashes,
                    linked_files=linked_files,
                )

            manifest = _StagingManifest(
                persist_state=profile.persist_state,
                upper_dir=upper_dir,
                copied_hashes=frozendict(copied_hashes),
                linked_files=frozenset(linked_files),
            )
            _write_json_atomic(manifest_path, manifest.to_dict())
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
        *,
        lazy: bool = False,
    ) -> None:
        """Sync changed writable files to state and remove staged tree.

        Args:
            profile: Resolved launcher profile.
            workspace: Workspace returned by `mount`, if available.
            lazy: Accepted for backend symmetry; unused by symlink mode.

        Raises:
            OverlayError: If no active staged workspace exists or the
                manifest is corrupt.
        """
        _ = lazy
        merged_dir = (
            workspace.merged_dir if workspace is not None else profile.merged_dir
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
                linked_files=manifest.linked_files,
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
        return _manifest_path_for(profile).is_file() and profile.merged_dir.is_dir()


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


def clean_state(profile: ResolvedProfile) -> bool:
    """Remove persisted writable runtime state for `profile`.

    Does not touch `base_dir` or any overlay layer. Refuses to run if
    either backend currently has `profile` mounted.

    Args:
        profile: Resolved launcher profile.

    Returns:
        `True` if `profile.state_dir` existed and was deleted, otherwise
        `False`.

    Raises:
        OverlayError: If `profile` currently has an active workspace.
    """
    for kind in BackendKind:
        if get_backend(kind).is_mounted(profile):
            raise OverlayError.already_active(profile.merged_dir)

    if not profile.state_dir.exists():
        return False
    shutil.rmtree(profile.state_dir)
    return True


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
    if include_state and profile.upper_dir is not None:
        sources.append(
            LayerSource(
                label="state",
                root=profile.upper_dir,
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
    linked_files: frozenset[str]

    def to_dict(self) -> dict[str, object]:
        """Serialise the manifest to a JSON-compatible mapping."""
        return {
            "persist_state": self.persist_state,
            "upper_dir": (str(self.upper_dir) if self.upper_dir is not None else None),
            "copied_hashes": dict(self.copied_hashes),
            "linked_files": sorted(self.linked_files),
        }

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, object],
        *,
        source_path: Path,
    ) -> Self:
        """Reconstruct a `_StagingManifest` from `to_dict` output."""
        persist_state = raw.get("persist_state")
        upper_raw = raw.get("upper_dir")
        copied_raw = raw.get("copied_hashes")
        linked_raw = raw.get("linked_files", [])
        if (
            not isinstance(persist_state, bool)
            or not isinstance(copied_raw, Mapping)
            or not isinstance(linked_raw, Sequence)
            or isinstance(linked_raw, str)
        ):
            raise OverlayError.invalid_manifest_schema(source_path)
        if upper_raw is not None and not isinstance(upper_raw, str):
            raise OverlayError.invalid_manifest_schema(source_path)

        copied_hashes: dict[str, str] = {}
        for key, value in copied_raw.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise OverlayError.invalid_manifest_schema(source_path)
            copied_hashes[key] = value

        linked_files: set[str] = set()
        for item in linked_raw:
            if not isinstance(item, str):
                raise OverlayError.invalid_manifest_schema(source_path)
            linked_files.add(item)

        return cls(
            persist_state=persist_state,
            upper_dir=Path(upper_raw) if upper_raw is not None else None,
            copied_hashes=frozendict(copied_hashes),
            linked_files=frozenset(linked_files),
        )


def _stage_entry(
    entry: FileEntry,
    *,
    merged_dir: Path,
    copied_hashes: dict[str, str],
    linked_files: list[str],
) -> None:
    target = merged_dir / entry.relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    rel_posix = entry.relative_path.as_posix()
    match entry.materialization:
        case Materialization.PATCH:
            rendered = render_entry_text(entry)
            target.write_text(rendered, encoding="utf-8", newline="")
            copied_hashes[rel_posix] = _sha256_file(target)
        case Materialization.COPY:
            if entry.source_path is not None:
                shutil.copy2(entry.source_path, target)
                copied_hashes[rel_posix] = _sha256_file(target)
        case Materialization.SYMLINK:
            if entry.source_path is not None:
                _link_readonly(entry.source_path, target)
                linked_files.append(rel_posix)


def _synthesized_dir_for(profile: ResolvedProfile) -> Path:
    return profile.runtime_dir / _SYNTHESIZED_DIRNAME


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


def _materialize_patched_files(
    entries: Sequence[FileEntry],
    *,
    target_root: Path,
    upper_dir: Path | None,
) -> None:
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    for entry in entries:
        rendered = render_entry_text(entry)
        target = target_root / entry.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="")
        if upper_dir is not None and (upper_dir / entry.relative_path).is_file():
            (upper_dir / entry.relative_path).write_text(
                rendered,
                encoding="utf-8",
                newline="",
            )


def _cleanup_fuse_dirs(
    merged_dir: Path,
    ephemeral_root: Path | None,
    synthesized_dir: Path | None = None,
) -> None:
    if ephemeral_root is not None and ephemeral_root.exists():
        shutil.rmtree(ephemeral_root, ignore_errors=True)
    if synthesized_dir is not None and synthesized_dir.exists():
        shutil.rmtree(synthesized_dir, ignore_errors=True)
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


def _link_readonly(source: Path, target: Path) -> None:
    try:
        target.symlink_to(source)
    except OSError:
        # Unprivileged Windows accounts without Developer Mode cannot
        # create symbolic links; fall back to a same-volume hardlink.
        target.hardlink_to(source)


def _sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


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

    if not isinstance(raw, Mapping):
        raise OverlayError.invalid_manifest_schema(path)
    return _StagingManifest.from_dict(raw, source_path=path)


def _sync_staged_changes(
    *,
    merged_dir: Path,
    upper_dir: Path,
    copied_hashes: frozendict[str, str],
    linked_files: frozenset[str],
) -> None:
    if not merged_dir.is_dir():
        return

    for current_dir, _dirnames, filenames in merged_dir.walk():
        rel_dir = current_dir.relative_to(merged_dir)
        for filename in filenames:
            full_path = current_dir / filename
            if full_path.is_symlink() or not full_path.is_file():
                continue

            rel_path = Path(filename) if rel_dir == Path() else rel_dir / filename
            rel_posix = rel_path.as_posix()
            if rel_posix in linked_files and full_path.stat().st_nlink > 1:
                continue

            recorded_hash = copied_hashes.get(rel_posix)
            if recorded_hash is not None and _sha256_file(full_path) == recorded_hash:
                continue

            destination = upper_dir / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(full_path, destination)
            _LOGGER.debug("Persisted modified file to state: %s", rel_posix)
