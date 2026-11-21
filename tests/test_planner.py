"""Tests for overlay planning, shadowing, and case collisions."""

from pathlib import Path

import pytest

from mentara.errors import OverlayError
from mentara.planner import (
    EntryOrigin,
    LayerSource,
    Materialization,
    build_overlay_plan,
    render_entry_text,
)


def test_build_overlay_plan_resolves_priority_and_shadows(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    layer_one = tmp_path / "layer1"
    layer_two = tmp_path / "layer2"
    state = tmp_path / "state"

    (base / "Mentara").mkdir(parents=True)
    (base / "Mentara" / "secret.py").write_text("ignored", encoding="utf-8")
    (base / "INI").mkdir(parents=True)
    (base / "ra2.mix").write_bytes(b"mixdata")
    (base / "ddraw.dll").write_bytes(b"base-dll")
    (base / "RA2MO.ini").write_text("[Options]\nSpeed=1\n", encoding="utf-8")
    (base / "INI" / "BattleClient.ini").write_text("base", encoding="utf-8")

    (layer_one / "INI").mkdir(parents=True)
    (layer_one / "ddraw.dll").write_bytes(b"layer1-dll")
    (layer_one / "INI" / "BattleClient.ini").write_text(
        "layer1",
        encoding="utf-8",
    )
    (layer_one / ".gitkeep").write_text("", encoding="utf-8")

    layer_two.mkdir()
    (layer_two / "ddraw.dll").write_bytes(b"layer2-dll")
    (layer_two / "Phobos.dll").write_bytes(b"phobos")

    state.mkdir()
    (state / "RA2MO.ini").write_text("[Options]\nSpeed=5\n", encoding="utf-8")
    (state / ".wh..wh..opq").write_text("", encoding="utf-8")

    plan = build_overlay_plan(
        (
            LayerSource(
                "base",
                base,
                EntryOrigin.BASE,
                exclude=("Mentara", ".gitkeep"),
            ),
            LayerSource(
                "layer:one",
                layer_one,
                EntryOrigin.LAYER,
                exclude=(".gitkeep",),
            ),
            LayerSource("layer:two", layer_two, EntryOrigin.LAYER),
            LayerSource("state", state, EntryOrigin.STATE, required=False),
        ),
        copy_patterns=("*.ini",),
    )

    by_path = {entry.relative_path.as_posix(): entry for entry in plan.entries}
    assert "Mentara/secret.py" not in by_path
    assert ".gitkeep" not in by_path
    assert ".wh..wh..opq" not in by_path
    assert Path("Mentara") not in plan.directories

    assert by_path["ra2.mix"].origin is EntryOrigin.BASE
    assert by_path["ra2.mix"].materialization is Materialization.SYMLINK

    ddraw = by_path["ddraw.dll"]
    assert ddraw.layer_label == "layer:two"
    assert ddraw.shadowed_from == ("base", "layer:one")
    assert ddraw.materialization is Materialization.SYMLINK

    ini = by_path["RA2MO.ini"]
    assert ini.origin is EntryOrigin.STATE
    assert ini.materialization is Materialization.COPY
    assert ini.shadowed_from == ("base",)

    assert len(plan.matching(("*.DLL",))) == 2
    assert len(plan.overrides()) == 4
    assert plan.case_collisions == ()


def test_build_overlay_plan_detects_windows_case_collisions(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    layer = tmp_path / "layer"
    base.mkdir()
    layer.mkdir()
    (base / "RA2MO.ini").write_text("base", encoding="utf-8")
    (layer / "ra2mo.ini").write_text("layer", encoding="utf-8")

    plan = build_overlay_plan(
        (
            LayerSource("base", base, EntryOrigin.BASE),
            LayerSource("layer:custom", layer, EntryOrigin.LAYER),
        ),
    )

    assert len(plan.case_collisions) == 1
    collision = plan.case_collisions[0]
    assert collision.folded_path == "ra2mo.ini"
    assert collision.variants == (
        (Path("RA2MO.ini"), "base"),
        (Path("ra2mo.ini"), "layer:custom"),
    )


def test_build_overlay_plan_raises_on_missing_required_layer(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(OverlayError, match="Missing layer:missing"):
        build_overlay_plan(
            (LayerSource("layer:missing", missing, EntryOrigin.LAYER),),
        )


def test_build_overlay_plan_composes_patches_across_layers_and_state(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    layer_one = tmp_path / "layer1"
    layer_two = tmp_path / "layer2"
    state = tmp_path / "state"
    for directory in (base, layer_one, layer_two, state):
        directory.mkdir()

    (base / "RA2MO.ini").write_text(
        "[Options]\r\nGameSpeed=1\r\nDifficulty=2\r\n",
        encoding="utf-8",
        newline="",
    )
    (layer_one / "RA2MO.patch.ini").write_text(
        "[Options]\nGameSpeed=4\nToolTips=yes\n",
        encoding="utf-8",
    )
    (layer_two / "RA2MO.patch.ini").write_text(
        "[Options]\n-Difficulty\n[Video]\nScreenWidth=1920\n",
        encoding="utf-8",
    )
    # Runtime state modifies Volume; patches still apply on top.
    (state / "RA2MO.ini").write_text(
        "[Options]\r\nGameSpeed=1\r\nDifficulty=2\r\n[Audio]\r\nClientVolume=8\r\n",
        encoding="utf-8",
        newline="",
    )

    plan = build_overlay_plan(
        (
            LayerSource("base", base, EntryOrigin.BASE),
            LayerSource("layer:one", layer_one, EntryOrigin.LAYER),
            LayerSource("layer:two", layer_two, EntryOrigin.LAYER),
            LayerSource("state", state, EntryOrigin.STATE),
        ),
    )

    entry = plan.lookup_case_insensitive(Path("RA2MO.ini"))
    assert entry is not None
    assert entry.materialization is Materialization.PATCH
    assert len(entry.patches) == 2
    rendered = render_entry_text(entry)
    assert "GameSpeed=4\r\n" in rendered
    assert "ToolTips=yes\r\n" in rendered
    assert "Difficulty" not in rendered
    assert "ClientVolume=8\r\n" in rendered
    assert "[Video]\r\nScreenWidth=1920\r\n" in rendered


def test_patch_directory_applies_fragments_in_name_order(tmp_path: Path) -> None:
    base, layer = tmp_path / "base", tmp_path / "layer"
    fragments = layer / "INI" / "rules.patch.ini"
    fragments.mkdir(parents=True)
    (base / "INI").mkdir(parents=True)
    (base / "INI" / "rules.ini").write_text("[A]\r\nX=0\r\n", encoding="utf-8")
    (fragments / "b.ini").write_text("[A]\nX=2\n[List]\n+=Second\n", encoding="utf-8")
    (fragments / "a.ini").write_text(
        "[A]\nX=1\nY=1\n[List]\n+=First\n", encoding="utf-8"
    )

    plan = build_overlay_plan(
        (
            LayerSource("base", base, EntryOrigin.BASE),
            LayerSource("layer", layer, EntryOrigin.LAYER),
        ),
    )

    entry = plan.lookup_case_insensitive(Path("INI/rules.ini"))
    assert entry is not None
    assert [spec.source_path.name for spec in entry.patches] == ["a.ini", "b.ini"]
    rendered = render_entry_text(entry)
    assert "X=2\r\nY=1\r\n" in rendered
    assert "0=First\r\n1=Second\r\n" in rendered
    # The directory is consumed whole, not shown in the workspace.
    assert Path("INI/rules.patch.ini") in plan.hidden_paths
    assert Path("INI/rules.patch.ini") not in plan.directories


@pytest.mark.parametrize(
    ("stray", "error"),
    [("notes.md", r"holds only \*\.ini files"), ("sub/c.ini", r"holds only fragments")],
)
def test_patch_directory_rejects_files_that_are_not_fragments(
    tmp_path: Path, stray: str, error: str
) -> None:
    layer = tmp_path / "layer"
    path = layer / "rules.patch.ini" / stray
    path.parent.mkdir(parents=True)
    path.write_text("[A]\nX=1\n", encoding="utf-8")

    with pytest.raises(OverlayError, match=error):
        build_overlay_plan((LayerSource("layer", layer, EntryOrigin.LAYER),))
