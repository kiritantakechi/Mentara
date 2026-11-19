"""Pure layer planning, patch composition, and conflict inspection."""

from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
lazy from collections.abc import Sequence

from mentara.errors import OverlayError
from mentara.patcher import (
    PatchSpec,
    apply_patch_chain,
    parse_patch_target,
)

__all__ = [
    "CaseCollision",
    "EntryOrigin",
    "FileEntry",
    "LayerSource",
    "Materialization",
    "OverlayPlan",
    "build_overlay_plan",
    "matches_any_pattern",
    "render_entry_text",
]


class EntryOrigin(StrEnum):
    """Provenance category of a resolved virtual file."""

    BASE = "base"
    LAYER = "layer"
    STATE = "state"


class Materialization(StrEnum):
    """How a resolved virtual file is materialised in the workspace."""

    SYMLINK = "symlink"
    COPY = "copy"
    PATCH = "patch"


@dataclass(frozen=True, slots=True)
class LayerSource:
    """Single directory layer contributing files to an `OverlayPlan`."""

    label: str
    root: Path
    origin: EntryOrigin
    exclude: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True, slots=True)
class FileEntry:
    """Winning or text-merged file resolved across stacked layers."""

    relative_path: Path
    source_path: Path | None
    origin: EntryOrigin
    layer_label: str
    materialization: Materialization
    shadowed_from: tuple[str, ...] = ()
    patches: tuple[PatchSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseCollision:
    """Two distinct paths colliding under Windows case-insensitivity."""

    folded_path: str
    variants: tuple[tuple[Path, str], ...]


@dataclass(frozen=True, slots=True)
class OverlayPlan:
    """Deterministic, read-only view of a stacked virtual directory."""

    directories: tuple[Path, ...]
    entries: tuple[FileEntry, ...]
    case_collisions: tuple[CaseCollision, ...]

    def overrides(self) -> tuple[FileEntry, ...]:
        """Return entries supplied or patched by layers or state.

        Returns:
            All entries whose origin is not `EntryOrigin.BASE`.
        """
        return tuple(
            entry for entry in self.entries if entry.origin is not EntryOrigin.BASE
        )

    def patched_entries(self) -> tuple[FileEntry, ...]:
        """Return entries with text-level patch operations.

        Returns:
            All entries with non-empty `patches`.
        """
        return tuple(entry for entry in self.entries if entry.patches)

    def matching(self, patterns: Sequence[str]) -> tuple[FileEntry, ...]:
        """Filter entries matching any case-insensitive glob pattern.

        Args:
            patterns: Globs matched against filename or POSIX path.

        Returns:
            Matching entries in plan order.
        """
        if not patterns:
            return self.entries
        return tuple(
            entry
            for entry in self.entries
            if matches_any_pattern(entry.relative_path, patterns)
        )

    def lookup_case_insensitive(
        self,
        relative_path: Path,
    ) -> FileEntry | None:
        """Find an entry matching `relative_path` ignoring case.

        Args:
            relative_path: Relative path to search for.

        Returns:
            Matching `FileEntry`, or `None` if absent.
        """
        target = relative_path.as_posix().casefold()
        for entry in self.entries:
            if entry.relative_path.as_posix().casefold() == target:
                return entry
        return None


@dataclass(slots=True)
class _PlanAccumulator:
    directories: set[Path] = field(default_factory=set)
    winning: dict[Path, FileEntry] = field(default_factory=dict)
    folded_variants: dict[str, dict[Path, str]] = field(default_factory=dict)

    def record_variant(self, rel_path: Path, label: str) -> None:
        folded = rel_path.as_posix().casefold()
        self.folded_variants.setdefault(folded, {})[rel_path] = label


def build_overlay_plan(
    sources: Sequence[LayerSource],
    *,
    copy_patterns: Sequence[str] = (),
) -> OverlayPlan:
    """Compute the merged file map across ordered bottom-to-top sources.

    Later entries in `sources` override earlier entries at the same
    relative path, while `.patch.ini` and `.patch.toml` files compose
    incrementally on top of lower-layer files.

    Args:
        sources: Ordered layer sources from lowest to highest priority.
        copy_patterns: Glob patterns marked as `Materialization.COPY`.

    Returns:
        A deterministic `OverlayPlan` with directories, entries, and any
        case-only collisions across layers.

    Raises:
        OverlayError: If a required source directory does not exist.
    """
    acc = _PlanAccumulator()

    for source in sources:
        if not source.root.is_dir():
            if source.required:
                raise OverlayError.missing_directory(source.label, source.root)
            continue

        _scan_source(
            source=source,
            copy_patterns=copy_patterns,
            acc=acc,
        )

    collisions = tuple(
        CaseCollision(
            folded_path=folded,
            variants=tuple(
                sorted(
                    variant_map.items(),
                    key=lambda item: item[0].as_posix(),
                )
            ),
        )
        for folded, variant_map in sorted(acc.folded_variants.items())
        if len(variant_map) > 1
    )

    sorted_dirs = tuple(sorted(acc.directories, key=lambda path: path.as_posix()))
    sorted_entries = tuple(
        acc.winning[key]
        for key in sorted(acc.winning, key=lambda path: path.as_posix())
    )
    return OverlayPlan(
        directories=sorted_dirs,
        entries=sorted_entries,
        case_collisions=collisions,
    )


def render_entry_text(entry: FileEntry) -> str:
    """Render the final UTF-8 text of `entry` after applying `patches`.

    Args:
        entry: Resolved `FileEntry` from an `OverlayPlan`.

    Returns:
        Merged text content.

    Raises:
        OverlayError: If reading `source_path` or applying patches
            fails.
    """
    base_text = ""
    if entry.source_path is not None:
        try:
            with entry.source_path.open(
                encoding="utf-8",
                errors="replace",
                newline="",
            ) as handle:
                base_text = handle.read()
        except OSError as exc:
            raise OverlayError.invalid_patch(
                entry.source_path,
                str(exc),
            ) from exc

    if not entry.patches:
        return base_text
    return apply_patch_chain(base_text, entry.patches)


def matches_any_pattern(
    relative_path: Path,
    patterns: Sequence[str],
) -> bool:
    """Return whether `relative_path` matches any glob ignoring case.

    Args:
        relative_path: File path relative to the virtual workspace root.
        patterns: Globs compared against filename and full path.

    Returns:
        `True` if any pattern matches, otherwise `False`.
    """
    name_folded = relative_path.name.casefold()
    posix_folded = relative_path.as_posix().casefold()
    for raw_pattern in patterns:
        pattern = raw_pattern.casefold()
        if fnmatchcase(name_folded, pattern) or fnmatchcase(
            posix_folded,
            pattern,
        ):
            return True
    return False


def _scan_source(
    *,
    source: LayerSource,
    copy_patterns: Sequence[str],
    acc: _PlanAccumulator,
) -> None:
    excluded = frozenset(source.exclude)
    for current_dir, dirnames, filenames in source.root.walk():
        rel_dir = current_dir.relative_to(source.root)
        is_top_level = rel_dir == Path()

        # Prune excluded directories in place before descending.
        dirnames[:] = sorted(
            name for name in dirnames if not (is_top_level and name in excluded)
        )
        for dirname in dirnames:
            acc.directories.add(Path(dirname) if is_top_level else rel_dir / dirname)

        for filename in sorted(filenames):
            if is_top_level and filename in excluded:
                continue
            if source.origin is EntryOrigin.STATE and filename.startswith(".wh."):
                continue

            rel_file = Path(filename) if is_top_level else rel_dir / filename
            full_path = current_dir / filename
            if not (full_path.is_file() or full_path.is_symlink()):
                continue

            patch_target = (
                parse_patch_target(rel_file)
                if source.origin is EntryOrigin.LAYER
                else None
            )
            if patch_target is not None:
                target_rel, patch_kind = patch_target
                _record_patch_entry(
                    target_rel=target_rel,
                    spec=PatchSpec(
                        kind=patch_kind,
                        source_path=full_path,
                        layer_label=source.label,
                    ),
                    acc=acc,
                )
            else:
                _record_full_entry(
                    rel_file=rel_file,
                    full_path=full_path,
                    source=source,
                    copy_patterns=copy_patterns,
                    acc=acc,
                )


def _record_patch_entry(
    *,
    target_rel: Path,
    spec: PatchSpec,
    acc: _PlanAccumulator,
) -> None:
    previous = acc.winning.get(target_rel)
    shadowed = _append_shadow(previous, new_label=spec.layer_label)
    patches = (*previous.patches, spec) if previous is not None else (spec,)
    acc.winning[target_rel] = FileEntry(
        relative_path=target_rel,
        source_path=previous.source_path if previous is not None else None,
        origin=EntryOrigin.LAYER,
        layer_label=spec.layer_label,
        materialization=Materialization.PATCH,
        shadowed_from=shadowed,
        patches=patches,
    )
    acc.record_variant(target_rel, spec.layer_label)


def _record_full_entry(
    *,
    rel_file: Path,
    full_path: Path,
    source: LayerSource,
    copy_patterns: Sequence[str],
    acc: _PlanAccumulator,
) -> None:
    previous = acc.winning.get(rel_file)
    shadowed = _append_shadow(previous, new_label=source.label)

    # When persisted state exists for a file that also has overlay text
    # patches, apply those overlay patches on top of the state file.
    if source.origin is EntryOrigin.STATE and previous is not None and previous.patches:
        acc.winning[rel_file] = FileEntry(
            relative_path=rel_file,
            source_path=full_path,
            origin=EntryOrigin.STATE,
            layer_label=previous.layer_label,
            materialization=Materialization.PATCH,
            shadowed_from=shadowed,
            patches=previous.patches,
        )
    else:
        materialization = (
            Materialization.COPY
            if (
                source.origin is EntryOrigin.STATE
                or matches_any_pattern(rel_file, copy_patterns)
            )
            else Materialization.SYMLINK
        )
        acc.winning[rel_file] = FileEntry(
            relative_path=rel_file,
            source_path=full_path,
            origin=source.origin,
            layer_label=source.label,
            materialization=materialization,
            shadowed_from=shadowed,
        )

    acc.record_variant(rel_file, source.label)


def _append_shadow(
    previous: FileEntry | None,
    *,
    new_label: str,
) -> tuple[str, ...]:
    if previous is None:
        return ()
    if previous.layer_label in previous.shadowed_from or (
        previous.layer_label == new_label
    ):
        return previous.shadowed_from
    return (*previous.shadowed_from, previous.layer_label)
