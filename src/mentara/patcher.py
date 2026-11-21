"""Text patches: INI section and key edits, and TOML line-edit scripts.

INI patches (any INI-syntax target, with or without sections):

- `[Section]` selects a section; lines above the first header edit the
  root scope of sectionless files such as `.cfg` and `.inj`.
- `Key=Value` sets every `Key` line, or adds it if there is none.
- `+=Value` adds `Value` under the next free integer key.
- `-Key` deletes every `Key` line; `[-Section]` deletes the section.
- `;` starts a comment.

A section repeated in the target is edited in every copy, so the result
does not depend on which copy the engine reads.

TOML patches are an array of `[[edit]]` tables, each with an `op`:

- `replace`: every occurrence of `match` becomes `content`;
- `insert_before` / `insert_after`: the `content` lines go before or
  after every line containing `match`;
- `delete`: every line containing `match` goes;
- `prepend` / `append`: `content` goes at the start or the end.

An edit with a `match` fails when nothing matches, unless it sets
`required = false`.
"""

import tomllib
from dataclasses import dataclass, replace
from typing import Annotated, Final, Literal, assert_never
lazy from collections.abc import Callable, Sequence
lazy from pathlib import Path

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

from mentara.errors import OverlayError
from mentara.layout import PatchFormat, TextFormat

__all__ = [
    "INIAppend",
    "INIDeleteSection",
    "INIKeyOp",
    "INIPatch",
    "INISectionOp",
    "INISet",
    "INIUnset",
    "INIUpdateSection",
    "Patch",
    "PatchSpec",
    "TextAppend",
    "TextDelete",
    "TextEdit",
    "TextInsertAfter",
    "TextInsertBefore",
    "TextPatch",
    "TextPrepend",
    "TextReplace",
    "apply_patches",
    "load_patch",
    "parse_ini_patch",
    "parse_toml_patch",
]

# Westwood files use CRLF; a patch that creates one does too.
_INI_NEWLINE: Final[str] = "\r\n"
_TEXT_NEWLINE: Final[str] = "\n"
_STRICT: Final[ConfigDict] = ConfigDict(extra="forbid")
# Comment markers in target files, which are not always Westwood's; a
# patch's own comments start with `;` only.
_COMMENTS: Final[tuple[str, ...]] = (";", "#")


@dataclass(frozen=True, slots=True)
class PatchSpec:
    """A text patch file of a layer, in INI or TOML format."""

    format: TextFormat
    source_path: Path
    layer_label: str


@dataclass(frozen=True, slots=True)
class INISet:
    """`Key=Value`: set or add a key."""

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class INIUnset:
    """`-Key`: delete a key."""

    key: str


@dataclass(frozen=True, slots=True)
class INIAppend:
    """`+=Value`: add a value under the next free integer key."""

    value: str


type INIKeyOp = INISet | INIUnset | INIAppend


@dataclass(frozen=True, slots=True)
class INIUpdateSection:
    """`[Section]` and its key operations; `None` is the root scope."""

    section: str | None
    operations: tuple[INIKeyOp, ...]


@dataclass(frozen=True, slots=True)
class INIDeleteSection:
    """`[-Section]`: delete every copy of a section."""

    section: str


type INISectionOp = INIUpdateSection | INIDeleteSection


@dataclass(frozen=True, slots=True)
class INIPatch:
    """Parsed INI patch: section operations in file order."""

    source_path: Path
    operations: tuple[INISectionOp, ...] = ()

    def apply(self, text: str) -> str:
        """Apply the patch, keeping comments and line endings.

        Args:
            text: Target text (empty to create the file).

        Returns:
            The patched text.
        """
        if not self.operations:
            return text
        blocks = _parse_ini_blocks(text.splitlines())
        for operation in self.operations:
            match operation:
                case INIUpdateSection(section=section, operations=key_ops):
                    blocks = _update_ini_section(blocks, section, key_ops)
                case INIDeleteSection(section=section):
                    folded = section.casefold()
                    blocks = tuple(b for b in blocks if b.folded_name != folded)
                case _:
                    assert_never(operation)
        lines = [line for block in blocks for line in block.lines]
        newline = _detect_newline(text, default=_INI_NEWLINE)
        return newline.join(lines) + newline if lines else ""


@dataclass(frozen=True, slots=True)
class TextReplace:
    """Replace every occurrence of `match` with `content`."""

    __pydantic_config__ = _STRICT
    match: Annotated[str, Field(min_length=1)]
    content: str
    required: bool = True
    op: Literal["replace"] = "replace"


@dataclass(frozen=True, slots=True)
class TextInsertBefore:
    """Insert the `content` lines before each line with `match`."""

    __pydantic_config__ = _STRICT
    match: Annotated[str, Field(min_length=1)]
    content: str
    required: bool = True
    op: Literal["insert_before"] = "insert_before"


@dataclass(frozen=True, slots=True)
class TextInsertAfter:
    """Insert the `content` lines after each line with `match`."""

    __pydantic_config__ = _STRICT
    match: Annotated[str, Field(min_length=1)]
    content: str
    required: bool = True
    op: Literal["insert_after"] = "insert_after"


@dataclass(frozen=True, slots=True)
class TextDelete:
    """Delete every line containing `match`."""

    __pydantic_config__ = _STRICT
    match: Annotated[str, Field(min_length=1)]
    required: bool = True
    op: Literal["delete"] = "delete"


@dataclass(frozen=True, slots=True)
class TextPrepend:
    """Put `content` at the start of the text."""

    __pydantic_config__ = _STRICT
    content: str
    op: Literal["prepend"] = "prepend"


@dataclass(frozen=True, slots=True)
class TextAppend:
    """Put `content` at the end of the text."""

    __pydantic_config__ = _STRICT
    content: str
    op: Literal["append"] = "append"


type TextEdit = (
    TextReplace
    | TextInsertBefore
    | TextInsertAfter
    | TextDelete
    | TextPrepend
    | TextAppend
)


@dataclass(frozen=True, slots=True)
class _TOMLDocument:
    __pydantic_config__ = _STRICT
    edit: Annotated[
        tuple[Annotated[TextEdit, Field(discriminator="op")], ...],
        Field(min_length=1),
    ]


_TOML_DOCUMENT: Final[TypeAdapter[_TOMLDocument]] = TypeAdapter(_TOMLDocument)


@dataclass(frozen=True, slots=True)
class TextPatch:
    """Parsed TOML patch: line edits in file order."""

    source_path: Path
    edits: tuple[TextEdit, ...]

    def apply(self, text: str) -> str:
        """Apply every edit in order.

        Args:
            text: Target text.

        Returns:
            The patched text.

        Raises:
            OverlayError: If a required `match` is not found.
        """
        for edit in self.edits:
            text = self._apply_edit(text, edit)
        return text

    def _apply_edit(self, text: str, edit: TextEdit) -> str:
        newline = _detect_newline(text, default=_TEXT_NEWLINE)
        match edit:
            case TextReplace(match=needle, content=content, required=required):
                self._require(needle, found=needle in text, required=required)
                return text.replace(needle, content)
            case TextInsertBefore(match=needle, content=content, required=required):
                lines = _edit_lines(
                    text, needle, lambda line: (*content.splitlines(), line)
                )
                self._require(needle, found=lines is not None, required=required)
                return text if lines is None else _join_lines(lines, newline)
            case TextInsertAfter(match=needle, content=content, required=required):
                lines = _edit_lines(
                    text, needle, lambda line: (line, *content.splitlines())
                )
                self._require(needle, found=lines is not None, required=required)
                return text if lines is None else _join_lines(lines, newline)
            case TextDelete(match=needle, required=required):
                lines = _edit_lines(text, needle, lambda _: ())
                self._require(needle, found=lines is not None, required=required)
                return text if lines is None else _join_lines(lines, newline)
            case TextPrepend(content=content):
                return content + newline + text
            case TextAppend(content=content):
                ended = not text or text.endswith(("\n", "\r\n"))
                return (text if ended else text + newline) + content + newline
            case _:
                assert_never(edit)

    def _require(self, needle: str, *, found: bool, required: bool) -> None:
        if required and not found:
            raise OverlayError.patch_target_not_found(self.source_path, needle)


type Patch = INIPatch | TextPatch


def parse_ini_patch(text: str, *, source_path: Path) -> INIPatch:
    """Parse an INI patch.

    Args:
        text: Patch text.
        source_path: Patch file, for error messages.

    Returns:
        The parsed `INIPatch`.

    Raises:
        OverlayError: If a header or key line is malformed.
    """
    operations: list[INISectionOp] = []
    section: str | None = None
    key_ops: list[INIKeyOp] = []

    def flush() -> None:
        if key_ops:
            operations.append(INIUpdateSection(section, tuple(key_ops)))
            key_ops.clear()

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            flush()
            header = line[1:-1].strip()
            if header.startswith("-"):
                operations.append(
                    INIDeleteSection(_named(header[1:], line_no, source_path))
                )
                section = None
            else:
                section = _named(header, line_no, source_path)
            continue
        key_ops.append(_parse_ini_key_op(line, line_no, source_path))
    flush()
    return INIPatch(source_path, tuple(operations))


def parse_toml_patch(text: str, *, source_path: Path) -> TextPatch:
    """Parse a TOML patch.

    Args:
        text: Patch text.
        source_path: Patch file, for error messages.

    Returns:
        The parsed `TextPatch`.

    Raises:
        OverlayError: If the TOML is invalid or an edit is malformed.
    """
    try:
        document = _TOML_DOCUMENT.validate_python(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise OverlayError.invalid_patch(source_path, str(exc)) from exc
    return TextPatch(source_path, document.edit)


def load_patch(spec: PatchSpec) -> Patch:
    """Read and parse a patch file.

    Args:
        spec: The patch file and its format.

    Returns:
        The parsed patch.

    Raises:
        OverlayError: If the file cannot be read or does not parse.
    """
    try:
        text = spec.source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OverlayError.unreadable_file(spec.source_path, str(exc)) from exc
    match spec.format:
        case PatchFormat.INI:
            return parse_ini_patch(text, source_path=spec.source_path)
        case PatchFormat.TOML:
            return parse_toml_patch(text, source_path=spec.source_path)
        case _:
            assert_never(spec.format)


def apply_patches(text: str, specs: Sequence[PatchSpec]) -> str:
    """Apply patch files in order, lowest layer first.

    Args:
        text: Target text (empty to create the file).
        specs: Patch files to apply.

    Returns:
        The patched text.

    Raises:
        OverlayError: If a patch cannot be read, parsed or applied.
    """
    for spec in specs:
        text = load_patch(spec).apply(text)
    return text


def _named(name: str, line_no: int, source_path: Path) -> str:
    name = name.strip()
    if not name:
        detail = f"empty section name on line {line_no}"
        raise OverlayError.invalid_patch(source_path, detail)
    return name


def _parse_ini_key_op(line: str, line_no: int, source_path: Path) -> INIKeyOp:
    key, sep, value = line.partition("=")
    key, value = key.strip(), value.strip()
    if key.startswith("-") and not sep and key[1:].strip():
        return INIUnset(key[1:].strip())
    if key == "+" and sep:
        return INIAppend(value)
    if key and sep and not key.startswith(("-", "+", "!", "#")):
        return INISet(key, value)
    detail = f"expected 'Key=Value', '+=Value' or '-Key' on line {line_no}: {line!r}"
    raise OverlayError.invalid_patch(source_path, detail)


def _detect_newline(text: str, *, default: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    return default


def _join_lines(lines: Sequence[str], newline: str) -> str:
    return newline.join(lines) + newline if lines else ""


def _edit_lines(
    text: str,
    needle: str,
    edit: Callable[[str], tuple[str, ...]],
) -> list[str] | None:
    # Lines with `needle` become `edit(line)`; `None` if there are none.
    lines = text.splitlines()
    if not any(needle in line for line in lines):
        return None
    return [
        part for line in lines for part in (edit(line) if needle in line else (line,))
    ]


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
        (index, name)
        for index, line in enumerate(lines)
        if (name := _section_name(line)) is not None
    ]
    # Block boundaries: each header line, then end of text. The first
    # boundary also ends the root block.
    bounds = [*(index for index, _ in headers), len(lines)]
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
    folded = None if section is None else section.casefold()
    targets = [
        index for index, block in enumerate(blocks) if block.folded_name == folded
    ]
    if targets:
        bodies = _apply_key_ops(tuple(blocks[index].body for index in targets), key_ops)
        updated = list(blocks)
        for index, body in zip(targets, bodies, strict=True):
            updated[index] = replace(blocks[index], body=body)
        return tuple(updated)

    # The root block always exists; only a named section can be absent.
    (body,) = _apply_key_ops(((),), key_ops)
    if section is None or not body:
        return blocks
    return (*_end_with_blank_line(blocks), _INIBlock(folded, f"[{section}]", body))


def _end_with_blank_line(blocks: tuple[_INIBlock, ...]) -> tuple[_INIBlock, ...]:
    *head, last = blocks
    if last.lines and last.lines[-1].strip():
        return (*head, replace(last, body=(*last.body, "")))
    return blocks


def _apply_key_ops(bodies: _Bodies, key_ops: Sequence[INIKeyOp]) -> _Bodies:
    current: _Bodies = bodies
    for op in key_ops:
        match op:
            case INISet(key=key, value=value):
                current = _with_key(current, key, value)
            case INIUnset(key=key):
                current = _without_key(current, key)
            case INIAppend(value=value):
                index = max(_next_free_index(body) for body in current)
                current = _append_line(current, f"{index}={value}")
            case _:
                assert_never(op)
    return current


def _without_key(bodies: _Bodies, key: str) -> _Bodies:
    folded = key.casefold()
    return tuple(
        tuple(line for line in body if _key_of(line) != folded) for body in bodies
    )


def _with_key(bodies: _Bodies, key: str, value: str) -> _Bodies:
    folded = key.casefold()
    if not any(_key_of(line) == folded for body in bodies for line in body):
        return _append_line(bodies, f"{key}={value}")
    return tuple(
        tuple(
            _with_value(line, value) if _key_of(line) == folded else line
            for line in body
        )
        for body in bodies
    )


def _append_line(bodies: _Bodies, line: str) -> _Bodies:
    *head, last = bodies
    # A new key goes after the last key, before the trailing blanks.
    end = len(last)
    while end > 0 and not last[end - 1].strip():
        end -= 1
    return (*head, (*last[:end], line, *last[end:]))


def _with_value(line: str, value: str) -> str:
    before, sep, after = line.partition("=")
    spacing = after[: len(after) - len(after.lstrip(" \t"))]
    return f"{before}{sep}{spacing}{value}"


def _section_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("[") or "]" not in stripped:
        return None
    inside, _, trailing = stripped[1:].partition("]")
    trailing = trailing.strip()
    return inside.strip() if not trailing or trailing.startswith(_COMMENTS) else None


def _key_of(line: str) -> str | None:
    # The folded key of a `Key=Value` line, or `None` for anything else.
    stripped = line.strip()
    if not stripped or stripped.startswith((*_COMMENTS, "[")):
        return None
    key, sep, _ = stripped.partition("=")
    key = key.strip()
    return key.casefold() if sep and key else None


def _next_free_index(body: Sequence[str]) -> int:
    keys = (_key_of(line) for line in body)
    indices = [int(key) for key in keys if key is not None and key.isdigit()]
    return max(indices, default=-1) + 1
