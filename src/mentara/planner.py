"""Pure layer planning, patch/MIX composition, and conflict checks."""

from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final
lazy from collections.abc import Sequence

from mentara.errors import OverlayError
from mentara.mix import (
    MIX_PATCH_SUFFIX,
    MixArchiveSpec,
    MixFileSpec,
    MixPatchSpec,
    compose_mix_archive,
    open_mix_archive,
    render_mix_member_text,
)
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
    "materialize_synthesized_entry",
    "render_entry_text",
    "render_virtual_text",
    "validate_synthesized_entry",
]

_MIX_SUFFIX: Final[str] = ".mix"


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
    MIX = "mix"


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
    """Winning or synthesized file resolved across stacked layers."""

    relative_path: Path
    source_path: Path | None
    origin: EntryOrigin
    layer_label: str
    materialization: Materialization
    shadowed_from: tuple[str, ...] = ()
    patches: tuple[PatchSpec, ...] = ()
    mix_archives: tuple[MixArchiveSpec, ...] = ()
    mix_files: tuple[MixFileSpec, ...] = ()
    mix_patches: tuple[MixPatchSpec, ...] = ()


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
        """Return entries supplied or modified by layers or state.

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

    def synthesized_entries(self) -> tuple[FileEntry, ...]:
        """Return entries requiring text patching or MIX composition.

        Returns:
            All entries with `Materialization.PATCH` or `MIX`.
        """
        return tuple(
            entry
            for entry in self.entries
            if entry.materialization in {Materialization.PATCH, Materialization.MIX}
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
    relative path, while `.patch.*` files and `<archive>.mix/` container
    overlays compose incrementally on top of lower-layer files.

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


def render_virtual_text(plan: OverlayPlan, target: Path) -> str:
    """Render a virtual text file or an entry inside a virtual `.mix`.

    Supports both regular virtual paths (e.g. `RA2MO.ini`) and inner MIX
    member paths (e.g. `expandmo99.mix/rulesmo.ini`).

    Args:
        plan: Resolved `OverlayPlan`.
        target: Relative virtual file path or `<archive>.mix/<member>`.

    Returns:
        Rendered UTF-8 text.

    Raises:
        OverlayError: If the target file or MIX entry does not exist.
    """
    mix_split = _split_mix_container_path(target)
    if mix_split is not None:
        mix_rel, inner_rel = mix_split
        mix_entry = plan.lookup_case_insensitive(mix_rel)
        if mix_entry is None:
            raise OverlayError.missing_virtual_file(target)
        return render_mix_member_text(
            mix_entry.source_path,
            mix_archives=mix_entry.mix_archives,
            mix_files=mix_entry.mix_files,
            mix_patches=mix_entry.mix_patches,
            member_name=inner_rel.name,
        )

    entry = plan.lookup_case_insensitive(target)
    if entry is None:
        raise OverlayError.missing_virtual_file(target)
    return render_entry_text(entry)


def materialize_synthesized_entry(
    entry: FileEntry,
    target_path: Path,
) -> None:
    """Write a `PATCH` or `MIX` synthesized entry to `target_path`.

    Args:
        entry: Synthesized `FileEntry` from an `OverlayPlan`.
        target_path: Destination file path on disk.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    match entry.materialization:
        case Materialization.PATCH:
            rendered = render_entry_text(entry)
            target_path.write_text(rendered, encoding="utf-8", newline="")
        case Materialization.MIX:
            compose_mix_archive(
                target_path,
                base_archive=entry.source_path,
                mix_archives=entry.mix_archives,
                mix_files=entry.mix_files,
                mix_patches=entry.mix_patches,
            )
        case Materialization.COPY | Materialization.SYMLINK:
            pass


def validate_synthesized_entry(entry: FileEntry) -> None:
    """Dry-run validation of a `PATCH` or `MIX` entry without writing.

    Args:
        entry: Synthesized `FileEntry` to validate.

    Raises:
        OverlayError: If any patch or MIX source is malformed.
    """
    match entry.materialization:
        case Materialization.PATCH:
            _ = render_entry_text(entry)
        case Materialization.MIX:
            if entry.source_path is not None:
                _ = open_mix_archive(entry.source_path)
            for arch_spec in entry.mix_archives:
                _ = open_mix_archive(arch_spec.source_path)
            seen_targets: set[str] = set()
            for patch_spec in entry.mix_patches:
                folded = patch_spec.target_name.casefold()
                if folded not in seen_targets:
                    seen_targets.add(folded)
                    _ = render_mix_member_text(
                        entry.source_path,
                        mix_archives=entry.mix_archives,
                        mix_files=entry.mix_files,
                        mix_patches=entry.mix_patches,
                        member_name=patch_spec.target_name,
                    )
        case Materialization.COPY | Materialization.SYMLINK:
            pass


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


def _split_mix_container_path(rel_path: Path) -> tuple[Path, Path] | None:
    parts = rel_path.parts
    for idx, segment in enumerate(parts[:-1]):
        if segment.casefold().endswith(_MIX_SUFFIX) and len(segment) > len(_MIX_SUFFIX):
            mix_rel = Path(*parts[: idx + 1])
            inner_rel = Path(*parts[idx + 1 :])
            return mix_rel, inner_rel
    return None


def _parse_mix_patch_archive(rel_path: Path) -> Path | None:
    name = rel_path.name
    if name.casefold().endswith(MIX_PATCH_SUFFIX) and len(name) > len(MIX_PATCH_SUFFIX):
        stem = name[: -len(MIX_PATCH_SUFFIX)]
        target_name = f"{stem}{_MIX_SUFFIX}"
        parent = rel_path.parent
        return Path(target_name) if parent == Path() else parent / target_name
    return None


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

        dirnames[:] = sorted(
            name for name in dirnames if not (is_top_level and name in excluded)
        )
        for dirname in dirnames:
            candidate_dir = Path(dirname) if is_top_level else rel_dir / dirname
            if source.origin is EntryOrigin.LAYER and _is_or_inside_mix_dir(
                candidate_dir
            ):
                continue
            acc.directories.add(candidate_dir)

        for filename in sorted(filenames):
            if is_top_level and filename in excluded:
                continue
            if source.origin is EntryOrigin.STATE and filename.startswith(".wh."):
                continue

            rel_file = Path(filename) if is_top_level else rel_dir / filename
            full_path = current_dir / filename
            if not (full_path.is_file() or full_path.is_symlink()):
                continue

            _dispatch_scanned_file(
                rel_file=rel_file,
                full_path=full_path,
                source=source,
                copy_patterns=copy_patterns,
                acc=acc,
            )


def _is_or_inside_mix_dir(rel_dir: Path) -> bool:
    return any(
        part.casefold().endswith(_MIX_SUFFIX) and len(part) > len(_MIX_SUFFIX)
        for part in rel_dir.parts
    )


def _dispatch_scanned_file(
    *,
    rel_file: Path,
    full_path: Path,
    source: LayerSource,
    copy_patterns: Sequence[str],
    acc: _PlanAccumulator,
) -> None:
    if source.origin is EntryOrigin.LAYER:
        mix_container = _split_mix_container_path(rel_file)
        if mix_container is not None:
            mix_rel, inner_rel = mix_container
            _record_mix_container_member(
                mix_rel=mix_rel,
                inner_rel=inner_rel,
                full_path=full_path,
                layer_label=source.label,
                acc=acc,
            )
            return

        mix_patch_target = _parse_mix_patch_archive(rel_file)
        if mix_patch_target is not None:
            _record_mix_archive_patch(
                mix_rel=mix_patch_target,
                spec=MixArchiveSpec(
                    source_path=full_path,
                    layer_label=source.label,
                ),
                acc=acc,
            )
            return

        patch_target = parse_patch_target(rel_file)
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
            return

    _record_full_entry(
        rel_file=rel_file,
        full_path=full_path,
        source=source,
        copy_patterns=copy_patterns,
        acc=acc,
    )


def _record_mix_container_member(
    *,
    mix_rel: Path,
    inner_rel: Path,
    full_path: Path,
    layer_label: str,
    acc: _PlanAccumulator,
) -> None:
    previous = acc.winning.get(mix_rel)
    shadowed = _append_shadow(previous, new_label=layer_label)
    mix_archives = previous.mix_archives if previous is not None else ()
    mix_files = previous.mix_files if previous is not None else ()
    mix_patches = previous.mix_patches if previous is not None else ()

    inner_patch = parse_patch_target(inner_rel)
    if inner_patch is not None:
        inner_target, patch_kind = inner_patch
        mix_patches = (
            *mix_patches,
            MixPatchSpec(
                target_name=inner_target.name,
                patch=PatchSpec(
                    kind=patch_kind,
                    source_path=full_path,
                    layer_label=layer_label,
                ),
            ),
        )
    else:
        mix_files = (
            *mix_files,
            MixFileSpec(
                target_name=inner_rel.name,
                source_path=full_path,
                layer_label=layer_label,
            ),
        )

    acc.winning[mix_rel] = FileEntry(
        relative_path=mix_rel,
        source_path=previous.source_path if previous is not None else None,
        origin=EntryOrigin.LAYER,
        layer_label=layer_label,
        materialization=Materialization.MIX,
        shadowed_from=shadowed,
        mix_archives=mix_archives,
        mix_files=mix_files,
        mix_patches=mix_patches,
    )
    acc.record_variant(mix_rel, layer_label)


def _record_mix_archive_patch(
    *,
    mix_rel: Path,
    spec: MixArchiveSpec,
    acc: _PlanAccumulator,
) -> None:
    previous = acc.winning.get(mix_rel)
    shadowed = _append_shadow(previous, new_label=spec.layer_label)
    mix_archives = (*previous.mix_archives, spec) if previous is not None else (spec,)
    acc.winning[mix_rel] = FileEntry(
        relative_path=mix_rel,
        source_path=previous.source_path if previous is not None else None,
        origin=EntryOrigin.LAYER,
        layer_label=spec.layer_label,
        materialization=Materialization.MIX,
        shadowed_from=shadowed,
        mix_archives=mix_archives,
        mix_files=previous.mix_files if previous is not None else (),
        mix_patches=previous.mix_patches if previous is not None else (),
    )
    acc.record_variant(mix_rel, spec.layer_label)


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
