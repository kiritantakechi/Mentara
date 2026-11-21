"""Generate the Mental AI's layer files from a profile's rules."""

from pathlib import Path
from typing import Final

from mentara.mentalai.catalog import build_catalog
from mentara.mentalai.emit import (
    render_ai_fragment,
    render_option_fragment,
    render_rules_fragment,
)
from mentara.mentalai.ini import IniData
from mentara.mentalai.teams import plan_ai

__all__ = [
    "AI_FRAGMENT",
    "OPTION_FRAGMENT",
    "RULES_FRAGMENT",
    "RULES_SOURCE",
    "generate_mentalai",
]

RULES_SOURCE: Final[Path] = Path("expandmo99.mix/rulesmo.ini")
AI_FRAGMENT: Final[Path] = Path("expandmo99.mix/aimo.patch.ini/mentalai.ini")
RULES_FRAGMENT: Final[Path] = Path("expandmo99.mix/rulesmo.patch.ini/mentalai.ini")
OPTION_FRAGMENT: Final[Path] = Path("INI/Game Options/Mental AI.patch.ini/mentalai.ini")


def generate_mentalai(rules_text: str) -> dict[Path, str]:
    """The Mental AI's patch fragments, by path inside the layer.

    Args:
        rules_text: The profile's rendered rules (`RULES_SOURCE`).

    Returns:
        Layer-relative path to file text.
    """
    plan = plan_ai(build_catalog(IniData.parse(rules_text)))
    return {
        AI_FRAGMENT: render_ai_fragment(plan),
        OPTION_FRAGMENT: render_option_fragment(plan),
        RULES_FRAGMENT: render_rules_fragment(plan),
    }
