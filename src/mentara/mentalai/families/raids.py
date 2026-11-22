"""Fast single-role teams: raids, feints and air strikes."""

from dataclasses import dataclass, replace
from typing import Final
lazy from collections.abc import Callable, Iterator, Mapping

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Country, Role, Unit
from mentara.mentalai.families._kit import (
    FEINT,
    RAID,
    SORTIE,
    Aim,
    Context,
    Course,
    Order,
    Series,
    aim_of,
    at_tier,
    on_call,
    variants_of,
)
from mentara.mentalai.model import (
    Conduct,
    Squad,
)
from mentara.mentalai.scripts import Lines, Quarry, Script
from mentara.mentalai.slots import (
    AIR,
    FAST,
    RAIDER,
    STEALTH,
    STRIKER,
    Seats,
    fill,
)


@dataclass(frozen=True, slots=True)
class _RaidKind:
    """A fast single-role team, the tiers it runs at and its weight."""

    series: Series
    name: str
    code: int
    write: Callable[[], Lines]
    seats: Seats
    tiers: tuple[int, ...]
    weight: int
    doctrine: Conduct

    def script(self) -> Script:
        return Script(self.code, self.name, self.write())


_RAIDS: Final[tuple[_RaidKind, ...]] = (
    _RaidKind(
        Series.BLITZ,
        "Blitz",
        3000,
        sc.blitz,
        ((STRIKER, 4), (FAST, 2)),
        (2, 3),
        40,
        RAID,
    ),
    _RaidKind(Series.FEINT, "Feint", 3100, sc.feint, ((FAST, 4),), (1, 2), 30, FEINT),
    _RaidKind(
        Series.ECONOMY_RAID,
        "Economy Raid",
        3200,
        sc.economy_raid,
        ((RAIDER, 4),),
        (1, 2),
        40,
        RAID,
    ),
    _RaidKind(
        Series.POWER_RAID,
        "Power Raid",
        3300,
        sc.power_raid,
        ((STRIKER, 3), (FAST, 2)),
        (1, 2, 3),
        30,
        RAID,
    ),
    _RaidKind(
        Series.STEALTH_RAID,
        "Stealth Raid",
        3400,
        sc.economy_raid,
        ((STEALTH, 4),),
        (1, 2, 3),
        30,
        RAID,
    ),
)


def raids(ctx: Context, country: Country) -> Iterator[Order]:
    """Fast single-role teams: factory blitzes, feints and raids.

    A feint hits the chosen enemy's farthest buildings to pull the
    defence away from the lines; raids hit the economy and the power.
    """
    for raid in _RAIDS:
        script = raid.script()
        for tier in raid.tiers:
            gate = at_tier(country, tier)
            if gate is None:
                continue
            for variant in variants_of(raid.seats, ctx.fielded(country, tier), tier):
                squad = Squad(
                    variant.number(raid.series),
                    variant.label(raid.name),
                    variant.crew,
                    script,
                    raid.doctrine,
                )
                yield from on_call(squad, gate, variant.weight(raid.weight))


_AIR_COURSES: Final[Mapping[Aim, Course]] = frozendict(
    {
        Aim.VEHICLES: Course(4001, (Quarry.VEHICLES, Quarry.DEFENSES)),
        Aim.INFANTRY: Course(4002, (Quarry.INFANTRY, Quarry.OCCUPIED)),
        Aim.BUILDINGS: Course(4003, (Quarry.DEFENSES, Quarry.STRUCTURES)),
    }
)


def air_script(unit: Unit) -> Script:
    """A strike on the class a craft hurts most, named by its quarry."""
    course = _AIR_COURSES[aim_of(unit)]
    first, second = course.quarries
    name = f"Air Strike vs {first.name.lower()}"
    return Script(course.code, name, sc.air_strike(first, second))


_AIR_TIERS: Final[tuple[int, ...]] = (2, 3)


def air_strikes(ctx: Context, country: Country) -> Iterator[Order]:
    """Strike craft on the class they hurt most.

    Airfield-bound craft share one airfield's pads across the tiers,
    one team per tier: an aircraft with no free pad is never built, and
    the AI abandons it.
    """
    for tier in _AIR_TIERS:
        gate = at_tier(country, tier)
        crew = fill(((AIR, 4),), ctx.fielded(country, tier), tier)
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
            air_script(craft),
            SORTIE,
            max_teams=max_teams,
        )
        yield from on_call(squad, gate, 50)
