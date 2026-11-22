"""Combined-arms assaults on a base.

Lines in three ways (direct, flanking, army-hunting), sieges, the
snipe of an enemy superweapon, and the assaults a side's own
superweapons make: Chronosphere jumps, Iron Curtain charges and lines
under a team-cast buff.
"""

from dataclasses import dataclass
from typing import Final
lazy from collections.abc import Callable, Iterator, Mapping

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Country, Kind, Unit
from mentara.mentalai.families._kit import (
    ASSAULT,
    COUNTER,
    FLANK,
    HUNTER,
    TIERS,
    TOP,
    ByTier,
    Combo,
    Context,
    Order,
    Series,
    answering,
    at_tier,
    on_call,
    variants_of,
)
from mentara.mentalai.model import (
    Condition,
    Conduct,
    Gate,
    Squad,
)
from mentara.mentalai.scripts import Lines, Quarry, Script
from mentara.mentalai.slots import (
    AA,
    ARTILLERY,
    CONTROLLER,
    DETECTOR,
    DISABLER,
    FRONT,
    HERO,
    SCREEN,
    SIEGE,
    SUPPORT,
    Seats,
    fill,
)


@dataclass(frozen=True, slots=True)
class LineKind:
    """A way a line fights; all ways share the line's members."""

    series: Series
    name: str
    code: int
    write: Callable[[tuple[int, ...]], Lines]
    doctrine: Conduct
    weights: ByTier

    def script(self, casts: tuple[int, ...]) -> Script:
        """The line's script for a country, casting its superweapons."""
        return Script(self.code, self.name, self.write(casts))


DIRECT: Final[LineKind] = LineKind(
    Series.LINE, "Line", 1000, sc.line_direct, ASSAULT, (100, 120, 150)
)
_FLANKING: Final[LineKind] = LineKind(
    Series.FLANK, "Flank", 1100, sc.line_flank, FLANK, (50, 60, 80)
)
HUNTING: Final[LineKind] = LineKind(
    Series.HUNT, "Hunt", 1200, sc.line_hunt, HUNTER, (40, 50, 60)
)
_LINES: Final[tuple[LineKind, ...]] = (DIRECT, _FLANKING, HUNTING)
_LINE_SEATS: Final[Mapping[int, Seats]] = frozendict(
    {
        1: ((FRONT, 4), (SCREEN, 3), (AA, 1), (DISABLER, 1), (DETECTOR, 1)),
        2: (
            (FRONT, 4),
            (ARTILLERY, 2),
            (SCREEN, 2),
            (AA, 2),
            (SUPPORT, 1),
            (CONTROLLER, 2),
            (DISABLER, 1),
            (DETECTOR, 1),
        ),
        3: (
            (FRONT, 4),
            (ARTILLERY, 2),
            (HERO, 1),
            (SCREEN, 2),
            (AA, 2),
            (SUPPORT, 1),
            (CONTROLLER, 1),
            (DISABLER, 1),
        ),
    }
)
# Two teams in the same frame: a line under an air strike, a pincer (a
# direct line and a flank), and a feint that pulls the defence away
# from a line.
_LINE_COMBOS: Final[tuple[Combo, ...]] = (
    Combo(Series.LINE_AIR, "Line + Air", Series.LINE, Series.AIR_STRIKE, (0, 50, 60)),
    Combo(Series.PINCER, "Pincer", Series.LINE, Series.FLANK, (30, 40, 50)),
    Combo(
        Series.FEINT_STRIKE,
        "Feint and Strike",
        Series.LINE,
        Series.FEINT,
        (35, 35, 35),
    ),
)
_LINE_TEAMS_MAX: Final[int] = 3


def lines(ctx: Context, country: Country) -> Iterator[Order]:
    """Combined-arms lines: direct, flanking and army-hunting.

    The members are the same; the scripts differ.
    """
    casts = country.front_casts
    for tier in TIERS:
        gate = at_tier(country, tier)
        if gate is None:
            continue
        units = ctx.fielded(country, tier)
        variants = tuple(variants_of(_LINE_SEATS[tier], units, tier, required=(FRONT,)))
        if not variants:
            continue
        for line in _LINES:
            script = line.script(casts)
            for variant in variants:
                squad = Squad(
                    variant.number(line.series),
                    variant.label(line.name),
                    variant.crew,
                    script,
                    line.doctrine,
                    max_teams=_LINE_TEAMS_MAX,
                )
                weight = variant.weight(line.weights[tier - 1])
                yield from on_call(squad, gate, weight)
        for combo in _LINE_COMBOS:
            yield from combo.calls(tier, gate)


_SIEGE_SEATS: Final[Seats] = ((SIEGE, 3), (FRONT, 2), (SCREEN, 2), (AA, 1))
_SIEGE_WEIGHT: Final[int] = 70
# A siege under an air strike, and one whose guns follow a hunting line
# that meets the army.
_SIEGE_COMBOS: Final[tuple[Combo, ...]] = (
    Combo(
        Series.SIEGE_AIR, "Siege + Air", Series.SIEGE, Series.AIR_STRIKE, (0, 40, 40)
    ),
    Combo(
        Series.SIEGE_ESCORT, "Escorted Siege", Series.SIEGE, Series.HUNT, (0, 35, 35)
    ),
)


def sieges(ctx: Context, country: Country) -> Iterator[Order]:
    """Artillery that out-damages buildings, with tanks and a screen."""
    for tier in (2, 3):
        gate = at_tier(country, tier)
        if gate is None:
            continue
        units = ctx.fielded(country, tier)
        variants = tuple(variants_of(_SIEGE_SEATS, units, tier, required=(SIEGE,)))
        if not variants:
            continue
        script = Script(2000, "Siege", sc.siege(country.front_casts))
        for variant in variants:
            squad = Squad(
                variant.number(Series.SIEGE),
                variant.label("Siege"),
                variant.crew,
                script,
                ASSAULT,
            )
            yield from on_call(squad, gate, variant.weight(_SIEGE_WEIGHT))
        for combo in _SIEGE_COMBOS:
            yield from combo.calls(tier, gate)


def superweapon_snipes(ctx: Context, country: Country) -> Iterator[Order]:
    """When the enemy owns a superweapon, a siege group goes for it."""
    seats: Seats = ((FRONT, 3), (SIEGE, 2), (AA, 1))
    crew = fill(seats, ctx.fielded(country, TOP), TOP, required=(FRONT,))
    if crew is None:
        return
    script = Script(
        2100, "Superweapon Snipe", sc.superweapon_snipe(country.front_casts)
    )
    squad = Squad(Series.SNIPE.at(), "Superweapon Snipe", crew, script, COUNTER)
    gates = (
        (f"Snipe {building}", Gate.enemy_owns(building))
        for building in ctx.superweapon_buildings
    )
    yield from answering(squad, gates, 60)


# What the Chronosphere drops a team beside, and what that is called.
_CHRONO_QUARRIES: Final[Mapping[Quarry, str]] = frozendict(
    {
        Quarry.FACTORIES: "Factories",
        Quarry.POWER: "Power",
        Quarry.DEFENSES: "Defenses",
    }
)
_CHRONO_CODE: Final[int] = 8100
_BOOST_CODE: Final[int] = 8300
# A boost assault needs this many members the buff reaches.
_BOOST_MEMBERS_MIN: Final[int] = 4
_SUPERWEAPON_SUFFIX: Final[str] = "special"


def superweapon_assaults(ctx: Context, country: Country) -> Iterator[Order]:
    """Chronosphere jumps, Iron Curtain charges and boost assaults.

    The sphere moves only what stands in its 3x3 cells and kills the
    infantry it moves, so jumps and curtain charges take vehicles. A
    boost assault is built from the units a team-cast buff reaches.
    """
    vehicles = tuple(u for u in ctx.fielded(country, TOP) if u.kind is Kind.VEHICLE)
    yield from _chrono_assaults(country, vehicles)
    yield from _curtain_charge(country, vehicles)
    yield from _boosts(ctx, country)


def _chrono_assaults(country: Country, vehicles: tuple[Unit, ...]) -> Iterator[Order]:
    seats: Seats = ((FRONT, 4), (ARTILLERY, 2), (AA, 1))
    crew = fill(seats, vehicles, TOP, required=(FRONT,))
    if not country.chronosphere or crew is None:
        return
    gate = Gate(Condition.CHRONOSPHERE_CHARGED)
    for index, (quarry, name) in enumerate(_CHRONO_QUARRIES.items(), start=1):
        script = Script(
            _CHRONO_CODE + quarry,
            f"Chrono vs {name}",
            sc.chrono_assault(quarry, country.front_casts),
        )
        squad = Squad(
            Series.CHRONO.at(index),
            f"Chrono Assault vs {name}",
            crew,
            script,
            ASSAULT,
            max_teams=1,
        )
        yield from on_call(squad, gate, 80)


def _curtain_charge(country: Country, vehicles: tuple[Unit, ...]) -> Iterator[Order]:
    curtain = country.curtain
    crew = fill(((FRONT, 5), (AA, 1)), vehicles, TOP, required=(FRONT,))
    if curtain is None or crew is None:
        return
    script = Script(
        8200, "Curtain Charge", sc.curtain_charge(curtain, country.front_casts)
    )
    squad = Squad(Series.CURTAIN.at(), script.name, crew, script, ASSAULT, max_teams=1)
    yield from on_call(squad, Gate(Condition.IRON_CURTAIN_CHARGED), 150)


def _boosts(ctx: Context, country: Country) -> Iterator[Order]:
    """A line for each team-cast buff, of the units the buff reaches.

    Its building is all the trigger waits for, so the team takes
    nothing from a tier above that building's.
    """
    seats: Seats = ((FRONT, 4), (SCREEN, 3), (ARTILLERY, 2), (AA, 1), (HERO, 1))
    seen: set[int] = set()
    for cast in country.casts:
        affects = cast.affects
        if cast.home or cast.curtain or affects is None or cast.group in seen:
            continue
        seen.add(cast.group)
        reached = (u for u in ctx.fielded(country, cast.tier) if u.armor in affects)
        crew = fill(seats, reached, cast.tier)
        if crew is None or sum(m.count for m in crew) < _BOOST_MEMBERS_MIN:
            continue
        others = (group for group in country.front_casts if group != cast.group)
        name = f"{_strip(cast.name)} Assault"
        script = Script(
            _BOOST_CODE + cast.group, name, sc.line_direct((cast.group, *others))
        )
        squad = Squad(Series.BOOST.at(cast.group), name, crew, script, ASSAULT)
        yield from on_call(squad, Gate.house_owns(cast.building), 70)


def _strip(name: str) -> str:
    """A superweapon's ID as a label: OverchargeSpecial, Overcharge."""
    if name.lower().endswith(_SUPERWEAPON_SUFFIX):
        return name[: -len(_SUPERWEAPON_SUFFIX)]
    return name
