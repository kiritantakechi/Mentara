"""Fleets, and a flotilla for every warship.

The engine keeps them off maps without water: a naval team's members
need a shipyard.
"""

from dataclasses import dataclass
from typing import Final
lazy from collections.abc import Callable, Iterator

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Country, Factory, Role, Unit
from mentara.mentalai.families._kit import (
    ARMED,
    ASSAULT,
    OTHER_JOBS,
    TOP,
    Context,
    Order,
    Series,
    alone,
    answering,
    from_tier,
    on_call,
    roster,
)
from mentara.mentalai.model import (
    Gate,
    Squad,
)
from mentara.mentalai.scripts import Lines, Script
from mentara.mentalai.slots import (
    NAVAL_AA,
    NAVAL_ARTILLERY,
    NAVAL_FRONT,
    NAVAL_HUNTER,
    Seats,
    fill,
)


@dataclass(frozen=True, slots=True)
class _FleetKind:
    """A kind of naval squad.

    Attributes:
        series: Its series.
        name: What it is.
        code: Its script's number.
        write: Its script.
        seats: Its slots, the lead ship's first.
        weight: Its trigger's weight.
        hunts: Whether it hunts ships, and so waits for an enemy
            shipyard.
    """

    series: Series
    name: str
    code: int
    write: Callable[[], Lines]
    seats: Seats
    weight: int
    hunts: bool = False

    def script(self) -> Script:
        return Script(self.code, self.name, self.write())


_NAVY: Final[_FleetKind] = _FleetKind(
    Series.NAVY,
    "Navy",
    9000,
    sc.naval_line,
    ((NAVAL_FRONT, 3), (NAVAL_ARTILLERY, 2), (NAVAL_AA, 1)),
    80,
)
_SUB_HUNT: Final[_FleetKind] = _FleetKind(
    Series.SUB_HUNT,
    "Sub Hunt",
    9100,
    sc.naval_hunt,
    ((NAVAL_HUNTER, 4),),
    50,
    hunts=True,
)
_BOMBARDMENT: Final[_FleetKind] = _FleetKind(
    Series.BOMBARDMENT,
    "Bombardment",
    9200,
    sc.naval_bombard,
    ((NAVAL_ARTILLERY, 3), (NAVAL_AA, 1)),
    50,
)
_FLEETS: Final[tuple[_FleetKind, ...]] = (_NAVY, _SUB_HUNT, _BOMBARDMENT)
_FLEET_TIERS: Final[tuple[int, ...]] = (1, TOP)
# A hunter squad's calls are numbered this far apart, one per shipyard.
_PREY_STEP: Final[int] = 20


def _afloat(
    ctx: Context, squad: Squad, gate: Gate, weight: int, *, hunts: bool
) -> Iterator[Order]:
    """A naval squad and its triggers.

    Ship hunters are called once per shipyard the enemy may own.
    Hunters with nothing to hunt would end their first objective at
    once, mark success and gain weight for it (in play Russia raised 35
    sub hunts against an enemy with almost no navy).
    """
    if not hunts:
        yield from on_call(squad, gate, weight)
        return
    gates = (
        (f"{squad.label} vs {shipyard}", Gate.enemy_owns(shipyard))
        for shipyard in ctx.shipyards
    )
    yield from answering(squad, gates, weight, step=_PREY_STEP)


def naval(ctx: Context, country: Country) -> Iterator[Order]:
    """Navies once a shipyard stands; ships only reach water targets."""
    for fleet in _FLEETS:
        script = fleet.script()
        lead = fleet.seats[0][0]
        for tier in _FLEET_TIERS:
            gate = from_tier(country, tier, factory=Factory.SHIPYARD)
            crew = fill(fleet.seats, ctx.fielded(country, tier), tier, required=(lead,))
            if gate is None or crew is None:
                continue
            squad = Squad(
                fleet.series.at(tier), f"{fleet.name} T{tier}", crew, script, ASSAULT
            )
            yield from _afloat(ctx, squad, gate, fleet.weight, hunts=fleet.hunts)


def _sails_to_fight(unit: Unit) -> bool:
    """A warship, an armed naval transport included."""
    jobs = OTHER_JOBS - {Role.TRANSPORT}
    return unit.has(Role.NAVAL) and bool(unit.roles & ARMED) and not unit.roles & jobs


def _fleet_of(ship: Unit) -> _FleetKind:
    """Where a ship's guns suit it.

    One that shells the shore bombards it, another that can hurt it
    joins the fleet's line, and one that cannot hunts ships.
    """
    if NAVAL_ARTILLERY.fits(ship):
        return _BOMBARDMENT
    return _NAVY if ship.firepower.building > 0 else _SUB_HUNT


def flotillas(ctx: Context, country: Country) -> Iterator[Order]:
    """A flotilla per warship, sent where its guns suit it."""
    for index, (unit, tier) in enumerate(
        roster(ctx, country, _sails_to_fight), start=1
    ):
        gate = from_tier(country, tier, factory=Factory.SHIPYARD)
        if gate is None:
            continue
        fleet = _fleet_of(unit)
        squad = Squad(
            Series.FLOTILLA.at(index),
            f"Flotilla {unit.id}",
            alone(unit, 3),
            fleet.script(),
            ASSAULT,
        )
        yield from _afloat(ctx, squad, gate, 40, hunts=fleet.hunts)
