"""Everything that flies to fight.

A strike group of a side's best craft at each tier, an interceptor
flight for each kind of airfield the enemy keeps, and for every craft
the sorties its weapons and its airframe suit: a strike on what it
hurts most, a hunt for harvesters, support wherever the house is under
fire, and cover over the base.
"""

from dataclasses import dataclass, replace
from typing import Final
lazy from collections.abc import Callable, Iterator, Mapping

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Country, Role, Unit
from mentara.mentalai.families._kit import (
    AIR_SUPPORT,
    ARMED,
    OTHER_JOBS,
    SORTIE,
    WATCH,
    Aim,
    Context,
    Course,
    Order,
    Series,
    aim_of,
    alone,
    answering,
    at_tier,
    from_tier,
    harm,
    on_call,
    roster,
    squadron,
)
from mentara.mentalai.model import (
    Conduct,
    Crew,
    Gate,
    Squad,
)
from mentara.mentalai.scripts import Quarry, Script, Target
from mentara.mentalai.slots import (
    AIR,
    AIR_EFFECT,
    INTERCEPTOR,
    Seats,
    fill,
)

_AIR_COURSES: Final[Mapping[Aim, Course]] = frozendict(
    {
        Aim.VEHICLES: Course(4001, (Quarry.VEHICLES, Quarry.DEFENSES)),
        Aim.INFANTRY: Course(4002, (Quarry.INFANTRY, Quarry.OCCUPIED)),
        Aim.BUILDINGS: Course(4003, (Quarry.DEFENSES, Quarry.STRUCTURES)),
    }
)


def _strike(unit: Unit) -> Script:
    """A strike on the class a craft hurts most, named by its quarry."""
    course = _AIR_COURSES[aim_of(unit)]
    first, second = course.quarries
    name = f"Air Strike vs {first.name.lower()}"
    return Script(course.code, name, sc.air_strike(first, second))


_AIR_TIERS: Final[tuple[int, ...]] = (2, 3)
# The side's best strike craft, and beside them a craft whose weapon
# only carries an effect: MO flew its Cryocopters and Hummingbirds at
# what its jets then hit.
_STRIKE_SEATS: Final[Seats] = ((AIR, 4), (AIR_EFFECT, 1))


def air_strikes(ctx: Context, country: Country) -> Iterator[Order]:
    """Strike craft on the class they hurt most.

    Airfield-bound craft share one airfield's pads across the tiers,
    one team per tier: an aircraft with no free pad is never built, and
    the AI abandons it.
    """
    for tier in _AIR_TIERS:
        gate = at_tier(country, tier)
        crew = fill(_STRIKE_SEATS, ctx.fielded(country, tier), tier, required=(AIR,))
        if gate is None or crew is None:
            continue
        craft = crew[0].unit
        max_teams = 3
        if craft.has(Role.DOCKED):
            share = country.docks // len(_AIR_TIERS)
            if share <= 0:
                continue
            crew = tuple(replace(m, count=min(m.count, share)) for m in crew)
            max_teams = 1
        squad = Squad(
            Series.AIR_STRIKE.at(tier),
            f"Air Strike T{tier}",
            crew,
            _strike(craft),
            SORTIE,
            max_teams=max_teams,
        )
        yield from on_call(squad, gate, 50)


def interceptors(ctx: Context, country: Country) -> Iterator[Order]:
    """The side's best air-to-air craft at each kind of enemy airfield.

    They go for its aircraft, on their pads if they find them there.
    """
    crew = fill(((INTERCEPTOR, 1),), ctx.fielded(country, 2), 2)
    if crew is None:
        return
    script = Script(4400, "Intercept", sc.intercept())
    squad = Squad(
        Series.INTERCEPT.at(),
        script.name,
        squadron(crew[0].unit),
        script,
        SORTIE,
        max_teams=1,
    )
    gates = (
        (f"Intercept vs {building}", Gate.enemy_owns(building))
        for building in ctx.airfields
    )
    yield from answering(squad, gates, 40)


def _flies_to_fight(unit: Unit) -> bool:
    if not unit.has(Role.AIRBORNE) or unit.roles & (OTHER_JOBS | {Role.NAVAL}):
        return False
    return bool(unit.roles & (ARMED | {Role.AA}))


def _hits_ground(unit: Unit) -> bool:
    return any(harm(unit.firepower, aim) > 0 for aim in Aim)


# A flight that stays near home or near the lines is a pair, as MO's
# own were.
_PAIR: Final[int] = 2


def _pair(craft: Unit) -> Crew:
    return alone(craft, _PAIR)


@dataclass(frozen=True, slots=True)
class _Sortie:
    """A mission a craft flies when it suits it.

    Attributes:
        series: Its squads' series, numbered by the craft.
        name: What it is called ("Squadron").
        fits: Whether a craft flies it.
        crew: The flight a craft makes up for it.
        script: What the flight does.
        doctrine: How it behaves.
        weight: Its trigger's weight.
        teams: How many flights of a craft may fly it at once; an
            airfield-bound craft has pads for one.
    """

    series: Series
    name: str
    fits: Callable[[Unit], bool]
    crew: Callable[[Unit], Crew]
    script: Callable[[Unit], Script]
    doctrine: Conduct
    weight: int
    teams: int = 1


_MINER_HUNT: Final[Script] = Script(4100, "Miner Hunt", sc.miner_hunt())
_SUPPORT: Final[Script] = Script(4200, "Air Support", sc.air_support())
_COVER: Final[Script] = Script(4300, "Air Cover", sc.post(Target.DEFENSES))
_SORTIES: Final[tuple[_Sortie, ...]] = (
    # A strike on the class it hurts most: every craft with a weapon
    # for the ground.
    _Sortie(
        Series.SQUADRON,
        "Squadron",
        lambda u: _hits_ground(u) or u.has(Role.EFFECT),
        squadron,
        _strike,
        SORTIE,
        30,
        teams=2,
    ),
    # The harvesters, for a craft that hurts vehicles most and needs no
    # pad to come back to: MO's Wolfhounds, Pteranodons and Dragonflies.
    _Sortie(
        Series.MINER_HUNT,
        "Miner Hunt",
        lambda u: (
            not u.has(Role.DOCKED)
            and aim_of(u) is Aim.VEHICLES
            and u.firepower.vehicle > 0
        ),
        squadron,
        lambda _u: _MINER_HUNT,
        SORTIE,
        20,
    ),
    # Whatever is attacking the house: a craft that can stay up.
    _Sortie(
        Series.AIR_SUPPORT,
        "Air Support",
        lambda u: not u.has(Role.DOCKED) and _hits_ground(u),
        _pair,
        lambda _u: _SUPPORT,
        AIR_SUPPORT,
        25,
    ),
    # The sky over the defences, as a base-defence team: a craft that
    # shoots aircraft down and can stay up.
    _Sortie(
        Series.AIR_COVER,
        "Air Cover",
        lambda u: not u.has(Role.DOCKED) and u.firepower.air > 0,
        _pair,
        lambda _u: _COVER,
        WATCH,
        15,
    ),
)


def wings(ctx: Context, country: Country) -> Iterator[Order]:
    """For every craft, the sorties its weapons and its airframe suit.

    Airfield-bound craft fly in pairs, one flight at a time: each needs
    a pad to come back to.
    """
    for index, (unit, tier) in enumerate(
        roster(ctx, country, _flies_to_fight), start=1
    ):
        gate = from_tier(country, tier)
        if gate is None:
            continue
        for sortie in _SORTIES:
            if not sortie.fits(unit):
                continue
            squad = Squad(
                sortie.series.at(index),
                f"{sortie.name} {unit.id}",
                sortie.crew(unit),
                sortie.script(unit),
                sortie.doctrine,
                max_teams=1 if unit.has(Role.DOCKED) else sortie.teams,
            )
            yield from on_call(squad, gate, sortie.weight)
