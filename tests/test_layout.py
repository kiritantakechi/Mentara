"""Tests for the layer layout grammar."""

from pathlib import Path

import pytest

from mentara.errors import OverlayError
from mentara.layout import (
    ArchivePlacement,
    FilePlacement,
    PatchFormat,
    PatchName,
    PatchPlacement,
    is_archive_name,
    is_structural,
    parse_patch_name,
    place,
    split_archive_path,
)

INI, TOML, MIX = PatchFormat.INI, PatchFormat.TOML, PatchFormat.MIX


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "ClientDefinitions.patch.ini",
            PatchName("ClientDefinitions.ini", INI, ".ini"),
        ),
        ("c_aberration.patch.MAP", PatchName("c_aberration.MAP", INI, ".map")),
        ("duel.patch.yrm", PatchName("duel.yrm", INI, ".yrm")),
        ("classic.patch.mpr", PatchName("classic.mpr", INI, ".mpr")),
        ("aqrit.patch.cfg", PatchName("aqrit.cfg", INI, ".cfg")),
        ("Ares.dll.patch.inj", PatchName("Ares.dll.inj", INI, ".inj")),
        ("expandmo99.patch.mix", PatchName("expandmo99.mix", MIX, ".mix")),
        ("Client.exe.config.patch.toml", PatchName("Client.exe.config", TOML, ".toml")),
        ("RA2MO.ini", None),
        (".patch.ini", None),
        ("a.patch.txt", None),
        ("a.patch.ini.bak", None),
    ],
)
def test_patch_names_carry_their_format_as_extension(
    name: str, expected: PatchName | None
) -> None:
    assert parse_patch_name(name) == expected


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("Ares.dll", FilePlacement(Path("Ares.dll"))),
        ("Maps/duel.yrm", FilePlacement(Path("Maps/duel.yrm"))),
        (
            "Resources/Client.patch.ini",
            PatchPlacement(
                Path("Resources/Client.ini"), INI, Path("Resources/Client.patch.ini")
            ),
        ),
        (
            "Resources/Client.patch.ini/b.ini",
            PatchPlacement(
                Path("Resources/Client.ini"), INI, Path("Resources/Client.patch.ini")
            ),
        ),
        (
            "app.exe.config.patch.toml/1.toml",
            PatchPlacement(
                Path("app.exe.config"), TOML, Path("app.exe.config.patch.toml")
            ),
        ),
        (
            "expandmo99.patch.mix",
            ArchivePlacement(
                Path("expandmo99.mix"), (), MIX, Path("expandmo99.patch.mix")
            ),
        ),
        (
            "expandmo99.patch.mix/b.mix",
            ArchivePlacement(
                Path("expandmo99.mix"), (), MIX, Path("expandmo99.patch.mix")
            ),
        ),
        (
            "expandmo99.mix/place.shp",
            ArchivePlacement(
                Path("expandmo99.mix"), ("place.shp",), None, Path("expandmo99.mix")
            ),
        ),
        (
            "expandmo99.mix/rulesmo.patch.ini/allied.ini",
            ArchivePlacement(
                Path("expandmo99.mix"), ("rulesmo.ini",), INI, Path("expandmo99.mix")
            ),
        ),
        (
            "ra2md.mix/localmd.mix/rulesmd.patch.ini",
            ArchivePlacement(
                Path("ra2md.mix"),
                ("localmd.mix", "rulesmd.ini"),
                INI,
                Path("ra2md.mix"),
            ),
        ),
        (
            "ra2md.mix/localmd.patch.mix",
            ArchivePlacement(
                Path("ra2md.mix"), ("localmd.mix",), MIX, Path("ra2md.mix")
            ),
        ),
        (
            "Maps/maps.mix/a.ini",
            ArchivePlacement(
                Path("Maps/maps.mix"), ("a.ini",), None, Path("Maps/maps.mix")
            ),
        ),
    ],
)
def test_every_layer_file_has_one_placement(relative: str, expected: object) -> None:
    assert place(Path(relative)) == expected


@pytest.mark.parametrize(
    ("relative", "error"),
    [
        ("rules.patch.ini/notes.md", r"rules\.patch\.ini/ holds only \*\.ini files"),
        ("rules.patch.ini/.ini", r"holds only \*\.ini files"),
        ("a.cfg.patch.toml/b.ini", r"holds only \*\.toml files"),
        ("rules.patch.ini/sub/c.ini", r"rules\.patch\.ini/ holds only fragments"),
        ("x.mix/r.patch.ini/s/a.ini", r"r\.patch\.ini/ holds only fragments"),
        ("x.mix/sub/a.ini", r"sub/ inside x\.mix/ is not a \.mix archive"),
    ],
)
def test_misplaced_files_are_errors(relative: str, error: str) -> None:
    with pytest.raises(OverlayError, match=error):
        place(Path(relative))


def test_structural_directories_and_archive_names() -> None:
    assert is_archive_name("EXPANDMO99.MIX")
    assert not is_archive_name("expandmo99.patch.mix")
    assert not is_archive_name(".mix")
    assert is_structural(Path("expandmo99.mix/sub"))
    assert is_structural(Path("Resources/Client.patch.ini"))
    assert is_structural(Path("expandmo99.patch.mix"))
    assert not is_structural(Path("Resources/Maps"))


def test_virtual_paths_split_at_the_outermost_archive() -> None:
    assert split_archive_path(Path("expandmo99.mix/rulesmo.ini")) == (
        Path("expandmo99.mix"),
        ("rulesmo.ini",),
    )
    assert split_archive_path(Path("ra2md.mix/localmd.mix/rulesmd.ini")) == (
        Path("ra2md.mix"),
        ("localmd.mix", "rulesmd.ini"),
    )
    assert split_archive_path(Path("RA2MO.ini")) is None
    assert split_archive_path(Path("expandmo99.mix")) is None
