"""The Mental AI's families of teams: what each country fields and when.

Each family reads a country's units, buildings and superweapons and
yields squads (a TaskForce with its TeamType) and the triggers that call
them. No unit, building or superweapon is named: every choice follows
from the rules data, so the same families serve every side.
"""

from typing import Final

from mentara.mentalai.families._kit import Context, Family, Order
from mentara.mentalai.families.agents import engineering, occupation, spies
from mentara.mentalai.families.air import air_strikes, interceptors, wings
from mentara.mentalai.families.assault import (
    lines,
    sieges,
    superweapon_assaults,
    superweapon_snipes,
)
from mentara.mentalai.families.defense import defense
from mentara.mentalai.families.landing import drops, landings
from mentara.mentalai.families.naval import flotillas, naval
from mentara.mentalai.families.raids import raids
from mentara.mentalai.families.response import counters, opportunities, redeploy
from mentara.mentalai.families.roster import (
    bombers,
    carriers,
    charges,
    deployers,
    heroes,
    leftovers,
)
from mentara.mentalai.families.specialists import (
    companies,
    escorts,
    psychics,
    specialists,
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
    spies,
    drops,
    landings,
    naval,
    wings,
    interceptors,
    flotillas,
    heroes,
    deployers,
    bombers,
    carriers,
    charges,
    psychics,
    companies,
    specialists,
    escorts,
    superweapon_assaults,
    counters,
    opportunities,
    redeploy,
)
