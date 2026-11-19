"""Pure layer planning and conflict inspection for overlays."""

from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
lazy from collections.abc import Sequence

from mentara.errors import OverlayError

__all__ = [
    "CaseCollision",
    "EntryOrigin",
    "FileEntry",
    "LayerSource",
    "Materialization",
    "OverlayPlan",
    "build_overlay_plan",
    "matches_any_pattern",
]


class EntryOrigin(StrEnum):
    """Provenance category of a resolved virtual file."""

    BASE = "base"
    LAYER = "layer"
    STATE = "state"


class Materialization(StrEnum):
    """How the symlink staging backend materialises a file."""

    SYMLINK = "symlink"
    COPY = "copy"


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
    """Winning file resolved across all stacked layers."""

    relative_path: Path
    source_path: Path
    origin: EntryOrigin
    layer_label: str
    materialization: Materialization
    shadowed_from: tuple[str, ...] = ()


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
        """Return entries supplied by overlay layers or writable state.

        Returns:
            All entries whose origin is not `EntryOrigin.BASE`.
        """
        return tuple(
            entry for entry in self.entries if entry.origin is not EntryOrigin.BASE
        )

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


def build_overlay_plan(
    sources: Sequence[LayerSource],
    *,
    copy_patterns: Sequence[str] = (),
) -> OverlayPlan:
    """Compute the merged file map across ordered bottom-to-top sources.

    Later entries in `sources` override earlier entries at the same
    relative path.

    Args:
        sources: Ordered layer sources from lowest to highest priority.
        copy_patterns: Glob patterns marked as `Materialization.COPY`.

    Returns:
        A deterministic `OverlayPlan` with directories, entries, and any
        case-only collisions across layers.

    Raises:
        OverlayError: If a required source directory does not exist.
    """
    directories: set[Path] = set()
    winning: dict[Path, FileEntry] = {}
    folded_variants: dict[str, dict[Path, str]] = {}

    for source in sources:
        if not source.root.is_dir():
            if source.required:
                raise OverlayError.missing_directory(source.label, source.root)
            continue

        _scan_source(
            source=source,
            copy_patterns=copy_patterns,
            directories=directories,
            winning=winning,
            folded_variants=folded_variants,
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
        for folded, variant_map in sorted(folded_variants.items())
        if len(variant_map) > 1
    )

    sorted_dirs = tuple(sorted(directories, key=lambda path: path.as_posix()))
    sorted_entries = tuple(
        winning[key] for key in sorted(winning, key=lambda path: path.as_posix())
    )
    return OverlayPlan(
        directories=sorted_dirs,
        entries=sorted_entries,
        case_collisions=collisions,
    )


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
    directories: set[Path],
    winning: dict[Path, FileEntry],
    folded_variants: dict[str, dict[Path, str]],
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
            directories.add(Path(dirname) if is_top_level else rel_dir / dirname)

        for filename in sorted(filenames):
            if is_top_level and filename in excluded:
                continue
            if source.origin is EntryOrigin.STATE and filename.startswith(".wh."):
                continue
            rel_file = Path(filename) if is_top_level else rel_dir / filename
            full_path = current_dir / filename
            if not (full_path.is_file() or full_path.is_symlink()):
                continue

            previous = winning.get(rel_file)
            shadowed = (
                (*previous.shadowed_from, previous.layer_label)
                if previous is not None
                else ()
            )
            materialization = (
                Materialization.COPY
                if (
                    source.origin is EntryOrigin.STATE
                    or matches_any_pattern(rel_file, copy_patterns)
                )
                else Materialization.SYMLINK
            )
            winning[rel_file] = FileEntry(
                relative_path=rel_file,
                source_path=full_path,
                origin=source.origin,
                layer_label=source.label,
                materialization=materialization,
                shadowed_from=shadowed,
            )

            folded = rel_file.as_posix().casefold()
            folded_variants.setdefault(folded, {})[rel_file] = source.label
