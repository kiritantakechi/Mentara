"""Teams that walk into buildings.

Engineers at the map's tech and bridges, infantry and tanks into
garrisons, bunkers and reactors, hijackers, spies, and engineer drops.
"""

from dataclasses import dataclass
from typing import Final
lazy from collections.abc import Iterator, Mapping

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Country, Role
from mentara.mentalai.families._kit import (
    BEELINE,
    DROP,
    TOP,
    Context,
    Order,
    Series,
    answering,
    on_call,
    owned,
    unlocked,
)
from mentara.mentalai.model import (
    Condition,
    Crew,
    Gate,
    Squad,
)
from mentara.mentalai.scripts import Script, Target
from mentara.mentalai.slots import (
    ENGINEER,
    FRONT,
    HIJACKER,
    INFANTRY,
    OCCUPIER,
    SPY,
    TRANSPORT,
    Seats,
    Slot,
    fill,
)


@dataclass(frozen=True, slots=True)
class _Errand:
    """A job for engineers at buildings of the map."""

    series: Series
    script: Script
    engineers: int
    buildings: tuple[str, ...]
    weight: int
    max_teams: int


def engineering(ctx: Context, country: Country) -> Iterator[Order]:
    """Engineers take the map's tech and mend its bridges.

    A trigger per tech building waits until a neutral house owns one:
    the more kinds of tech lie untaken, the sooner the engineers go, and
    with none left they stay home. An engineer waits by a bridge hut
    for its bridge to fall.
    """
    catalog = ctx.catalog
    errands = (
        _Errand(
            Series.CAPTURE,
            Script(6000, "Capture", sc.capture_tech()),
            engineers=2,
            buildings=catalog.tech_buildings,
            weight=25,
            max_teams=2,
        ),
        _Errand(
            Series.BRIDGE,
            Script(6600, "Bridge Repair", sc.bridge_repair()),
            engineers=1,
            buildings=catalog.bridge_huts,
            weight=15,
            max_teams=1,
        ),
    )
    low = ctx.fielded(country, 1)
    for errand in errands:
        crew = fill(((ENGINEER, errand.engineers),), low, 1)
        if crew is None:
            continue
        name = errand.script.name
        squad = Squad(
            errand.series.at(),
            name,
            crew,
            errand.script,
            BEELINE,
            max_teams=errand.max_teams,
        )
        gates = (
            (f"{name} {building}", Gate.neutral_owns(building))
            for building in errand.buildings
        )
        yield from answering(squad, gates, errand.weight)


@dataclass(frozen=True, slots=True)
class _Post:
    """A building units walk into, who goes, and what it waits for."""

    series: Series
    script: Script
    seats: Seats
    gate: Gate | None
    weight: int


def occupation(ctx: Context, country: Country) -> Iterator[Order]:
    """Garrisons, bunkers, bio reactors and hijackers."""
    posts = (
        _Post(
            Series.GARRISON,
            Script(6100, "Garrison", sc.garrison()),
            ((OCCUPIER, 5),),
            Gate(Condition.ALWAYS),
            20,
        ),
        _Post(
            Series.BATTLE_BUNKER,
            Script(6200, "Battle Bunker", sc.occupy_bunker()),
            ((OCCUPIER, 4),),
            owned(country.battle_bunker),
            25,
        ),
        _Post(
            Series.TANK_BUNKER,
            Script(6300, "Tank Bunker", sc.tank_bunker()),
            ((FRONT, 2),),
            owned(country.tank_bunker),
            25,
        ),
        _Post(
            Series.BIO_REACTOR,
            Script(6400, "Bio Reactor", sc.absorb()),
            ((INFANTRY, 5),),
            owned(country.absorber),
            20,
        ),
    )
    low = ctx.fielded(country, 1)
    for post in posts:
        crew = fill(post.seats, low, 1)
        if post.gate is None or crew is None:
            continue
        squad = Squad(
            post.series.at(),
            post.script.name,
            crew,
            post.script,
            BEELINE,
            max_teams=1,
        )
        yield from on_call(squad, post.gate, post.weight)
    yield from _hijackers(ctx, country)


def _hijackers(ctx: Context, country: Country) -> Iterator[Order]:
    crew = fill(((HIJACKER, 3),), ctx.fielded(country, TOP), TOP)
    gate = None if crew is None else unlocked(country, crew)
    if crew is None or gate is None:
        return
    script = Script(6500, "Hijack", sc.hijack())
    squad = Squad(Series.HIJACK.at(), "Hijack", crew, script, BEELINE, max_teams=1)
    yield from on_call(squad, gate, 15)


# Classes of building, and what each is called in a team's name.
_SPY_TARGETS: Final[Mapping[Target, str]] = frozendict(
    {
        Target.POWER: "Power",
        Target.RADAR: "Radar",
        Target.VEHICLE_FACTORY: "War Factory",
        Target.BARRACKS: "Barracks",
        Target.REFINERY: "Refinery",
        Target.SUPERWEAPON: "Superweapon",
        Target.TECH_LAB: "Tech Lab",
    }
)
_DROP_TARGETS: Final[Mapping[Target, str]] = frozendict(
    {
        Target.POWER: "Power",
        Target.FACTORIES: "Factory",
        Target.CONSTRUCTION_YARD: "Yard",
    }
)
# Script numbers: a spy's and a drop's are their target's, from here.
_SPY_CODE: Final[int] = 7000
_DROP_CODE: Final[int] = 7100
# An air drop is numbered this far past the same drop by land.
_AIR_DROP_STEP: Final[int] = 10
_DROP_ENGINEERS: Final[int] = 2
# An aircraft that carries infantry: the faster and roomier the better.
_AIR_TRANSPORT: Final[Slot] = Slot(
    "air transport",
    lambda u: u.has(Role.AIRBORNE, Role.TRANSPORT),
    lambda u, _t: u.passengers * u.speed,
    rank=5,
)


def infiltration(ctx: Context, country: Country) -> Iterator[Order]:
    """Spies on every class of building, and engineer drops."""
    yield from _spies(ctx, country)
    yield from _drops(ctx, country, "Engineer Drop", airborne=False)
    yield from _drops(ctx, country, "Air Drop", airborne=True)


def _spies(ctx: Context, country: Country) -> Iterator[Order]:
    crew = fill(((SPY, 1),), ctx.fielded(country, TOP), TOP)
    gate = None if crew is None else unlocked(country, crew)
    if crew is None or gate is None:
        return
    for index, (target, name) in enumerate(_SPY_TARGETS.items(), start=1):
        script = Script(_SPY_CODE + target, f"Spy vs {name}", sc.infiltrate(target))
        squad = Squad(
            Series.SPY.at(index), script.name, crew, script, BEELINE, max_teams=1
        )
        yield from on_call(squad, gate, 6)


def _drops(
    ctx: Context, country: Country, way: str, *, airborne: bool
) -> Iterator[Order]:
    """Engineers driven or flown next to a target, to take it.

    They wait for the tier of their transport, the second at least.
    """
    crew = _drop_crew(ctx, country, airborne=airborne)
    gate = None if crew is None else unlocked(country, crew, floor=2)
    if crew is None or gate is None:
        return
    first = _AIR_DROP_STEP * airborne
    for index, (target, name) in enumerate(_DROP_TARGETS.items(), start=1):
        script = Script(_DROP_CODE + target, f"Drop vs {name}", sc.drop(target))
        squad = Squad(
            Series.DROP.at(first + index),
            f"{way} vs {name}",
            crew,
            script,
            DROP,
            max_teams=1,
        )
        yield from on_call(squad, gate, 10)


def _drop_crew(ctx: Context, country: Country, *, airborne: bool) -> Crew | None:
    """A transport and the engineers that fit in it, by land or air.

    Vanilla 14 seats them in one transport, an aircraft first.
    """
    units = ctx.fielded(country, TOP)
    engineers = fill(((ENGINEER, _DROP_ENGINEERS),), units, TOP)
    if engineers is None:
        return None
    engineer = engineers[0].unit
    carriers = tuple(
        u
        for u in units
        if u.size_limit >= engineer.size
        and u.passengers >= _DROP_ENGINEERS
        and u.has(Role.AIRBORNE) == airborne
        and u.has(Role.TRANSPORT)
        and not u.roles & {Role.NAVAL, Role.HARVESTER, Role.MCV}
    )
    seat = _AIR_TRANSPORT if airborne else TRANSPORT
    transport = fill(((seat, 1),), carriers, TOP)
    return None if transport is None else transport + engineers
