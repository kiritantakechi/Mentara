"""The Mental AI's families of teams: what each country fields and when.

Each family reads a country's units, buildings and superweapons and
yields squads (a TaskForce with its TeamType) and the triggers that call
them. No unit, building or superweapon is named: every choice follows
from the rules data, so the same families serve every side.
"""

from typing import Final

from mentara.mentalai.families._kit import Context, Family, Order
from mentara.mentalai.families.agents import engineering, infiltration, occupation
from mentara.mentalai.families.assault import (
    lines,
    sieges,
    superweapon_assaults,
    superweapon_snipes,
)
from mentara.mentalai.families.defense import defense
from mentara.mentalai.families.naval import flotillas, naval
from mentara.mentalai.families.raids import air_strikes, raids
from mentara.mentalai.families.response import counters, opportunities, redeploy
from mentara.mentalai.families.roster import (
    bombers,
    carriers,
    charges,
    deployers,
    heroes,
    leftovers,
    squadrons,
)

__all__ = ["FAMILIES", "Context", "Family", "Order", "leftovers"]

# In the order their triggers are listed.
FAMILIES: Final[tuple[Family, ...]] = (
    lines,
    sieges,
    superweapon_snipes,
    raids,
    air_strikes,
    defense,
    engineering,
    occupation,
    infiltration,
    naval,
    squadrons,
    flotillas,
    heroes,
    deployers,
    bombers,
    carriers,
    charges,
    superweapon_assaults,
    counters,
    opportunities,
    redeploy,
)
