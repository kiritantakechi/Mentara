"""Teams that walk into buildings.

Engineers at the map's tech and bridges, infantry and tanks into
garrisons, bunkers and reactors, hijackers, and spies.
"""

from dataclasses import dataclass
from typing import Final
lazy from collections.abc import Iterator, Mapping

from mentara.mentalai import scripts as sc
from mentara.mentalai.families._kit import (
    BEELINE,
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
    Seats,
    fill,
)
lazy from mentara.mentalai.catalog import Country


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
    with none left they stay home. An engineer looks for a bridge that
    is down, a few times over, and is free again.
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
# Script numbers: a spy's is its target's, from here.
_SPY_CODE: Final[int] = 7000


def spies(ctx: Context, country: Country) -> Iterator[Order]:
    """A spy for every class of building worth entering."""
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
