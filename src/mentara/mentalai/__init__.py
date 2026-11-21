"""The Mental AI: combined-arms skirmish AI behind "Mental AI Boost"."""

from mentara.mentalai.catalog import Catalog, build_catalog
from mentara.mentalai.emit import (
    render_ai_fragment,
    render_option_fragment,
    render_rules_fragment,
)
from mentara.mentalai.ini import IniData
from mentara.mentalai.model import AIPlan
from mentara.mentalai.teams import plan_ai

__all__ = [
    "AIPlan",
    "Catalog",
    "IniData",
    "build_catalog",
    "plan_ai",
    "render_ai_fragment",
    "render_option_fragment",
    "render_rules_fragment",
]
