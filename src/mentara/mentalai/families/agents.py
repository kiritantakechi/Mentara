"""Teams that walk into buildings.

Engineers at the map's tech and bridges, infantry and tanks into
garrisons, bunkers and reactors, hijackers, spies, and everything a
transport sets down in the enemy's base: engineers, saboteurs, a rush
of infantry, and a hero beside a superweapon.
"""

from dataclasses import dataclass, replace
from typing import Final
lazy from collections.abc import Callable, Iterator, Mapping

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
    BOMBER,
    ENGINEER,
    FRONT,
    HERO,
    HIJACKER,
    INFANTRY,
    OCCUPIER,
    SCREEN,
    SPY,
    TRANSPORT,
    Seats,
    Slot,
    fill,
)
lazy from mentara.mentalai.catalog import Unit
lazy from mentara.mentalai.scripts import Lines


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
_DROP_TARGETS: Final[Mapping[Target, str]] = frozendict(
    {
        Target.POWER: "Power",
        Target.FACTORIES: "Factory",
        Target.CONSTRUCTION_YARD: "Yard",
    }
)
# Script numbers: a spy's is its target's, from here.
_SPY_CODE: Final[int] = 7000
# An air drop is numbered this far past the same drop by land.
_AIR_DROP_STEP: Final[int] = 10
# An aircraft that carries infantry: the faster and roomier the better.
_AIR_TRANSPORT: Final[Slot] = Slot(
    "air transport",
    lambda u: u.has(Role.AIRBORNE, Role.TRANSPORT),
    lambda u, _t: u.passengers * u.speed,
    rank=5,
)


# A hero that wrecks buildings: the better at it the better.
_WRECKER: Final[Slot] = Slot(
    "wrecker",
    lambda u: HERO.fits(u) and u.firepower.building > 0,
    lambda u, _t: u.firepower.building,
    rank=HERO.rank,
)
# A hero drop's script is numbered by its building's index, from here.
_HERO_DROP_CODE: Final[int] = 72000
# A hero's air drop is numbered this far past the same drop by land.
_HERO_AIR_STEP: Final[int] = 50


# Infantry for a rush: what wrecks the most buildings before it falls,
# for its cost. MO's own rushes carried flamethrowers, Enforcers and
# Tesla troopers; a dog, which only bites, has no place in one.
_STORMER: Final[Slot] = Slot(
    "stormer",
    lambda u: INFANTRY.fits(u) and u.firepower.building > 0,
    lambda u, _t: u.firepower.building * u.strength / max(u.cost, 1),
    rank=SCREEN.rank,
)


@dataclass(frozen=True, slots=True)
class _Purpose:
    """What riders do once a transport has set them down.

    Attributes:
        name: What the script is called ("Drop").
        code: Its scripts are numbered by their target, from here.
        write: The script for a target.
    """

    name: str
    code: int
    write: Callable[[Target], Lines]


_ENTER: Final[_Purpose] = _Purpose("Drop", 7100, sc.drop)
_WRECK: Final[_Purpose] = _Purpose("Rush", 7400, sc.rush)


@dataclass(frozen=True, slots=True)
class _Payload:
    """Who a transport sets down, and where.

    Attributes:
        names: What the drop is called, by land and by air.
        rider: The slot its riders fill.
        seats: The fewest riders a transport must seat, and the most it
            takes.
        place: Its first squad number in the series, by land.
        purpose: What the riders do once out.
        targets: The classes of building it rides to, and their names.
        weight: Each of its triggers' weight.
    """

    names: tuple[str, str]
    rider: Slot
    seats: tuple[int, int]
    place: int
    purpose: _Purpose
    targets: Mapping[Target, str]
    weight: int


_PAYLOADS: Final[tuple[_Payload, ...]] = (
    # Engineers take what they are set down beside.
    _Payload(
        ("Engineer Drop", "Air Drop"), ENGINEER, (2, 2), 0, _ENTER, _DROP_TARGETS, 10
    ),
    # Bomb planters: MO's Ivans by Borillo and Driller, its SEALs by
    # Stallion.
    _Payload(
        ("Sabotage", "Air Sabotage"),
        BOMBER,
        (1, 3),
        20,
        _WRECK,
        frozendict({Target.POWER: "Power", Target.FACTORIES: "Factory"}),
        12,
    ),
    # A transport full of infantry: MO's Borillo and Armadillo rushes.
    _Payload(("Rush", "Air Assault"), _STORMER, (3, 6), 40, _WRECK, _DROP_TARGETS, 15),
)


def infiltration(ctx: Context, country: Country) -> Iterator[Order]:
    """Spies on every class of building, and drops by land and air."""
    yield from _spies(ctx, country)
    for payload in _PAYLOADS:
        yield from _drops(ctx, country, payload, airborne=False)
        yield from _drops(ctx, country, payload, airborne=True)
    yield from _hero_drops(ctx, country, "Hero Drop", airborne=False)
    yield from _hero_drops(ctx, country, "Hero Air Drop", airborne=True)


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
    ctx: Context, country: Country, payload: _Payload, *, airborne: bool
) -> Iterator[Order]:
    """A payload driven or flown next to each of its targets.

    It waits for the tier of its transport, the second at least.
    """
    crew = _drop_crew(ctx, country, payload.rider, payload.seats, airborne=airborne)
    gate = None if crew is None else unlocked(country, crew, floor=2)
    if crew is None or gate is None:
        return
    way = payload.names[airborne]
    first = payload.place + _AIR_DROP_STEP * airborne
    purpose = payload.purpose
    for index, (target, name) in enumerate(payload.targets.items(), start=1):
        script = Script(
            purpose.code + target, f"{purpose.name} vs {name}", purpose.write(target)
        )
        squad = Squad(
            Series.DROP.at(first + index),
            f"{way} vs {name}",
            crew,
            script,
            DROP,
            max_teams=1,
        )
        yield from on_call(squad, gate, payload.weight)


def _hero_drops(
    ctx: Context, country: Country, way: str, *, airborne: bool
) -> Iterator[Order]:
    """A hero set down beside each superweapon the enemy owns.

    MO's own Mental AI flies Tanya at a nuclear silo; here every side
    sends its best wrecker, by land and by air. The enemy's building is
    all a trigger waits for.
    """
    crew = _drop_crew(ctx, country, _WRECKER, (1, 1), airborne=airborne)
    if crew is None:
        return
    first = _HERO_AIR_STEP * airborne
    for place, building in enumerate(ctx.superweapon_buildings, start=1):
        index = ctx.catalog.building_index(building)
        script = Script(
            _HERO_DROP_CODE + index, f"Hero Drop vs {building}", sc.strike_drop(index)
        )
        squad = Squad(
            Series.HERO_DROP.at(first + place),
            f"{way} vs {building}",
            crew,
            script,
            DROP,
            max_teams=1,
        )
        yield from on_call(squad, Gate.enemy_owns(building), 50)


def _drop_crew(
    ctx: Context,
    country: Country,
    rider: Slot,
    seats: tuple[int, int],
    *,
    airborne: bool,
) -> Crew | None:
    """A transport and the riders it seats, by land or air.

    Vanilla 14 seats them in one transport, an aircraft first.

    Args:
        ctx: What every family shares.
        country: The country.
        rider: The slot the riders fill.
        seats: The fewest riders the transport must seat, and the most
            it takes.
        airborne: Whether the transport flies.

    Returns:
        The crew, the highest-ranked first, or None when the country
        has no such rider or no transport that seats enough of them.
    """
    units = ctx.fielded(country, TOP)
    riders = fill(((rider, 1),), units, TOP)
    if riders is None:
        return None
    aboard = riders[0]
    fewest, most = seats

    def room(unit: Unit) -> int:
        return unit.passengers // max(aboard.unit.size, 1)

    carriers = tuple(
        u
        for u in units
        if u.size_limit >= aboard.unit.size
        and room(u) >= fewest
        and u.has(Role.AIRBORNE) == airborne
        and u.has(Role.TRANSPORT)
        and not u.roles & {Role.NAVAL, Role.HARVESTER, Role.MCV}
    )
    seat = _AIR_TRANSPORT if airborne else TRANSPORT
    transport = fill(((seat, 1),), carriers, TOP)
    if transport is None:
        return None
    crew = (*transport, replace(aboard, count=min(most, room(transport[0].unit))))
    return tuple(sorted(crew, key=lambda member: -member.rank))
