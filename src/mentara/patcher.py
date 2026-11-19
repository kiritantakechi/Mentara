"""Text-level and Westwood INI overlay patch parsing and merging."""

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self
lazy from collections.abc import Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    model_validator,
)

from mentara.errors import OverlayError

__all__ = [
    "INI_PATCH_SUFFIX",
    "TOML_PATCH_SUFFIX",
    "AppendText",
    "DeleteLines",
    "IniAppend",
    "IniDeleteSection",
    "IniKeyOp",
    "IniPatch",
    "IniSectionOp",
    "IniSet",
    "IniUnset",
    "IniUpdateSection",
    "InsertText",
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

INI_PATCH_SUFFIX = ".patch.ini"
TOML_PATCH_SUFFIX = ".patch.toml"


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
class IniSet:
    """Set or update `key=value` within an INI section."""

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class IniUnset:
    """Remove `key` from an INI section."""

    key: str


@dataclass(frozen=True, slots=True)
class IniAppend:
    """Append `value` at the next integer key in an INI section."""

    value: str


type IniKeyOp = IniSet | IniUnset | IniAppend


@dataclass(frozen=True, slots=True)
class IniDeleteSection:
    """Delete an entire `[section]` block from an INI document."""

    section: str


@dataclass(frozen=True, slots=True)
class IniUpdateSection:
    """Apply ordered key operations to `[section]`."""

    section: str
    operations: tuple[IniKeyOp, ...]


type IniSectionOp = IniDeleteSection | IniUpdateSection


@dataclass(frozen=True, slots=True)
class IniPatch:
    """Parsed `.patch.ini` containing ordered section operations."""

    operations: tuple[IniSectionOp, ...] = ()


@dataclass(frozen=True, slots=True)
class ReplaceText:
    """Replace occurrences of `target` with `replacement`."""

    target: str
    replacement: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class InsertText:
    """Insert `content` before or after lines matching `anchor`."""

    anchor: str
    content: str
    after: bool = True
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


type TextEdit = ReplaceText | InsertText | DeleteLines | AppendText | PrependText


class _TomlTextOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: TextOpKind
    target: str | None = None
    anchor: str | None = None
    contains: str | None = None
    replacement: str | None = None
    content: str | None = None
    required: bool = True

    @model_validator(mode="after")
    def _validate_fields(self) -> Self:
        match self.op:
            case TextOpKind.REPLACE:
                if _is_blank(self.target) or self.replacement is None:
                    msg = "replace op requires non-empty 'target' and 'replacement'"
                    raise ValueError(msg)
            case TextOpKind.INSERT_AFTER | TextOpKind.INSERT_BEFORE:
                if _is_blank(self.anchor) or self.content is None:
                    msg = (
                        f"{self.op.value} op requires non-empty 'anchor' and 'content'"
                    )
                    raise ValueError(msg)
            case TextOpKind.DELETE_LINES:
                if _is_blank(self.contains):
                    msg = "delete_lines op requires non-empty 'contains'"
                    raise ValueError(msg)
            case TextOpKind.APPEND | TextOpKind.PREPEND:
                if self.content is None:
                    msg = f"{self.op.value} op requires 'content'"
                    raise ValueError(msg)
        return self

    def to_edit(self) -> TextEdit:
        """Convert validated TOML entry into a `TextEdit` variant."""
        match self.op:
            case TextOpKind.REPLACE:
                return ReplaceText(
                    target=self.target or "",
                    replacement=self.replacement or "",
                    required=self.required,
                )
            case TextOpKind.INSERT_AFTER:
                return InsertText(
                    anchor=self.anchor or "",
                    content=self.content or "",
                    after=True,
                    required=self.required,
                )
            case TextOpKind.INSERT_BEFORE:
                return InsertText(
                    anchor=self.anchor or "",
                    content=self.content or "",
                    after=False,
                    required=self.required,
                )
            case TextOpKind.DELETE_LINES:
                return DeleteLines(contains=self.contains or "")
            case TextOpKind.APPEND:
                return AppendText(content=self.content or "")
            case TextOpKind.PREPEND:
                return PrependText(content=self.content or "")


class _TomlPatchDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: tuple[_TomlTextOperation, ...]

    @model_validator(mode="after")
    def _validate_non_empty(self) -> Self:
        if not self.text:
            msg = "patch document must define at least one [[text]] operation"
            raise ValueError(msg)
        return self


def parse_patch_target(relative_path: Path) -> tuple[Path, PatchKind] | None:
    """Resolve whether `relative_path` is `.patch.ini` or `.patch.toml`.

    Args:
        relative_path: Relative path scanned inside an overlay layer.

    Returns:
        `(target_relative_path, PatchKind)` if `relative_path` carries a
        patch suffix, otherwise `None`.
    """
    name = relative_path.name
    name_folded = name.casefold()
    for suffix, kind in (
        (INI_PATCH_SUFFIX, PatchKind.INI),
        (TOML_PATCH_SUFFIX, PatchKind.TOML),
    ):
        if name_folded.endswith(suffix) and len(name) > len(suffix):
            target_name = name[: -len(suffix)]
            target_path = (
                Path(target_name)
                if relative_path.parent == Path()
                else relative_path.parent / target_name
            )
            return target_path, kind
    return None


def parse_ini_patch(text: str, *, source_path: Path) -> IniPatch:
    """Parse an extended Westwood `.patch.ini` document.

    Supported directives inside `[Section]`:
    - `Key=Value`: set or update `Key` in `[Section]`.
    - `!Key` or `-Key`: delete `Key` from `[Section]`.
    - `+=Value` or `+Key=Value`: append `Value` using the next integer
      index in `[Section]`.
    - `[-Section]`: delete the entire `[Section]` block.

    Args:
        text: Raw UTF-8 text of the `.patch.ini` file.
        source_path: File path used for error reporting.

    Returns:
        Parsed `IniPatch`.

    Raises:
        OverlayError: If a key directive appears outside any section or
            cannot be parsed.
    """
    operations: list[IniSectionOp] = []
    current_section: str | None = None
    current_ops: list[IniKeyOp] = []

    def _flush_current() -> None:
        nonlocal current_section, current_ops
        if current_section is not None:
            operations.append(
                IniUpdateSection(
                    section=current_section,
                    operations=tuple(current_ops),
                ),
            )
            current_section = None
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
                    IniDeleteSection(section=header[1:].strip()),
                )
            else:
                current_section = header
            continue

        if current_section is None:
            detail = f"entry outside section on line {line_no}: {stripped!r}"
            raise OverlayError.invalid_patch(source_path, detail)

        current_ops.append(_parse_ini_op(stripped, source_path, line_no))

    _flush_current()
    return IniPatch(operations=tuple(operations))


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
        doc = _TomlPatchDocument.model_validate(payload)
    except ValidationError as exc:
        raise OverlayError.invalid_patch(source_path, str(exc)) from exc

    return tuple(item.to_edit() for item in doc.text)


def apply_ini_patch(
    base_text: str,
    patch: IniPatch,
    *,
    default_newline: str = "\r\n",
) -> str:
    """Apply an `IniPatch` while preserving comments and line endings.

    Args:
        base_text: Existing INI text (empty string if creating a file).
        patch: Structured section and key operations.
        default_newline: Line ending used when `base_text` has no lines.

    Returns:
        Updated INI text.
    """
    if not patch.operations:
        return base_text

    newline = _detect_newline(base_text, default=default_newline)
    lines = base_text.splitlines()

    for section_op in patch.operations:
        match section_op:
            case IniDeleteSection(section=section):
                lines = _delete_ini_section(lines, section)
            case IniUpdateSection(section=section, operations=key_ops):
                for op in key_ops:
                    lines = _apply_ini_key_op(lines, section, op)

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
        case ReplaceText(
            target=target,
            replacement=replacement,
            required=required,
        ):
            if target not in text:
                if required:
                    raise OverlayError.patch_target_not_found(
                        patch_path,
                        target,
                    )
                return text
            return text.replace(target, replacement)
        case InsertText():
            return _insert_around_anchor(
                text,
                edit=edit,
                newline=newline,
                patch_path=patch_path,
            )
        case DeleteLines(contains=contains):
            kept = [line for line in text.splitlines() if contains not in line]
            return newline.join(kept) + (newline if kept else "")
        case AppendText(content=content):
            prefix = (
                text if not text or text.endswith(("\n", "\r\n")) else text + newline
            )
            return prefix + content + newline
        case PrependText(content=content):
            return content + newline + text


def apply_patch_chain(
    base_text: str,
    patches: Sequence[PatchSpec],
) -> str:
    """Apply an ordered chain of `.patch.ini` and `.patch.toml` files.

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
            raise OverlayError.invalid_patch(
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
    return current


def _parse_ini_op(
    stripped: str,
    source_path: Path,
    line_no: int,
) -> IniKeyOp:
    if stripped.startswith(("!", "-")):
        raw_key = stripped[1:].strip()
        if "=" in raw_key:
            raw_key = raw_key.split("=", 1)[0].strip()
        if not raw_key:
            detail = f"empty unset key on line {line_no}"
            raise OverlayError.invalid_patch(source_path, detail)
        return IniUnset(key=raw_key)

    if stripped.startswith("+"):
        if "=" not in stripped:
            detail = f"expected '+=' on line {line_no}: {stripped!r}"
            raise OverlayError.invalid_patch(source_path, detail)
        _plus_key, value = stripped.split("=", 1)
        return IniAppend(value=value.strip())

    if "=" not in stripped:
        detail = f"expected 'Key=Value' or '!Key' on line {line_no}: {stripped!r}"
        raise OverlayError.invalid_patch(source_path, detail)

    key, value = stripped.split("=", 1)
    clean_key = key.strip()
    if not clean_key:
        detail = f"empty key name on line {line_no}"
        raise OverlayError.invalid_patch(source_path, detail)
    return IniSet(key=clean_key, value=value.strip())


def _is_blank(value: str | None) -> bool:
    return value is None or value == ""


def _detect_newline(text: str, *, default: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    return default


def _find_section_span(
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


def _extract_section_header(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("[") and "]" in stripped:
        closing = stripped.find("]")
        trailing = stripped[closing + 1 :].strip()
        if not trailing or trailing.startswith((";", "#")):
            return stripped[1:closing].strip()
    return None


def _extract_key_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith((";", "#", "[")):
        return None
    if "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].strip()
    return key or None


def _delete_ini_section(lines: list[str], section: str) -> list[str]:
    span = _find_section_span(lines, section)
    if span is None:
        return lines
    start, end = span
    return [*lines[:start], *lines[end:]]


def _apply_ini_key_op(
    lines: list[str],
    section: str,
    op: IniKeyOp,
) -> list[str]:
    span = _find_section_span(lines, section)
    if span is None:
        match op:
            case IniUnset():
                return lines
            case IniSet(key=key, value=value):
                entry_line = f"{key}={value}"
            case IniAppend(value=value):
                entry_line = f"0={value}"
        updated = list(lines)
        if updated and updated[-1].strip():
            updated.append("")
        updated.extend((f"[{section}]", entry_line))
        return updated

    start, end = span
    match op:
        case IniUnset(key=key):
            return _unset_key_in_span(lines, start, end, key)
        case IniSet(key=key, value=value):
            return _set_key_in_span(lines, start, end, key, value)
        case IniAppend(value=value):
            next_key = str(_next_numeric_key(lines, start, end))
            return _insert_at_section_tail(
                lines,
                start,
                end,
                f"{next_key}={value}",
            )


def _unset_key_in_span(
    lines: list[str],
    start: int,
    end: int,
    key: str,
) -> list[str]:
    target = key.casefold()
    kept_section = [
        line
        for line in lines[start + 1 : end]
        if (_extract_key_name(line) or "").casefold() != target
    ]
    return [*lines[: start + 1], *kept_section, *lines[end:]]


def _set_key_in_span(
    lines: list[str],
    start: int,
    end: int,
    key: str,
    value: str,
) -> list[str]:
    target = key.casefold()
    updated = list(lines)
    for idx in range(start + 1, end):
        found_key = _extract_key_name(updated[idx])
        if found_key is not None and found_key.casefold() == target:
            updated[idx] = f"{found_key}={value}"
            return updated
    return _insert_at_section_tail(updated, start, end, f"{key}={value}")


def _next_numeric_key(lines: Sequence[str], start: int, end: int) -> int:
    max_index = -1
    for idx in range(start + 1, end):
        found_key = _extract_key_name(lines[idx])
        if found_key is not None and found_key.isdigit():
            max_index = max(max_index, int(found_key))
    return max_index + 1


def _insert_at_section_tail(
    lines: list[str],
    start: int,
    end: int,
    new_line: str,
) -> list[str]:
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    return [*lines[:insert_at], new_line, *lines[insert_at:]]


def _insert_around_anchor(
    text: str,
    *,
    edit: InsertText,
    newline: str,
    patch_path: Path,
) -> str:
    lines = text.splitlines()
    out: list[str] = []
    matched = False
    inserted_lines = edit.content.splitlines()

    for line in lines:
        if edit.anchor in line:
            matched = True
            if edit.after:
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
