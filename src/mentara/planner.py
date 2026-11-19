"""Pure layer planning, patch/MIX composition, and conflict checks."""

import tempfile
from dataclasses import dataclass, field, replace
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final, assert_never
lazy from collections.abc import Sequence

from mentara.config import MIXDecryptMode
from mentara.errors import OverlayError
from mentara.mix import (
    MIX_PATCH_SUFFIX,
    MIXArchiveOp,
    MIXContext,
    MIXFileOp,
    MIXOp,
    MIXPatchOp,
    MIXProbeKind,
    compose_mix_archive,
    open_mix_archive,
    probe_mix_file,
    render_mix_member_text,
)
from mentara.patcher import (
    PatchSpec,
    apply_patch_chain,
    parse_patch_target,
)

__all__ = [
    "WHITEOUT_PREFIX",
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

WHITEOUT_PREFIX: Final[str] = ".wh."
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
    mix_ops: tuple[MIXOp, ...] = ()
    mix_probe: MIXProbeKind | None = None


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
    hidden_paths: tuple[Path, ...] = ()
    mix_context: MIXContext = field(default_factory=MIXContext)

    def overrides(self) -> tuple[FileEntry, ...]:
        """Return entries supplied or modified by layers or state.

        Returns:
            All entries whose origin is not `EntryOrigin.BASE` or that
            require synthesis (such as base MIX decryption).
        """
        return tuple(
            entry
            for entry in self.entries
            if entry.origin is not EntryOrigin.BASE
            or entry.materialization in {Materialization.PATCH, Materialization.MIX}
        )

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


def build_overlay_plan(
    sources: Sequence[LayerSource],
    *,
    copy_patterns: Sequence[str] = (),
    mix_decrypt: MIXDecryptMode = MIXDecryptMode.LAYERS,
    mix_context: MIXContext | None = None,
) -> OverlayPlan:
    """Compute the merged file map across ordered bottom-to-top sources.

    Later entries in `sources` override earlier entries at the same
    relative path, while `.patch.*` files, `.patch.mix` archives, and
    `<archive>.mix/` container directories compose incrementally on top
    of lower-layer files. Encrypted `.mix` archives are automatically
    scheduled for decryption according to `mix_decrypt`.

    Args:
        sources: Ordered layer sources from lowest to highest priority.
        copy_patterns: Glob patterns marked as `Materialization.COPY`.
        mix_decrypt: Policy for automatic standalone MIX decryption.
        mix_context: Optional decryption context (auto-derived from
            `sources` when omitted).

    Returns:
        A deterministic `OverlayPlan` with directories, entries,
        consumed hidden paths, and case-only collisions across layers.

    Raises:
        OverlayError: If a required source directory does not exist or
            an overlay container layout is invalid.
    """
    accumulator = _PlanAccumulator(
        copy_patterns=tuple(copy_patterns),
        mix_decrypt=mix_decrypt,
    )

    for source in sources:
        if not source.root.is_dir():
            if source.required:
                raise OverlayError.missing_directory(source.label, source.root)
            continue

        _scan_source(source=source, accumulator=accumulator)

    resolved_context = (
        mix_context
        if mix_context is not None
        else MIXContext(
            search_dirs=tuple(
                source.root
                for source in reversed(sources)
                if source.origin in {EntryOrigin.LAYER, EntryOrigin.BASE}
                and source.root.is_dir()
            )
        )
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
        for folded, variant_map in sorted(accumulator.folded_variants.items())
        if len(variant_map) > 1
    )

    sorted_dirs = tuple(
        sorted(accumulator.directories, key=lambda path: path.as_posix())
    )
    sorted_entries = tuple(
        accumulator.winning[key]
        for key in sorted(accumulator.winning, key=lambda path: path.as_posix())
    )
    sorted_hidden = tuple(
        sorted(accumulator.hidden_paths, key=lambda path: path.as_posix())
    )
    return OverlayPlan(
        directories=sorted_dirs,
        entries=sorted_entries,
        case_collisions=collisions,
        hidden_paths=sorted_hidden,
        mix_context=resolved_context,
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
            raise OverlayError.unreadable_file(
                entry.source_path,
                str(exc),
            ) from exc

    if not entry.patches:
        return base_text
    return apply_patch_chain(base_text, entry.patches)


def render_virtual_text(plan: OverlayPlan, target: Path) -> str:
    """Render a virtual text file or an entry inside a virtual `.mix`.

    Supports regular virtual paths (`RA2MO.ini`), inner MIX paths
    (`expandmo99.mix/rulesmo.ini`), and nested MIX member paths
    (`ra2md.mix/localmd.mix/rulesmd.ini`).

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
        mix_relative, inner_relative = mix_split
        mix_entry = plan.lookup_case_insensitive(mix_relative)
        if mix_entry is None:
            raise OverlayError.missing_virtual_file(target)
        return render_mix_member_text(
            mix_entry.source_path,
            mix_ops=mix_entry.mix_ops,
            member_path=inner_relative.parts,
            context=plan.mix_context,
        )

    entry = plan.lookup_case_insensitive(target)
    if entry is None:
        raise OverlayError.missing_virtual_file(target)
    return render_entry_text(entry)


def materialize_synthesized_entry(
    entry: FileEntry,
    target_path: Path,
    *,
    context: MIXContext | None = None,
) -> None:
    """Atomically write a `PATCH` or `MIX` synthesized entry to disk.

    Args:
        entry: Synthesized `FileEntry` from an `OverlayPlan`.
        target_path: Destination file path on disk.
        context: Optional MIX decryption context.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    match entry.materialization:
        case Materialization.PATCH:
            rendered = render_entry_text(entry)
            _write_text_atomic(target_path, rendered)
        case Materialization.MIX:
            compose_mix_archive(
                target_path,
                base_archive=entry.source_path,
                mix_ops=entry.mix_ops,
                context=context,
            )
        case Materialization.COPY | Materialization.SYMLINK:
            pass
        case _:
            assert_never(entry.materialization)


def validate_synthesized_entry(
    entry: FileEntry,
    *,
    context: MIXContext | None = None,
) -> None:
    """Dry-run validation of a `PATCH` or `MIX` entry without writing.

    Args:
        entry: Synthesized `FileEntry` to validate.
        context: Optional MIX decryption context.

    Raises:
        OverlayError: If any patch or MIX source is malformed.
    """
    match entry.materialization:
        case Materialization.PATCH:
            _ = render_entry_text(entry)
        case Materialization.MIX:
            _validate_mix_entry(entry, context=context)
        case Materialization.COPY | Materialization.SYMLINK:
            pass
        case _:
            assert_never(entry.materialization)


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


# Mutable internal accumulator for a single overlay plan build.
@dataclass(slots=True)
class _PlanAccumulator:
    copy_patterns: tuple[str, ...] = ()
    mix_decrypt: MIXDecryptMode = MIXDecryptMode.LAYERS
    directories: set[Path] = field(default_factory=set)
    winning: dict[Path, FileEntry] = field(default_factory=dict)
    folded_keys: dict[str, Path] = field(default_factory=dict)
    folded_variants: dict[str, dict[Path, str]] = field(default_factory=dict)
    hidden_paths: set[Path] = field(default_factory=set)

    def record_variant(self, relative_path: Path, label: str) -> None:
        folded = relative_path.as_posix().casefold()
        self.folded_variants.setdefault(folded, {})[relative_path] = label
        self.folded_keys.setdefault(folded, relative_path)

    def resolve_canonical(self, relative_path: Path) -> Path:
        if relative_path in self.winning:
            return relative_path
        existing = self.folded_keys.get(relative_path.as_posix().casefold())
        if existing is not None and existing in self.winning:
            return existing
        return relative_path


def _write_text_atomic(path: Path, content: str) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _validate_mix_entry(
    entry: FileEntry,
    *,
    context: MIXContext | None,
) -> None:
    if entry.source_path is not None:
        _ = open_mix_archive(entry.source_path, context=context)
    seen_targets: set[tuple[str, ...]] = set()
    for op in entry.mix_ops:
        match op:
            case MIXArchiveOp():
                _ = open_mix_archive(op.source_path, context=context)
            case MIXFileOp():
                if not op.source_path.is_file():
                    role = "MIX overlay file"
                    raise OverlayError.missing_file(role, op.source_path)
                if (
                    op.target_path[-1].casefold().endswith(_MIX_SUFFIX)
                    and probe_mix_file(op.source_path).needs_decryption
                ):
                    _ = open_mix_archive(op.source_path, context=context)
            case MIXPatchOp():
                folded = tuple(part.casefold() for part in op.target_path)
                if folded not in seen_targets:
                    seen_targets.add(folded)
                    _ = render_mix_member_text(
                        entry.source_path,
                        mix_ops=entry.mix_ops,
                        member_path=op.target_path,
                        context=context,
                    )
            case _:
                assert_never(op)


def _is_mix_segment(segment: str) -> bool:
    return segment.casefold().endswith(_MIX_SUFFIX) and len(segment) > len(_MIX_SUFFIX)


def _split_mix_container_path(relative_path: Path) -> tuple[Path, Path] | None:
    parts = relative_path.parts
    for index, segment in enumerate(parts[:-1]):
        if _is_mix_segment(segment):
            mix_relative = Path(*parts[: index + 1])
            inner_relative = Path(*parts[index + 1 :])
            return mix_relative, inner_relative
    return None


def _parse_mix_patch_archive(relative_path: Path) -> Path | None:
    name = relative_path.name
    if name.casefold().endswith(MIX_PATCH_SUFFIX) and len(name) > len(MIX_PATCH_SUFFIX):
        stem = name[: -len(MIX_PATCH_SUFFIX)]
        target_name = f"{stem}{_MIX_SUFFIX}"
        parent = relative_path.parent
        return Path(target_name) if parent == Path() else parent / target_name
    return None


def _scan_source(
    *,
    source: LayerSource,
    accumulator: _PlanAccumulator,
) -> None:
    excluded = frozenset(source.exclude)
    for current_dir, dirnames, filenames in source.root.walk():
        relative_dir = current_dir.relative_to(source.root)
        is_top_level = relative_dir == Path()

        dirnames[:] = sorted(
            name for name in dirnames if not (is_top_level and name in excluded)
        )
        for dirname in dirnames:
            candidate_dir = Path(dirname) if is_top_level else relative_dir / dirname
            if source.origin is EntryOrigin.LAYER and _is_or_inside_mix_dir(
                candidate_dir
            ):
                continue
            accumulator.directories.add(candidate_dir)

        for filename in sorted(filenames):
            if is_top_level and filename in excluded:
                continue
            if source.origin is EntryOrigin.STATE and filename.startswith(
                WHITEOUT_PREFIX
            ):
                continue

            relative_file = Path(filename) if is_top_level else relative_dir / filename
            full_path = current_dir / filename
            if not (full_path.is_file() or full_path.is_symlink()):
                continue

            _dispatch_scanned_file(
                relative_file=relative_file,
                full_path=full_path,
                source=source,
                accumulator=accumulator,
            )


def _is_or_inside_mix_dir(relative_dir: Path) -> bool:
    return any(_is_mix_segment(part) for part in relative_dir.parts)


def _dispatch_scanned_file(
    *,
    relative_file: Path,
    full_path: Path,
    source: LayerSource,
    accumulator: _PlanAccumulator,
) -> None:
    if source.origin is EntryOrigin.LAYER:
        mix_container = _split_mix_container_path(relative_file)
        if mix_container is not None:
            mix_relative, inner_relative = mix_container
            _record_mix_container_member(
                mix_relative=mix_relative,
                inner_relative=inner_relative,
                full_path=full_path,
                layer_label=source.label,
                accumulator=accumulator,
            )
            return

        mix_patch_target = _parse_mix_patch_archive(relative_file)
        if mix_patch_target is not None:
            accumulator.hidden_paths.add(relative_file)
            _record_mix_archive_patch(
                mix_relative=mix_patch_target,
                source_path=full_path,
                layer_label=source.label,
                accumulator=accumulator,
            )
            return

        patch_target = parse_patch_target(relative_file)
        if patch_target is not None:
            target_relative, patch_kind = patch_target
            accumulator.hidden_paths.add(relative_file)
            _record_patch_entry(
                target_relative=target_relative,
                spec=PatchSpec(
                    kind=patch_kind,
                    source_path=full_path,
                    layer_label=source.label,
                ),
                accumulator=accumulator,
            )
            return

    _record_full_entry(
        relative_file=relative_file,
        full_path=full_path,
        source=source,
        accumulator=accumulator,
    )


def _record_mix_container_member(
    *,
    mix_relative: Path,
    inner_relative: Path,
    full_path: Path,
    layer_label: str,
    accumulator: _PlanAccumulator,
) -> None:
    nested_parents = inner_relative.parts[:-1]
    for parent_segment in nested_parents:
        if not _is_mix_segment(parent_segment):
            detail = (
                f"invalid non-.mix subdirectory {parent_segment!r} inside "
                f"MIX container {mix_relative.as_posix()}"
            )
            raise OverlayError.invalid_mix(full_path, detail)

    canonical_mix = accumulator.resolve_canonical(mix_relative)
    if canonical_mix != mix_relative:
        accumulator.hidden_paths.add(mix_relative)

    leaf_name = inner_relative.parts[-1]
    leaf_path = Path(leaf_name)
    nested_mix_patch = _parse_mix_patch_archive(leaf_path)
    inner_text_patch = parse_patch_target(leaf_path)

    if nested_mix_patch is not None:
        new_op: MIXOp = MIXArchiveOp(
            target_path=(*nested_parents, nested_mix_patch.name),
            source_path=full_path,
            layer_label=layer_label,
        )
    elif inner_text_patch is not None:
        inner_target, patch_kind = inner_text_patch
        new_op = MIXPatchOp(
            target_path=(*nested_parents, inner_target.name),
            patch=PatchSpec(
                kind=patch_kind,
                source_path=full_path,
                layer_label=layer_label,
            ),
        )
    else:
        new_op = MIXFileOp(
            target_path=(*nested_parents, leaf_name),
            source_path=full_path,
            layer_label=layer_label,
        )

    _append_mix_op(
        canonical_mix=canonical_mix,
        new_op=new_op,
        layer_label=layer_label,
        accumulator=accumulator,
    )


def _record_mix_archive_patch(
    *,
    mix_relative: Path,
    source_path: Path,
    layer_label: str,
    accumulator: _PlanAccumulator,
) -> None:
    canonical_mix = accumulator.resolve_canonical(mix_relative)
    new_op = MIXArchiveOp(
        target_path=(),
        source_path=source_path,
        layer_label=layer_label,
    )
    _append_mix_op(
        canonical_mix=canonical_mix,
        new_op=new_op,
        layer_label=layer_label,
        accumulator=accumulator,
    )


def _append_mix_op(
    *,
    canonical_mix: Path,
    new_op: MIXOp,
    layer_label: str,
    accumulator: _PlanAccumulator,
) -> None:
    previous = accumulator.winning.get(canonical_mix)
    shadowed = _append_shadow(previous, new_label=layer_label)
    existing_ops = previous.mix_ops if previous is not None else ()
    accumulator.winning[canonical_mix] = FileEntry(
        relative_path=canonical_mix,
        source_path=previous.source_path if previous is not None else None,
        origin=EntryOrigin.LAYER,
        layer_label=layer_label,
        materialization=Materialization.MIX,
        shadowed_from=shadowed,
        mix_ops=(*existing_ops, new_op),
        mix_probe=previous.mix_probe if previous is not None else None,
    )
    accumulator.record_variant(canonical_mix, layer_label)


def _record_patch_entry(
    *,
    target_relative: Path,
    spec: PatchSpec,
    accumulator: _PlanAccumulator,
) -> None:
    canonical_target = accumulator.resolve_canonical(target_relative)
    previous = accumulator.winning.get(canonical_target)
    shadowed = _append_shadow(previous, new_label=spec.layer_label)
    patches = (*previous.patches, spec) if previous is not None else (spec,)
    accumulator.winning[canonical_target] = FileEntry(
        relative_path=canonical_target,
        source_path=previous.source_path if previous is not None else None,
        origin=EntryOrigin.LAYER,
        layer_label=spec.layer_label,
        materialization=Materialization.PATCH,
        shadowed_from=shadowed,
        patches=patches,
    )
    accumulator.record_variant(canonical_target, spec.layer_label)


def _should_auto_decrypt_mix(
    relative_file: Path,
    *,
    origin: EntryOrigin,
    mix_decrypt: MIXDecryptMode,
) -> bool:
    if not _is_mix_segment(relative_file.name):
        return False
    match mix_decrypt:
        case MIXDecryptMode.PATCHED:
            return False
        case MIXDecryptMode.LAYERS:
            return origin is EntryOrigin.LAYER
        case MIXDecryptMode.ALL:
            return origin in {EntryOrigin.BASE, EntryOrigin.LAYER}
        case _:
            assert_never(mix_decrypt)


def _record_full_entry(
    *,
    relative_file: Path,
    full_path: Path,
    source: LayerSource,
    accumulator: _PlanAccumulator,
) -> None:
    previous = accumulator.winning.get(relative_file)
    shadowed = _append_shadow(previous, new_label=source.label)

    # When persisted state exists for a file with overlay patches or
    # MIX operations, re-apply those overlay operations on top of state.
    if source.origin is EntryOrigin.STATE and previous is not None:
        if previous.patches:
            accumulator.winning[relative_file] = replace(
                previous,
                source_path=full_path,
                origin=EntryOrigin.STATE,
                materialization=Materialization.PATCH,
                shadowed_from=shadowed,
            )
            accumulator.record_variant(relative_file, source.label)
            return
        if previous.mix_ops:
            accumulator.winning[relative_file] = replace(
                previous,
                source_path=full_path,
                origin=EntryOrigin.STATE,
                materialization=Materialization.MIX,
                shadowed_from=shadowed,
            )
            accumulator.record_variant(relative_file, source.label)
            return

    probe: MIXProbeKind | None = None
    if _should_auto_decrypt_mix(
        relative_file,
        origin=source.origin,
        mix_decrypt=accumulator.mix_decrypt,
    ):
        detected_probe = probe_mix_file(full_path)
        if detected_probe.needs_decryption:
            probe = detected_probe

    if probe is not None:
        materialization = Materialization.MIX
    elif source.origin is EntryOrigin.STATE or matches_any_pattern(
        relative_file,
        accumulator.copy_patterns,
    ):
        materialization = Materialization.COPY
    else:
        materialization = Materialization.SYMLINK

    accumulator.winning[relative_file] = FileEntry(
        relative_path=relative_file,
        source_path=full_path,
        origin=source.origin,
        layer_label=source.label,
        materialization=materialization,
        shadowed_from=shadowed,
        mix_probe=probe,
    )
    accumulator.record_variant(relative_file, source.label)


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
