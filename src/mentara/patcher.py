"""Text-level INI/map/KV and TOML overlay patch merging."""

import tomllib
from dataclasses import dataclass
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

    Args:
        relative_path: Relative path scanned inside an overlay layer.

    Returns:
        `(target_relative_path, PatchKind)` if `relative_path` is a
        patch file, otherwise `None`.
    """
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
    top-level root scope (for sectionless `.cfg` and `.inj` files):
    - `Key=Value`: set or update `Key` (preserving spacing around `=`).
    - `!Key` or `-Key`: delete `Key`.
    - `+=Value` or `+Key=Value`: append `Value` using the next integer
      index in the current section.
    - `[-Section]`: delete the entire `[Section]` block.

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
    lines = base_text.splitlines()

    for section_op in patch.operations:
        match section_op:
            case INIDeleteSection(section=section):
                lines = _delete_ini_section(lines, section)
            case INIUpdateSection(section=section, operations=key_ops):
                lines = _apply_ini_section_update(lines, section, key_ops)
            case _:
                assert_never(section_op)

    if not lines:
        return ""
    return newline.join(lines) + newline


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


def _find_section_header_span(
    lines: Sequence[str],
    section: str,
) -> tuple[int, int] | None:
    target = section.casefold()
    start_idx: int | None = None
    for idx, raw_line in enumerate(lines):
        header = _extract_section_header(raw_line)
        if header is None:
            continue
        if start_idx is None:
            if header.casefold() == target:
                start_idx = idx
        else:
            return start_idx, idx
    if start_idx is not None:
        return start_idx, len(lines)
    return None


def _root_body_span(lines: Sequence[str]) -> tuple[int, int]:
    for idx, raw_line in enumerate(lines):
        if _extract_section_header(raw_line) is not None:
            return 0, idx
    return 0, len(lines)


def _find_section_body_span(
    lines: Sequence[str],
    section: str,
) -> tuple[int, int] | None:
    header_span = _find_section_header_span(lines, section)
    if header_span is None:
        return None
    return header_span[0] + 1, header_span[1]


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


def _delete_ini_section(lines: list[str], section: str) -> list[str]:
    span = _find_section_header_span(lines, section)
    if span is None:
        return lines
    start, end = span
    return [*lines[:start], *lines[end:]]


def _apply_ini_section_update(
    lines: list[str],
    section: str | None,
    key_ops: Sequence[INIKeyOp],
) -> list[str]:
    if section is None:
        body_start, body_end = _root_body_span(lines)
        updated_body = _apply_key_ops_to_body(lines[body_start:body_end], key_ops)
        return [*lines[:body_start], *updated_body, *lines[body_end:]]

    body_span = _find_section_body_span(lines, section)
    if body_span is None:
        new_body = _apply_key_ops_to_body([], key_ops)
        if not new_body:
            return lines
        updated = list(lines)
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(f"[{section}]")
        updated.extend(new_body)
        return updated

    body_start, body_end = body_span
    updated_body = _apply_key_ops_to_body(lines[body_start:body_end], key_ops)
    return [*lines[:body_start], *updated_body, *lines[body_end:]]


def _apply_key_ops_to_body(
    body: list[str],
    key_ops: Sequence[INIKeyOp],
) -> list[str]:
    current = list(body)
    for op in key_ops:
        match op:
            case INIUnset(key=key):
                current = _unset_key_in_body(current, key)
            case INISet(key=key, value=value):
                current = _set_key_in_body(current, key, value)
            case INIAppend(value=value):
                next_key = str(_next_numeric_key(current))
                current = _insert_at_body_tail(current, f"{next_key}={value}")
            case _:
                assert_never(op)
    return current


def _unset_key_in_body(body: list[str], key: str) -> list[str]:
    target = key.casefold()
    return [
        line for line in body if (_extract_key_name(line) or "").casefold() != target
    ]


def _set_key_in_body(body: list[str], key: str, value: str) -> list[str]:
    target = key.casefold()
    updated = list(body)
    for idx, raw_line in enumerate(updated):
        found_key = _extract_key_name(raw_line)
        if found_key is not None and found_key.casefold() == target:
            before_eq, sep, after_eq = raw_line.partition("=")
            leading_ws = after_eq[: len(after_eq) - len(after_eq.lstrip(" \t"))]
            updated[idx] = f"{before_eq}{sep}{leading_ws}{value}"
            return updated
    return _insert_at_body_tail(updated, f"{key}={value}")


def _next_numeric_key(body: Sequence[str]) -> int:
    max_index = -1
    for line in body:
        found_key = _extract_key_name(line)
        if found_key is not None and found_key.isdigit():
            max_index = max(max_index, int(found_key))
    return max_index + 1


def _insert_at_body_tail(body: list[str], new_line: str) -> list[str]:
    insert_at = len(body)
    while insert_at > 0 and not body[insert_at - 1].strip():
        insert_at -= 1
    return [*body[:insert_at], new_line, *body[insert_at:]]


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
