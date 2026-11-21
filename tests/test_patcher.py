"""Tests for INI and TOML text patches."""

from pathlib import Path

import pytest

from mentara.errors import OverlayError
from mentara.layout import PatchFormat
from mentara.patcher import (
    INIAppend,
    INIDeleteSection,
    INISet,
    INIUnset,
    INIUpdateSection,
    PatchSpec,
    TextAppend,
    TextDelete,
    TextInsertAfter,
    TextInsertBefore,
    TextPrepend,
    TextReplace,
    apply_patches,
    parse_ini_patch,
    parse_toml_patch,
)

SOURCE = Path("test.patch.ini")


def test_ini_patch_parses_one_spelling_per_operation() -> None:
    patch = parse_ini_patch(
        "; comment\nRoot=1\n[A]\nKey = Value\n-Old\n+=Item\n[-B]\n",
        source_path=SOURCE,
    )

    assert patch.operations == (
        INIUpdateSection(None, (INISet("Root", "1"),)),
        INIUpdateSection(
            "A", (INISet("Key", "Value"), INIUnset("Old"), INIAppend("Item"))
        ),
        INIDeleteSection("B"),
    )


@pytest.mark.parametrize(
    "line",
    ["NoEquals", "!Old", "+Key=Value", "-Key=1", "=Value", "# comment"],
)
def test_ini_patch_rejects_other_spellings(line: str) -> None:
    with pytest.raises(
        OverlayError, match="expected 'Key=Value', '\\+=Value' or '-Key'"
    ):
        parse_ini_patch(f"[A]\n{line}\n", source_path=SOURCE)


@pytest.mark.parametrize("header", ["[]", "[-]", "[ - ]"])
def test_ini_patch_rejects_empty_section_names(header: str) -> None:
    with pytest.raises(OverlayError, match="empty section name"):
        parse_ini_patch(f"{header}\n", source_path=SOURCE)


def test_sectionless_cfg_and_inj_patches_preserve_alignment() -> None:
    base_cfg = (
        ";;; www.bitpatch.com ;;;\r\n"
        "ForceDirectDrawEmulation = 1\r\n"
        "NoVideoMemory            = 0\r\n"
        "ShowFPS                  = 0\r\n"
    )
    cfg = parse_ini_patch(
        "-NoVideoMemory\nShowFPS = 1\nCustomOption = 2\n",
        source_path=Path("aqrit.patch.cfg"),
    ).apply(base_cfg)
    assert "NoVideoMemory" not in cfg
    assert "ShowFPS                  = 1\r\n" in cfg
    assert "CustomOption=2\r\n" in cfg

    base_inj = (
        "; \\Ares.cpp\r\n"
        "52C5E0 = Ares_NoLogo, 7\r\n"
        "6AD0ED = Ares_AllowSinglePlay, 5\r\n"
    )
    inj = parse_ini_patch(
        "-6AD0ED\n52C5E0 = Custom_NoLogo, 7\n",
        source_path=Path("Ares.dll.patch.inj"),
    ).apply(base_inj)
    assert "6AD0ED" not in inj
    assert "52C5E0 = Custom_NoLogo, 7\r\n" in inj


def test_ini_patch_sets_deletes_appends_and_deletes_sections() -> None:
    base = (
        "; Header comment\r\n"
        "[Settings]\r\n"
        "GameExecutableNames=gamemd.exe\r\n"
        "GameLauncherExecutableName=Syringe.exe\r\n"
        "ForbiddenFiles=rulesmo.ini,artmo.ini\r\n"
        "\r\n"
        "[Animations]\r\n"
        "0=ANIM_A\r\n"
        "5=ANIM_B\r\n"
        "\r\n"
        "[Obsolete]\r\n"
        "DeadKey=1\r\n"
    )
    patch = parse_ini_patch(
        "[-Obsolete]\n"
        "[Settings]\n"
        "GameExecutableNames=Syringe.exe\n"
        "GameLauncherExecutableName=\n"
        "-ForbiddenFiles\n"
        "NewKey=yes\n"
        "[Animations]\n"
        "+=ANIM_C\n"
        "+=ANIM_D\n"
        "[BrandNew]\n"
        "+=FIRST_ITEM\n",
        source_path=SOURCE,
    )

    merged = patch.apply(base)

    assert "; Header comment\r\n" in merged
    assert "[Obsolete]" not in merged
    assert "DeadKey" not in merged
    assert "ForbiddenFiles" not in merged
    assert "GameExecutableNames=Syringe.exe\r\n" in merged
    assert "GameLauncherExecutableName=\r\n" in merged
    assert "NewKey=yes\r\n" in merged
    assert "6=ANIM_C\r\n7=ANIM_D\r\n" in merged
    assert "[BrandNew]\r\n0=FIRST_ITEM\r\n" in merged


def test_ini_patch_edits_every_occurrence_of_a_repeated_section() -> None:
    base = (
        "[TaskForces]\r\n0=TF_A\r\n\r\n"
        "[TF_A]\r\nName=4 Robots Water\r\n0=4,ROBOW\r\nGroup=-1\r\n\r\n"
        "[TF_A]\r\nName=2 Robots\r\n0=2,ROBO\r\n\r\n"
        "[TaskForces]\r\n1=TF_B\r\n"
    )
    patch = parse_ini_patch(
        "[TF_A]\nName=Fixed\n-Group\nMax=3\n[TaskForces]\n+=TF_C\n",
        source_path=Path("aimo.patch.ini"),
    )

    assert patch.apply(base) == (
        "[TaskForces]\r\n0=TF_A\r\n\r\n"
        "[TF_A]\r\nName=Fixed\r\n0=4,ROBOW\r\n\r\n"
        "[TF_A]\r\nName=Fixed\r\n0=2,ROBO\r\nMax=3\r\n\r\n"
        "[TaskForces]\r\n1=TF_B\r\n2=TF_C\r\n"
    )


def test_ini_patch_delete_then_redefine_collapses_a_repeated_section() -> None:
    base = (
        "[Keep]\r\nA=1\r\n[Dup]\r\n0=54,0\r\n6=0,1\r\n"
        "[Keep2]\r\nB=2\r\n[Dup]\r\n0=53,0\r\n"
    )
    patch = parse_ini_patch("[-Dup]\n[Dup]\n0=54,0\n1=0,1\n", source_path=SOURCE)

    assert patch.apply(base) == (
        "[Keep]\r\nA=1\r\n[Keep2]\r\nB=2\r\n\r\n[Dup]\r\n0=54,0\r\n1=0,1\r\n"
    )


def test_ini_patch_delete_in_an_absent_section_creates_nothing() -> None:
    patch = parse_ini_patch(
        "-Root\n[Missing]\n-Key\n[Present]\n-A\n", source_path=SOURCE
    )

    assert (
        patch.apply("; comment\nRoot=1\n[Present]\nA=1\n") == "; comment\n[Present]\n"
    )


def test_ini_patch_tolerates_hash_comments_in_the_target() -> None:
    patch = parse_ini_patch("[A]\nKey=2\n", source_path=SOURCE)

    assert patch.apply("[A] # note\n#Key=1\nKey=1\n") == "[A] # note\n#Key=1\nKey=2\n"


def test_toml_patch_applies_every_edit_in_order() -> None:
    patch = parse_toml_patch(
        """
[[edit]]
op = "prepend"
content = "; Header"

[[edit]]
op = "replace"
match = "Renderer=auto"
content = "Renderer=opengl"

[[edit]]
op = "insert_after"
match = "[Video]"
content = "; Managed by Mentara"

[[edit]]
op = "insert_before"
match = "Renderer=opengl"
content = "VSync=yes"

[[edit]]
op = "delete"
match = "RemoveThisLine"

[[edit]]
op = "append"
content = "; Footer"
""",
        source_path=Path("config.patch.toml"),
    )

    assert patch.edits == (
        TextPrepend("; Header"),
        TextReplace("Renderer=auto", "Renderer=opengl"),
        TextInsertAfter("[Video]", "; Managed by Mentara"),
        TextInsertBefore("Renderer=opengl", "VSync=yes"),
        TextDelete("RemoveThisLine"),
        TextAppend("; Footer"),
    )
    assert patch.apply("[Video]\nRenderer=auto\nRemoveThisLine=1\n") == (
        "; Header\n[Video]\n; Managed by Mentara\n"
        "VSync=yes\nRenderer=opengl\n; Footer\n"
    )


@pytest.mark.parametrize(
    "edit",
    [
        'op = "replace"\nmatch = "Missing"\ncontent = "X"',
        'op = "insert_before"\nmatch = "Missing"\ncontent = "X"',
        'op = "insert_after"\nmatch = "Missing"\ncontent = "X"',
        'op = "delete"\nmatch = "Missing"',
    ],
)
def test_toml_edits_with_a_match_fail_unless_optional(edit: str) -> None:
    source = Path("bad.patch.toml")
    required = parse_toml_patch(f"[[edit]]\n{edit}\n", source_path=source)
    optional = parse_toml_patch(
        f"[[edit]]\n{edit}\nrequired = false\n", source_path=source
    )

    with pytest.raises(OverlayError, match="Missing"):
        required.apply("Hello=World\n")
    assert optional.apply("Hello=World\n") == "Hello=World\n"


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (
            '[[edit]]\nop = "append"\ncontent = "ok"\nmatch = "x"\n',
            "Unexpected keyword",
        ),
        (
            '[[edit]]\nop = "replace"\nmatch = ""\ncontent = "x"\n',
            "at least 1 character",
        ),
        ('[[edit]]\nop = "rename"\n', "does not match any of the expected tags"),
        ("edit = []\n", "at least 1 item"),
        ('[[text]]\nop = "append"\ncontent = "x"\n', "edit"),
        ("[[edit]\n", "Invalid overlay patch"),
    ],
)
def test_toml_patch_rejects_malformed_documents(text: str, error: str) -> None:
    with pytest.raises(OverlayError, match=error):
        parse_toml_patch(text, source_path=Path("bad.patch.toml"))


def test_apply_patches_reads_each_file_in_its_format(tmp_path: Path) -> None:
    ini, toml = tmp_path / "a.patch.ini", tmp_path / "a.ini.patch.toml"
    ini.write_text("[A]\nKey=2\n", encoding="utf-8")
    toml.write_text('[[edit]]\nop = "append"\ncontent = "; end"\n', encoding="utf-8")
    specs = (
        PatchSpec(PatchFormat.INI, ini, "layer:one"),
        PatchSpec(PatchFormat.TOML, toml, "layer:two"),
    )

    assert apply_patches("[A]\r\nKey=1\r\n", specs) == "[A]\r\nKey=2\r\n; end\r\n"
    with pytest.raises(OverlayError, match="Failed to read"):
        apply_patches("", (PatchSpec(PatchFormat.INI, tmp_path / "gone", "x"),))
