"""Layer layout: where each file of an overlay layer lands, and how.

A layer mirrors the game directory. Three kinds of names are structural:

- `<archive>.mix/` is a MIX container: the files below it are members of
  that archive, and nested `<archive>.mix/` directories reach archives
  stored inside it.
- `<name>.patch.<format>` is a patch of the file it names. The format is
  the patch's own syntax:
  - INI syntax (`ini`, `map`, `yrm`, `mpr`, `cfg`, `inj`) edits
    `<name>.<format>` by section and key;
  - `mix` merges its entries into the archive `<name>.mix`;
  - `toml` is a script of line edits for any text file `<name>`.
- A patch may be a directory of that name holding fragments in its
  format (`*.ini` in `rulesmo.patch.ini/`), applied in name order as
  one patch.

Every other file supplies the file at its own path.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from mentara.errors import OverlayError

__all__ = [
    "INI_EXTENSIONS",
    "ArchivePlacement",
    "FilePlacement",
    "PatchFormat",
    "PatchName",
    "PatchPlacement",
    "Placement",
    "TextFormat",
    "is_archive_name",
    "is_structural",
    "parse_patch_name",
    "place",
    "split_archive_path",
]

INI_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {"ini", "map", "yrm", "mpr", "cfg", "inj"}
)
_PATCH_MARKER: Final[str] = ".patch."
_MIX_SUFFIX: Final[str] = ".mix"


class PatchFormat(StrEnum):
    """Syntax of a patch, named by its extension."""

    INI = "ini"
    TOML = "toml"
    MIX = "mix"


@dataclass(frozen=True, slots=True)
class PatchName:
    """What a `<name>.patch.<format>` name patches."""

    target: str
    format: PatchFormat
    fragment_suffix: str


type TextFormat = Literal[PatchFormat.INI, PatchFormat.TOML]


@dataclass(frozen=True, slots=True)
class FilePlacement:
    """A layer file that supplies a file of the virtual tree whole.

    Attributes:
        path: Virtual path of the file.
    """

    path: Path


@dataclass(frozen=True, slots=True)
class PatchPlacement:
    """A layer file that patches a text file of the virtual tree.

    Attributes:
        path: Virtual path of the patched file.
        patch: Format of the patch.
        claims: Patch file or directory the plan consumes and hides.
    """

    path: Path
    patch: TextFormat
    claims: Path


@dataclass(frozen=True, slots=True)
class ArchivePlacement:
    """A layer file that lands in a MIX archive.

    Attributes:
        archive: Virtual path of the archive.
        member: Path of the target inside the archive; empty for a MIX
            patch that merges into the archive itself.
        patch: Format of the patch, or `None` if the file supplies the
            member whole.
        claims: MIX container or patch the plan consumes. The plan hides
            it unless it materialises an entry at that path (a container
            spelt like its archive).
    """

    archive: Path
    member: tuple[str, ...]
    patch: PatchFormat | None
    claims: Path


type Placement = FilePlacement | PatchPlacement | ArchivePlacement


def parse_patch_name(name: str) -> PatchName | None:
    """Parse a `<name>.patch.<format>` file or directory name.

    Args:
        name: Last segment of a layer path; matched ignoring case.

    Returns:
        The patch's target name and format, or `None` if `name` is not a
        patch name.
    """
    marker = name.casefold().rfind(_PATCH_MARKER)
    if marker <= 0:
        return None
    stem, extension = name[:marker], name[marker + len(_PATCH_MARKER) :]
    folded = extension.casefold()
    if folded in INI_EXTENSIONS:
        return PatchName(f"{stem}.{extension}", PatchFormat.INI, f".{folded}")
    if folded == PatchFormat.MIX:
        return PatchName(f"{stem}.{extension}", PatchFormat.MIX, _MIX_SUFFIX)
    if folded == PatchFormat.TOML:
        return PatchName(stem, PatchFormat.TOML, ".toml")
    return None


def place(relative: Path) -> Placement:
    """Resolve what a file at `relative` in a layer does.

    Args:
        relative: File path relative to the layer root.

    Returns:
        The file's `Placement`.

    Raises:
        OverlayError: If the path breaks the layout: a directory other
            than a nested archive inside a MIX container, or anything
            but a fragment in the patch's format inside a patch
            directory.
    """
    *directories, leaf = relative.parts
    container_at = next(
        (index for index, part in enumerate(directories) if is_archive_name(part)),
        None,
    )
    archive = None if container_at is None else Path(*directories[: container_at + 1])
    below = directories if container_at is None else directories[container_at + 1 :]

    patch_dir = parse_patch_name(below[-1]) if below else None
    if patch_dir is not None:
        if not _is_fragment(leaf, patch_dir):
            detail = f"{below[-1]}/ holds only *{patch_dir.fragment_suffix} files"
            raise OverlayError.invalid_layout(relative, detail)
        below, patch_name = below[:-1], patch_dir
    else:
        patch_name = parse_patch_name(leaf)
    for part in below:
        if parse_patch_name(part) is not None:
            detail = f"{part}/ holds only fragments, no directories"
            raise OverlayError.invalid_layout(relative, detail)
        if archive is not None and not is_archive_name(part):
            detail = f"{part}/ inside {archive.as_posix()}/ is not a .mix archive"
            raise OverlayError.invalid_layout(relative, detail)

    name = leaf if patch_name is None else patch_name.target
    patch = None if patch_name is None else patch_name.format
    if archive is not None:
        return ArchivePlacement(archive, (*below, name), patch, claims=archive)
    claims = relative.parent if patch_dir is not None else relative
    if patch is PatchFormat.MIX:
        return ArchivePlacement(Path(*below, name), (), patch, claims=claims)
    if patch is None:
        return FilePlacement(Path(*below, name))
    return PatchPlacement(Path(*below, name), patch, claims=claims)


def is_archive_name(name: str) -> bool:
    """Return whether `name` names a MIX archive.

    Args:
        name: File or directory name; matched ignoring case.

    Returns:
        `True` for `<name>.mix`, but not for a `<name>.patch.mix` patch.
    """
    folded = name.casefold()
    return (
        folded.endswith(_MIX_SUFFIX)
        and len(folded) > len(_MIX_SUFFIX)
        and parse_patch_name(name) is None
    )


def is_structural(relative_dir: Path) -> bool:
    """Return whether a layer directory is or lies in a structural one.

    Args:
        relative_dir: Directory path relative to the layer root.

    Returns:
        `True` for MIX containers, patch directories and anything below
        them: the plan consumes them instead of mirroring them.
    """
    return any(
        is_archive_name(part) or parse_patch_name(part) is not None
        for part in relative_dir.parts
    )


def split_archive_path(path: Path) -> tuple[Path, tuple[str, ...]] | None:
    """Split a virtual path through a MIX archive at the archive.

    Args:
        path: Virtual path such as `expandmo99.mix/rulesmo.ini` or
            `ra2md.mix/localmd.mix/rulesmd.ini`.

    Returns:
        The outermost archive and the member path inside it, or `None`
        if `path` does not pass through an archive.
    """
    *directories, _ = path.parts
    for index, part in enumerate(directories):
        if is_archive_name(part):
            return Path(*path.parts[: index + 1]), path.parts[index + 1 :]
    return None


def _is_fragment(name: str, patch: PatchName) -> bool:
    folded = name.casefold()
    return folded.endswith(patch.fragment_suffix) and folded != patch.fragment_suffix
