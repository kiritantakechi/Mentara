"""Text-level INI/map/KV and TOML overlay patch merging."""

import tomllib
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, Self, assert_never
lazy from collections.abc import Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from mentara.errors import OverlayError

__all__ = [
    "INI_PATCH_EXTENSIONS",
    "TOML_PATCH_SUFFIX",
    "AppendText",
    "DeleteLines",
    "INIAppend",
    "INIDeleteSection",
    "INIKeyOp",
    "INIPatch",
    "INISectionOp",
    "INISet",
    "INIUnset",
    "INIUpdateSection",
    "InsertAfter",
    "InsertBefore",
    "PatchKind",
    "PatchSpec",
    "PrependText",
    "ReplaceText",
    "TextEdit",
    "TextOpKind",
    "apply_ini_patch",
    "apply_patch_chain",
    "apply_text_edit",
    "parse_ini_patch",
    "parse_patch_target",
    "parse_toml_patch",
]

# Directly determinable INI and key-value text formats:
# `<stem>.patch.<ext>` targets `<stem>.<ext>`.
INI_PATCH_EXTENSIONS: Final[tuple[str, ...]] = (
    "ini",
    "map",
    "yrm",
    "mpr",
    "cfg",
    "inj",
)
TOML_PATCH_SUFFIX: Final[str] = ".patch.toml"
_PATCH_MARKER: Final[str] = ".patch."


class PatchKind(StrEnum):
    """Supported declarative text patch formats."""

    INI = "ini"
    TOML = "toml"


class TextOpKind(StrEnum):
    """Line or block operation tag in a `.patch.toml` file."""

    REPLACE = "replace"
    INSERT_AFTER = "insert_after"
    INSERT_BEFORE = "insert_before"
    DELETE_LINES = "delete_lines"
    APPEND = "append"
    PREPEND = "prepend"


@dataclass(frozen=True, slots=True)
class PatchSpec:
    """Descriptor pointing to a patch file in an overlay layer."""

    kind: PatchKind
    source_path: Path
    layer_label: str


@dataclass(frozen=True, slots=True)
class INISet:
    """Set or update `key=value` within a section or top-level scope."""

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class INIUnset:
    """Remove `key` from a section or top-level scope."""

    key: str


@dataclass(frozen=True, slots=True)
class INIAppend:
    """Append `value` at the next integer key in a section."""

    value: str


type INIKeyOp = INISet | INIUnset | INIAppend


@dataclass(frozen=True, slots=True)
class INIDeleteSection:
    """Delete an entire `[section]` block from an INI document."""

    section: str


@dataclass(frozen=True, slots=True)
class INIUpdateSection:
    """Apply ordered key operations to `[section]` or root scope."""

    section: str | None
    operations: tuple[INIKeyOp, ...]


type INISectionOp = INIDeleteSection | INIUpdateSection


@dataclass(frozen=True, slots=True)
class INIPatch:
    """Parsed INI/map/KV patch containing ordered section operations."""

    operations: tuple[INISectionOp, ...] = ()


@dataclass(frozen=True, slots=True)
class ReplaceText:
    """Replace occurrences of `target` with `replacement`."""

    target: str
    replacement: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class InsertAfter:
    """Insert `content` immediately after lines matching `anchor`."""

    anchor: str
    content: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class InsertBefore:
    """Insert `content` immediately before lines matching `anchor`."""

    anchor: str
    content: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class DeleteLines:
    """Delete every line containing `contains`."""

    contains: str


@dataclass(frozen=True, slots=True)
class AppendText:
    """Append `content` at the end of a plaintext document."""

    content: str


@dataclass(frozen=True, slots=True)
class PrependText:
    """Prepend `content` at the start of a plaintext document."""

    content: str


type TextEdit = (
    ReplaceText | InsertAfter | InsertBefore | DeleteLines | AppendText | PrependText
)


def parse_patch_target(relative_path: Path) -> tuple[Path, PatchKind] | None:
    """Resolve whether `relative_path` is a declarative overlay patch.

    Recognises:
    - `<stem>.patch.<ext>` -> `<stem>.<ext>` (`PatchKind.INI`) for
      `<ext>` in `INI_PATCH_EXTENSIONS` (`ini`, `map`, `yrm`, `mpr`,
      `cfg`, `inj`).
    - `<target>.patch.toml` -> `<target>` (`PatchKind.TOML`) for general
      plaintext files.
    - A fragment of a patch directory: a directory named like a patch
      holds that patch split across files ending in its own extension
      (`*.ini` in `rules.patch.ini/`, `*.toml` in `a.cfg.patch.toml/`).
      Every fragment targets the directory's target; the planner applies
      them in name order.

    Args:
        relative_path: Relative path scanned inside an overlay layer.

    Returns:
        `(target_relative_path, PatchKind)` if `relative_path` is a
        patch file or fragment, otherwise `None`.
    """
    parent = relative_path.parent
    directory = _parse_patch_name(parent) if parent.name else None
    if directory is None:
        return _parse_patch_name(relative_path)
    name, extension = relative_path.name.casefold(), parent.suffix.casefold()
    return directory if name.endswith(extension) and name != extension else None


def _parse_patch_name(relative_path: Path) -> tuple[Path, PatchKind] | None:
    name = relative_path.name
    name_folded = name.casefold()

    for ext in INI_PATCH_EXTENSIONS:
        suffix = f"{_PATCH_MARKER}{ext}"
        if name_folded.endswith(suffix) and len(name) > len(suffix):
            stem = name[: -len(suffix)]
            original_ext = name[-len(ext) :]
            target_name = f"{stem}.{original_ext}"
            return _with_parent(relative_path.parent, target_name), PatchKind.INI

    if name_folded.endswith(TOML_PATCH_SUFFIX) and len(name) > len(TOML_PATCH_SUFFIX):
        target_name = name[: -len(TOML_PATCH_SUFFIX)]
        return _with_parent(relative_path.parent, target_name), PatchKind.TOML

    return None


def parse_ini_patch(text: str, *, source_path: Path) -> INIPatch:
    """Parse a `.patch.{ini,map,yrm,mpr,cfg,inj}` patch document.

    Directives may appear either inside `[Section]` blocks or at the
    top-level root scope (for sectionless `.cfg` and `.inj` files).
    A section repeated in the target file is edited in every
    occurrence, so the result does not depend on which duplicate the
    game engine reads:
    - `Key=Value`: set or update every `Key` line (preserving spacing
      around `=`), or append it to the last occurrence if absent.
    - `!Key` or `-Key`: delete every `Key` line.
    - `+=Value` or `+Key=Value`: append `Value` to the last occurrence
      using the next integer index across all occurrences.
    - `[-Section]`: delete every `[Section]` block.

    Args:
        text: Raw UTF-8 text of the patch file.
        source_path: File path used for error reporting.

    Returns:
        Parsed `INIPatch`.

    Raises:
        OverlayError: If a section header or key directive is malformed.
    """
    operations: list[INISectionOp] = []
    current_section: str | None = None
    current_ops: list[INIKeyOp] = []

    def _flush_current() -> None:
        nonlocal current_ops
        if current_ops:
            operations.append(
                INIUpdateSection(
                    section=current_section,
                    operations=tuple(current_ops),
                ),
            )
            current_ops = []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue

        if stripped.startswith("[") and stripped.endswith("]"):
            _flush_current()
            header = stripped[1:-1].strip()
            if not header:
                detail = f"empty section header on line {line_no}"
                raise OverlayError.invalid_patch(source_path, detail)
            if header.startswith("-") and len(header) > 1:
                operations.append(
                    INIDeleteSection(section=header[1:].strip()),
                )
                current_section = None
            else:
                current_section = header
            continue

        current_ops.append(_parse_ini_op(stripped, source_path, line_no))

    _flush_current()
    return INIPatch(operations=tuple(operations))


def parse_toml_patch(
    text: str,
    *,
    source_path: Path,
) -> tuple[TextEdit, ...]:
    """Parse and validate a `.patch.toml` plaintext patch document.

    Args:
        text: Raw UTF-8 TOML text.
        source_path: Patch file path for error reporting.

    Returns:
        Ordered tuple of `TextEdit` operations.

    Raises:
        OverlayError: If TOML syntax or schema validation fails.
    """
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise OverlayError.invalid_patch(source_path, str(exc)) from exc

    try:
        doc = _TOMLPatchDocument.parse(payload)
    except ValidationError as exc:
        raise OverlayError.invalid_patch(source_path, str(exc)) from exc

    return tuple(item.to_edit() for item in doc.text)


def apply_ini_patch(
    base_text: str,
    patch: INIPatch,
    *,
    default_newline: str = "\r\n",
) -> str:
    """Apply an `INIPatch` while preserving comments and line endings.

    The text is parsed once into header-delimited blocks, each section
    operation rewrites whole blocks, and the blocks are joined again, so
    a `[Section]` repeated in `base_text` is edited in every occurrence.

    Args:
        base_text: Existing INI/map/KV text (empty if creating a file).
        patch: Structured section and key operations.
        default_newline: Line ending used when `base_text` has no lines.

    Returns:
        Updated text.
    """
    if not patch.operations:
        return base_text

    newline = _detect_newline(base_text, default=default_newline)
    blocks = _parse_ini_blocks(base_text.splitlines())
    for section_op in patch.operations:
        match section_op:
            case INIDeleteSection(section=section):
                folded_name = section.casefold()
                blocks = tuple(
                    block for block in blocks if block.folded_name != folded_name
                )
            case INIUpdateSection(section=section, operations=key_ops):
                blocks = _update_ini_section(blocks, section, key_ops)
            case _:
                assert_never(section_op)

    lines = [line for block in blocks for line in block.lines]
    return newline.join(lines) + newline if lines else ""


def apply_text_edit(
    text: str,
    edit: TextEdit,
    *,
    patch_path: Path,
) -> str:
    """Apply a single `TextEdit` variant to `text`.

    Args:
        text: Input plaintext content.
        edit: Plaintext edit variant.
        patch_path: Source patch file for diagnostic reporting.

    Returns:
        Transformed plaintext content.

    Raises:
        OverlayError: If a required target or anchor string is missing.
    """
    newline = _detect_newline(text, default="\n")
    match edit:
        case ReplaceText():
            result = _replace_text(text, edit, patch_path=patch_path)
        case InsertAfter() | InsertBefore():
            result = _insert_around_anchor(
                text,
                edit,
                newline=newline,
                patch_path=patch_path,
            )
        case DeleteLines(contains=contains):
            kept = [line for line in text.splitlines() if contains not in line]
            result = newline.join(kept) + (newline if kept else "")
        case AppendText(content=content):
            prefix = (
                text if not text or text.endswith(("\n", "\r\n")) else text + newline
            )
            result = prefix + content + newline
        case PrependText(content=content):
            result = content + newline + text
        case _:
            assert_never(edit)
    return result


def apply_patch_chain(
    base_text: str,
    patches: Sequence[PatchSpec],
) -> str:
    """Apply an ordered chain of INI/map/KV and TOML text patches.

    Args:
        base_text: Initial file contents (or empty string).
        patches: Ordered patches from lowest to highest overlay layer.

    Returns:
        Final merged text.

    Raises:
        OverlayError: If reading or applying any patch fails.
    """
    current = base_text
    for spec in patches:
        try:
            raw_patch = spec.source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OverlayError.unreadable_file(
                spec.source_path,
                str(exc),
            ) from exc

        match spec.kind:
            case PatchKind.INI:
                ini_patch = parse_ini_patch(
                    raw_patch,
                    source_path=spec.source_path,
                )
                current = apply_ini_patch(current, ini_patch)
            case PatchKind.TOML:
                text_edits = parse_toml_patch(
                    raw_patch,
                    source_path=spec.source_path,
                )
                for edit in text_edits:
                    current = apply_text_edit(
                        current,
                        edit,
                        patch_path=spec.source_path,
                    )
            case _:
                assert_never(spec.kind)
    return current


class _ReplaceOp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal[TextOpKind.REPLACE]
    target: str = Field(min_length=1)
    replacement: str
    required: bool = True

    def to_edit(self) -> ReplaceText:
        return ReplaceText(
            target=self.target,
            replacement=self.replacement,
            required=self.required,
        )


class _InsertAfterOp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal[TextOpKind.INSERT_AFTER]
    anchor: str = Field(min_length=1)
    content: str
    required: bool = True

    def to_edit(self) -> InsertAfter:
        return InsertAfter(
            anchor=self.anchor,
            content=self.content,
            required=self.required,
        )


class _InsertBeforeOp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal[TextOpKind.INSERT_BEFORE]
    anchor: str = Field(min_length=1)
    content: str
    required: bool = True

    def to_edit(self) -> InsertBefore:
        return InsertBefore(
            anchor=self.anchor,
            content=self.content,
            required=self.required,
        )


class _DeleteLinesOp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal[TextOpKind.DELETE_LINES]
    contains: str = Field(min_length=1)

    def to_edit(self) -> DeleteLines:
        return DeleteLines(contains=self.contains)


class _AppendOp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal[TextOpKind.APPEND]
    content: str

    def to_edit(self) -> AppendText:
        return AppendText(content=self.content)


class _PrependOp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal[TextOpKind.PREPEND]
    content: str

    def to_edit(self) -> PrependText:
        return PrependText(content=self.content)


type _TOMLTextOperation = Annotated[
    _ReplaceOp
    | _InsertAfterOp
    | _InsertBeforeOp
    | _DeleteLinesOp
    | _AppendOp
    | _PrependOp,
    Field(discriminator="op"),
]


class _TOMLPatchDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: tuple[_TOMLTextOperation, ...] = Field(min_length=1)

    @classmethod
    def parse(cls, payload: object) -> Self:
        return cls.model_validate(payload)


def _with_parent(parent: Path, name: str) -> Path:
    return Path(name) if parent == Path() else parent / name


def _parse_ini_op(
    stripped: str,
    source_path: Path,
    line_no: int,
) -> INIKeyOp:
    if stripped.startswith(("!", "-")):
        raw_key, _, _ = stripped[1:].partition("=")
        clean_key = raw_key.strip()
        if not clean_key:
            detail = f"empty unset key on line {line_no}"
            raise OverlayError.invalid_patch(source_path, detail)
        return INIUnset(key=clean_key)

    if stripped.startswith("+"):
        _plus_key, sep, value = stripped.partition("=")
        if not sep:
            detail = f"expected '+=' on line {line_no}: {stripped!r}"
            raise OverlayError.invalid_patch(source_path, detail)
        return INIAppend(value=value.strip())

    key, sep, value = stripped.partition("=")
    if not sep:
        detail = f"expected 'Key=Value' or '!Key' on line {line_no}: {stripped!r}"
        raise OverlayError.invalid_patch(source_path, detail)

    clean_key = key.strip()
    if not clean_key:
        detail = f"empty key name on line {line_no}"
        raise OverlayError.invalid_patch(source_path, detail)
    return INISet(key=clean_key, value=value.strip())


def _detect_newline(text: str, *, default: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    return default


# A target may repeat a `[Section]` header or a key, and which copy the
# game honours is engine-specific. Edits therefore address every
# occurrence, so a patch never depends on that choice.
@dataclass(frozen=True, slots=True)
class _INIBlock:
    # One `[Section]` occurrence, or the root scope before the first
    # header (the block whose `header` is `None`).
    folded_name: str | None
    header: str | None
    body: tuple[str, ...]

    @property
    def lines(self) -> tuple[str, ...]:
        return self.body if self.header is None else (self.header, *self.body)


type _Bodies = tuple[tuple[str, ...], ...]


def _parse_ini_blocks(lines: Sequence[str]) -> tuple[_INIBlock, ...]:
    headers = [
        (idx, name)
        for idx, line in enumerate(lines)
        if (name := _extract_section_header(line)) is not None
    ]
    # Block boundaries: each header line, then end of text. The first
    # boundary also ends the root block.
    bounds = [*(idx for idx, _ in headers), len(lines)]
    sections = (
        _INIBlock(name.casefold(), lines[start], tuple(lines[start + 1 : end]))
        for (start, name), end in zip(headers, bounds[1:], strict=True)
    )
    return (_INIBlock(None, None, tuple(lines[: bounds[0]])), *sections)


def _update_ini_section(
    blocks: tuple[_INIBlock, ...],
    section: str | None,
    key_ops: Sequence[INIKeyOp],
) -> tuple[_INIBlock, ...]:
    folded_name = None if section is None else section.casefold()
    targets = [
        idx for idx, block in enumerate(blocks) if block.folded_name == folded_name
    ]
    if targets:
        bodies = _apply_key_ops(tuple(blocks[idx].body for idx in targets), key_ops)
        updated = list(blocks)
        for idx, body in zip(targets, bodies, strict=True):
            updated[idx] = replace(blocks[idx], body=body)
        return tuple(updated)

    # The root block always exists; only a named section can be absent.
    (body,) = _apply_key_ops(((),), key_ops)
    if section is None or not body:
        return blocks
    return (*_end_with_blank_line(blocks), _INIBlock(folded_name, f"[{section}]", body))


def _end_with_blank_line(blocks: tuple[_INIBlock, ...]) -> tuple[_INIBlock, ...]:
    *head, last = blocks
    if last.lines and last.lines[-1].strip():
        return (*head, replace(last, body=(*last.body, "")))
    return blocks


def _apply_key_ops(bodies: _Bodies, key_ops: Sequence[INIKeyOp]) -> _Bodies:
    current = bodies
    for op in key_ops:
        match op:
            case INIUnset(key=key):
                current = tuple(_without_key(body, key) for body in current)
            case INISet(key=key, value=value):
                current = _with_key(current, key, value)
            case INIAppend(value=value):
                index = max(_next_numeric_key(body) for body in current)
                current = _append_line(current, f"{index}={value}")
            case _:
                assert_never(op)
    return current


def _without_key(body: tuple[str, ...], key: str) -> tuple[str, ...]:
    folded_key = key.casefold()
    return tuple(line for line in body if not _has_key(line, folded_key))


def _with_key(bodies: _Bodies, key: str, value: str) -> _Bodies:
    folded_key = key.casefold()
    if not any(_has_key(line, folded_key) for body in bodies for line in body):
        return _append_line(bodies, f"{key}={value}")
    return tuple(
        tuple(
            _with_value(line, value) if _has_key(line, folded_key) else line
            for line in body
        )
        for body in bodies
    )


def _append_line(bodies: _Bodies, line: str) -> _Bodies:
    *head, last = bodies
    return (*head, _insert_at_body_tail(last, line))


def _has_key(line: str, folded_key: str) -> bool:
    found_key = _extract_key_name(line)
    return found_key is not None and found_key.casefold() == folded_key


def _with_value(line: str, value: str) -> str:
    before_eq, sep, after_eq = line.partition("=")
    leading_ws = after_eq[: len(after_eq) - len(after_eq.lstrip(" \t"))]
    return f"{before_eq}{sep}{leading_ws}{value}"


def _extract_section_header(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("[") and "]" in stripped:
        inside, _, trailing_raw = stripped[1:].partition("]")
        trailing = trailing_raw.strip()
        if not trailing or trailing.startswith((";", "#")):
            return inside.strip()
    return None


def _extract_key_value(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith((";", "#", "[")):
        return None
    raw_key, sep, raw_value = stripped.partition("=")
    if not sep:
        return None
    key = raw_key.strip()
    return (key, raw_value.strip()) if key else None


def _extract_key_name(line: str) -> str | None:
    entry = _extract_key_value(line)
    return entry[0] if entry is not None else None


def _next_numeric_key(body: Sequence[str]) -> int:
    max_index = -1
    for line in body:
        found_key = _extract_key_name(line)
        if found_key is not None and found_key.isdigit():
            max_index = max(max_index, int(found_key))
    return max_index + 1


def _insert_at_body_tail(body: tuple[str, ...], new_line: str) -> tuple[str, ...]:
    insert_at = len(body)
    while insert_at > 0 and not body[insert_at - 1].strip():
        insert_at -= 1
    return (*body[:insert_at], new_line, *body[insert_at:])


def _replace_text(
    text: str,
    edit: ReplaceText,
    *,
    patch_path: Path,
) -> str:
    if edit.target not in text:
        if edit.required:
            raise OverlayError.patch_target_not_found(patch_path, edit.target)
        return text
    return text.replace(edit.target, edit.replacement)


def _insert_around_anchor(
    text: str,
    edit: InsertAfter | InsertBefore,
    *,
    newline: str,
    patch_path: Path,
) -> str:
    lines = text.splitlines()
    out: list[str] = []
    matched = False
    inserted_lines = edit.content.splitlines()
    insert_after = isinstance(edit, InsertAfter)

    for line in lines:
        if edit.anchor in line:
            matched = True
            if insert_after:
                out.append(line)
                out.extend(inserted_lines)
            else:
                out.extend(inserted_lines)
                out.append(line)
        else:
            out.append(line)

    if not matched:
        if edit.required:
            raise OverlayError.patch_target_not_found(patch_path, edit.anchor)
        return text

    return newline.join(out) + newline
