"""Everything a transport sets down in the enemy's base.

Engineers, saboteurs, a rush of infantry and a hero beside a
superweapon, each by land, by air and by sea; and a landing: a hover
transport's load of tanks and infantry put ashore behind the base.

The engine decides when a team goes by sea (gamemd 0x41FEE0, 0x6F1FA0).
A team with a naval transport and no warship is raised only while its
other members cannot reach the chosen enemy's base overland and an
amphibious unit can; a team with no ship or aircraft only while they
can. So on a map of islands the sea teams here are all the ground
forces a house sends, and on any other map they are never raised.
"""

from dataclasses import dataclass, replace
from typing import Final
lazy from collections.abc import Callable, Iterator, Mapping

from mentara.mentalai import scripts as sc
from mentara.mentalai.families._kit import (
    DROP,
    LANDING,
    TIERS,
    TOP,
    Context,
    Order,
    Series,
    at_tier,
    on_call,
    unlocked,
)
from mentara.mentalai.model import (
    Gate,
    Squad,
)
from mentara.mentalai.scripts import Script, Target
from mentara.mentalai.slots import (
    AA,
    AIR_TRANSPORT,
    BOMBER,
    ENGINEER,
    FRONT,
    HERO,
    INFANTRY,
    SCREEN,
    SEA_TRANSPORT,
    TRANSPORT,
    Seats,
    Slot,
    fill,
)
lazy from mentara.mentalai.catalog import Country, Unit
lazy from mentara.mentalai.model import Crew, Member
lazy from mentara.mentalai.scripts import Lines


@dataclass(frozen=True, slots=True)
class _Way:
    """How a transport gets there.

    Attributes:
        carrier: The slot its transport fills.
        step: Its squads are numbered this far past the same drop by
            land.
        hero_step: The same for a hero's drop, which has a squad per
            superweapon building.
    """

    carrier: Slot
    step: int
    hero_step: int


# In the order a payload names them.
_LAND: Final[_Way] = _Way(TRANSPORT, 0, 0)
_AIR: Final[_Way] = _Way(AIR_TRANSPORT, 10, 50)
_SEA: Final[_Way] = _Way(SEA_TRANSPORT, 5, 25)
_WAYS: Final[tuple[_Way, ...]] = (_LAND, _AIR, _SEA)

_DROP_TARGETS: Final[Mapping[Target, str]] = frozendict(
    {
        Target.POWER: "Power",
        Target.FACTORIES: "Factory",
        Target.CONSTRUCTION_YARD: "Yard",
    }
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
_HERO_DROPS: Final[tuple[str, ...]] = ("Hero Drop", "Hero Air Drop", "Hero Sea Drop")
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
        names: What the drop is called, by each way.
        rider: The slot its riders fill.
        seats: The fewest riders a transport must seat, and the most it
            takes.
        place: Its first squad number in the series, by land.
        purpose: What the riders do once out.
        targets: The classes of building it rides to, and their names.
        weight: Each of its triggers' weight.
    """

    names: tuple[str, ...]
    rider: Slot
    seats: tuple[int, int]
    place: int
    purpose: _Purpose
    targets: Mapping[Target, str]
    weight: int


_PAYLOADS: Final[tuple[_Payload, ...]] = (
    # Engineers take what they are set down beside.
    _Payload(
        ("Engineer Drop", "Air Drop", "Sea Drop"),
        ENGINEER,
        (2, 2),
        0,
        _ENTER,
        _DROP_TARGETS,
        10,
    ),
    # Bomb planters: MO's Ivans by Borillo and Driller, its SEALs by
    # Stallion.
    _Payload(
        ("Sabotage", "Air Sabotage", "Sea Sabotage"),
        BOMBER,
        (1, 3),
        20,
        _WRECK,
        frozendict({Target.POWER: "Power", Target.FACTORIES: "Factory"}),
        12,
    ),
    # A transport full of infantry: MO's Borillo and Armadillo rushes.
    _Payload(
        ("Rush", "Air Assault", "Sea Assault"),
        _STORMER,
        (3, 6),
        40,
        _WRECK,
        _DROP_TARGETS,
        15,
    ),
)


def drops(ctx: Context, country: Country) -> Iterator[Order]:
    """Engineers, saboteurs, a rush and a hero, by each way there is."""
    for payload in _PAYLOADS:
        for way, name in zip(_WAYS, payload.names, strict=True):
            yield from _drops(ctx, country, payload, way, name)
    for way, name in zip(_WAYS, _HERO_DROPS, strict=True):
        yield from _hero_drops(ctx, country, way, name)


def _drops(
    ctx: Context, country: Country, payload: _Payload, way: _Way, name: str
) -> Iterator[Order]:
    """A payload carried next to each of its targets.

    It waits for the tier of its transport, the second at least.
    """
    crew = _drop_crew(ctx, country, payload.rider, payload.seats, way)
    gate = None if crew is None else unlocked(country, crew, floor=2)
    if crew is None or gate is None:
        return
    first = payload.place + way.step
    purpose = payload.purpose
    for index, (target, place) in enumerate(payload.targets.items(), start=1):
        script = Script(
            purpose.code + target, f"{purpose.name} vs {place}", purpose.write(target)
        )
        squad = Squad(
            Series.DROP.at(first + index),
            f"{name} vs {place}",
            crew,
            script,
            DROP,
            max_teams=1,
        )
        yield from on_call(squad, gate, payload.weight)


def _hero_drops(
    ctx: Context, country: Country, way: _Way, name: str
) -> Iterator[Order]:
    """A hero set down beside each superweapon the enemy owns.

    MO's own Mental AI flies Tanya at a nuclear silo; here every side
    sends its best wrecker, by every way it has. The enemy's building
    is all a trigger waits for.
    """
    crew = _drop_crew(ctx, country, _WRECKER, (1, 1), way)
    if crew is None:
        return
    for place, building in enumerate(ctx.superweapon_buildings, start=1):
        index = ctx.catalog.building_index(building)
        script = Script(
            _HERO_DROP_CODE + index, f"Hero Drop vs {building}", sc.strike_drop(index)
        )
        squad = Squad(
            Series.HERO_DROP.at(way.hero_step + place),
            f"{name} vs {building}",
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
    way: _Way,
) -> Crew | None:
    """A transport and the riders it seats.

    Vanilla 14 seats them in one transport, an aircraft first.

    Args:
        ctx: What every family shares.
        country: The country.
        rider: The slot the riders fill.
        seats: The fewest riders the transport must seat, and the most
            it takes.
        way: How the transport gets there.

    Returns:
        The crew, the highest-ranked first, or None when the country
        has no such rider or no such transport that seats enough of
        them.
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
        u for u in units if u.size_limit >= aboard.unit.size and room(u) >= fewest
    )
    transport = fill(((way.carrier, 1),), carriers, TOP)
    if transport is None:
        return None
    crew = (*transport, replace(aboard, count=min(most, room(transport[0].unit))))
    return tuple(sorted(crew, key=lambda member: -member.rank))


# A landing party: tanks first, then the infantry and anti-air the
# transport still has room for.
_PARTY_SEATS: Final[Seats] = ((FRONT, 3), (SCREEN, 2), (AA, 1))
_LANDING_TARGETS: Final[Mapping[Target, str]] = frozendict(
    {Target.POWER: "Power", Target.FACTORIES: "Factory"}
)
_LANDING_CODE: Final[int] = 7500
# A target's landings are numbered ten apart, by tier.
_LANDING_STEP: Final[int] = 10


def landings(ctx: Context, country: Country) -> Iterator[Order]:
    """A hover transport's load of a line, put ashore behind the base.

    MO's own AI never crossed water with its tanks: its Voyagers and
    Zubrs sailed as warships and its Mandjets and Watercats not at all.
    Here each tier's tanks, infantry and anti-air board one, cross to
    the far side of the chosen enemy's base and storm its power or its
    factories.
    """
    casts = country.front_casts
    for tier in TIERS:
        gate = at_tier(country, tier)
        crew = None if gate is None else _landing_party(ctx, country, tier)
        if gate is None or crew is None:
            continue
        for place, (target, name) in enumerate(_LANDING_TARGETS.items()):
            script = Script(
                _LANDING_CODE + target,
                f"Landing vs {name}",
                sc.landing(target, casts),
            )
            squad = Squad(
                Series.LANDING.at(_LANDING_STEP * place + tier),
                f"{script.name} T{tier}",
                crew,
                script,
                LANDING,
                max_teams=1,
            )
            yield from on_call(squad, gate, 30)


def _landing_party(ctx: Context, country: Country, tier: int) -> Crew | None:
    """A sea transport and what of a party fits it, the tanks first."""
    units = ctx.fielded(country, tier)
    boats = fill(((SEA_TRANSPORT, 1),), units, tier)
    if boats is None:
        return None
    boat = boats[0].unit
    fits = (u for u in units if 0 < u.size <= boat.size_limit)
    party = fill(_PARTY_SEATS, fits, tier, required=(FRONT,))
    if party is None:
        return None
    room = boat.passengers
    aboard: list[Member] = []
    for member in party:
        count = min(member.count, room // member.unit.size)
        if count:
            room -= count * member.unit.size
            aboard.append(replace(member, count=count))
    return tuple(sorted((*boats, *aboard), key=lambda member: -member.rank))
