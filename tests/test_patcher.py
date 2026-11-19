"""Tests for `.patch.ini` and `.patch.toml` text-level patching."""

lazy from pathlib import Path

import pytest

from mentara.errors import OverlayError
from mentara.patcher import (
    PatchKind,
    PatchSpec,
    apply_ini_patch,
    apply_patch_chain,
    parse_ini_patch,
    parse_patch_target,
    parse_toml_patch,
)


def test_parse_patch_target_recognizes_ini_and_toml_suffixes() -> None:
    assert parse_patch_target(Path("RA2MO.ini")) is None
    assert parse_patch_target(Path("Resources/ClientDefinitions.ini.patch.ini")) == (
        Path("Resources/ClientDefinitions.ini"),
        PatchKind.INI,
    )
    assert parse_patch_target(Path("MentalOmegaClient.exe.config.patch.toml")) == (
        Path("MentalOmegaClient.exe.config"),
        PatchKind.TOML,
    )


def test_ini_patch_set_unset_append_and_delete_section() -> None:
    base_ini = (
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
    patch_text = (
        "; Incremental INI patch\n"
        "[-Obsolete]\n"
        "[Settings]\n"
        "GameExecutableNames=Syringe.exe\n"
        "GameLauncherExecutableName=\n"
        "!ForbiddenFiles\n"
        "NewKey=yes\n"
        "[Animations]\n"
        "+=ANIM_C\n"
        "+=ANIM_D\n"
        "[BrandNew]\n"
        "+=FIRST_ITEM\n"
    )

    patch = parse_ini_patch(patch_text, source_path=Path("test.patch.ini"))
    merged = apply_ini_patch(base_ini, patch)

    assert "\r\n" in merged
    assert "; Header comment\r\n" in merged
    assert "[Obsolete]" not in merged
    assert "DeadKey" not in merged
    assert "ForbiddenFiles" not in merged
    assert "GameExecutableNames=Syringe.exe\r\n" in merged
    assert "GameLauncherExecutableName=\r\n" in merged
    assert "NewKey=yes\r\n" in merged
    assert "6=ANIM_C\r\n7=ANIM_D\r\n" in merged
    assert "[BrandNew]\r\n0=FIRST_ITEM\r\n" in merged


def test_toml_patch_applies_symmetric_plaintext_edits(
    tmp_path: Path,
) -> None:
    patch_file = tmp_path / "config.patch.toml"
    patch_file.write_text(
        """
[[text]]
op = "prepend"
content = "; Header banner"

[[text]]
op = "replace"
target = "Renderer=auto"
replacement = "Renderer=opengl"

[[text]]
op = "insert_after"
anchor = "[Video]"
content = "; Managed by Mentara"

[[text]]
op = "insert_before"
anchor = "Renderer=opengl"
content = "VSync=yes"

[[text]]
op = "delete_lines"
contains = "RemoveThisLine"

[[text]]
op = "append"
content = "; Footer"
""",
        encoding="utf-8",
    )

    base = "[Video]\nRenderer=auto\nRemoveThisLine=1\n"

    edits = parse_toml_patch(
        patch_file.read_text(encoding="utf-8"),
        source_path=patch_file,
    )
    assert len(edits) == 6

    result = apply_patch_chain(
        base,
        (PatchSpec(PatchKind.TOML, patch_file, "layer:one"),),
    )
    assert result.startswith("; Header banner\n")
    assert "; Managed by Mentara\n" in result
    assert "VSync=yes\nRenderer=opengl\n" in result
    assert "RemoveThisLine" not in result
    assert result.endswith("; Footer\n")


def test_patch_errors_on_invalid_syntax_or_missing_required_anchor(
    tmp_path: Path,
) -> None:
    bad_ini = tmp_path / "bad.patch.ini"
    bad_ini.write_text("OrphanKey=1\n", encoding="utf-8")
    with pytest.raises(OverlayError, match="outside section"):
        parse_ini_patch(
            bad_ini.read_text(encoding="utf-8"),
            source_path=bad_ini,
        )

    bad_toml = tmp_path / "bad.patch.toml"
    bad_toml.write_text(
        '[[text]]\nop = "replace"\ntarget = "MissingAnchor"\nreplacement = "X"\n',
        encoding="utf-8",
    )
    with pytest.raises(OverlayError, match="MissingAnchor"):
        apply_patch_chain(
            "Hello=World\n",
            (PatchSpec(PatchKind.TOML, bad_toml, "layer:test"),),
        )
