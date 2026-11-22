"""What every family is written in.

The number series, the context all families share, the gates a trigger
waits at, the doctrines a squad follows, and the helpers that put a
crew on call as a squad.

A squad's or trigger's number is four digits: its series, then a tier,
a variant or a count within it (`0102` is the tier-2 direct line). See
`overlays/README.md`.
"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Final

from mentara.mentalai.catalog import Catalog, Country, Factory, Role, Unit
from mentara.mentalai.model import (
    Call,
    Conduct,
    Crew,
    Gate,
    Member,
    MindControl,
    Squad,
)
from mentara.mentalai.slots import (
    Seats,
    Slot,
    fill,
)
lazy from mentara.mentalai.catalog import Firepower
lazy from mentara.mentalai.scripts import Quarry

type Order = Squad | Call
type Family = Callable[[Context, Country], Iterator[Order]]
# A number per tier, 1 to 3; zero where a tier has none.
type ByTier = tuple[int, int, int]

TIERS: Final[tuple[int, ...]] = (1, 2, 3)
TOP: Final[int] = 3


class Series(Enum):
    """The first two digits of a squad's or a trigger's number."""

    LINE = 1
    FLANK = 2
    HUNT = 3
    LINE_AIR = 4
    SIEGE = 5
    SIEGE_AIR = 6
    BLITZ = 7
    FEINT = 8
    ECONOMY_RAID = 9
    POWER_RAID = 10
    STEALTH_RAID = 11
    PINCER = 12
    AIR_STRIKE = 13
    FEINT_STRIKE = 14
    WATCH = 15
    PATROL = 16
    TECH_GUARD = 17
    SKY_GUARD = 18
    SNIPE = 19
    CAPTURE = 20
    GARRISON = 21
    BATTLE_BUNKER = 22
    TANK_BUNKER = 23
    BIO_REACTOR = 24
    HIJACK = 25
    SPY = 26
    DROP = 27
    BRIDGE = 28
    STARVE = 29
    NAVY = 30
    SUB_HUNT = 31
    BOMBARDMENT = 32
    FLOTILLA = 33
    SIEGE_ESCORT = 34
    CHRONO = 35
    CURTAIN = 36
    BOOST = 37
    BLACKOUT = 38
    FINISH = 39
    GRID = 40
    SQUADRON = 41
    HERO = 42
    DEPLOYER = 43
    BOMBER = 44
    CARRIER = 45
    STRIKE_GROUP = 46
    CHARGE = 47
    CURTAIN_CHARGE = 48
    HERO_DROP = 49
    # One trigger per notable enemy unit, and one squad per armour and
    # tier: both run past their hundred, the squads as far as 79.
    COUNTER_CALL = 50
    COUNTER = 60
    AIR_SUPPORT = 80
    MINER_HUNT = 81
    AIR_COVER = 82
    INTERCEPT = 83
    LANDING = 84
    PSYCHIC = 85
    COMPANY = 86
    SPECIALIST = 87
    ESCORT = 88
    MINER_GUARD = 89
    YARD = 99

    def at(self, place: int = 0) -> int:
        """The series' number at a place: a tier, or a count."""
        return self.value * 100 + place

    def variant(self, tier: int, rank: int = 0) -> int:
        """The number of a tier's rank-th best filling."""
        return self.at(10 * rank + tier)


@dataclass(frozen=True, slots=True)
class Key:
    """What a counter answers: an armour, in the air, at sea or not."""

    armor: str
    airborne: bool
    naval: bool


@dataclass(frozen=True, slots=True)
class Notable:
    """An enemy unit worth a counter, and the tier it appears at."""

    unit: Unit
    tier: int
    key: Key


# Not frozen: counter squads register their target lists as they form.
@dataclass(slots=True)
class Context:
    """What every family shares: the catalog and the rules-side lists.

    Attributes:
        catalog: Units and countries.
        notable: Enemy units worth a counter, from every country.
        keys: The counter keys, in index order.
        airfields: Every country's aircraft factories.
        shipyards: Every country's shipyard.
        superweapon_buildings: Every country's superweapon buildings.
        target_lists: Phobos `[AITargetTypes]` lists, registered in
            index order.
    """

    catalog: Catalog
    notable: tuple[Notable, ...]
    keys: tuple[Key, ...]
    airfields: tuple[str, ...]
    shipyards: tuple[str, ...]
    superweapon_buildings: tuple[str, ...]
    target_lists: list[tuple[str, ...]] = field(default_factory=list)

    @classmethod
    def build(cls, catalog: Catalog) -> Context:
        """Gather the cross-country lists once.

        Args:
            catalog: Units and countries.

        Returns:
            The context.
        """
        countries = catalog.countries
        notable = _notable_units(catalog)
        keys = {n.key for n in notable}
        return cls(
            catalog=catalog,
            notable=notable,
            keys=tuple(sorted(keys, key=lambda k: (k.airborne, k.naval, k.armor))),
            airfields=_unique(b for c in countries for b in c.airfields),
            shipyards=_unique(
                c.factories[Factory.SHIPYARD]
                for c in countries
                if Factory.SHIPYARD in c.factories
            ),
            superweapon_buildings=_unique(
                b for c in countries for b in c.superweapon_buildings
            ),
        )

    def target_list(self, units: tuple[str, ...]) -> int:
        """The index of an `[AITargetTypes]` list, added if new."""
        if units not in self.target_lists:
            self.target_lists.append(units)
        return self.target_lists.index(units)

    def fielded(self, country: Country, tier: int) -> tuple[Unit, ...]:
        """The units a country fields by a tier."""
        return self.catalog.fielded(country, tier)


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


# An enemy unit is worth a counter when it costs this much, flies,
# shells from the sea, or is a hero.
_NOTABLE_COST: Final[int] = 1000
_NO_COUNTER: Final[frozenset[Role]] = frozenset(
    {Role.HARVESTER, Role.MCV, Role.DEPLOYER, Role.ENGINEER, Role.INFILTRATOR}
)


def _is_notable(unit: Unit) -> bool:
    if unit.roles & _NO_COUNTER or not unit.roles & {Role.GUN, Role.AA}:
        return False
    return (
        unit.cost >= _NOTABLE_COST
        or unit.has(Role.HERO)
        or unit.has(Role.AIRBORNE, Role.GUN)
        or unit.has(Role.NAVAL, Role.ARTILLERY)
    )


def _notable_units(catalog: Catalog) -> tuple[Notable, ...]:
    """Enemy units worth a counter: costly, flying, shelling or heroic.

    A unit several countries field takes the lowest tier any of them
    reaches it at.
    """
    tiers: dict[str, int] = {}
    for country in catalog.countries:
        for name, tier in country.units.items():
            unit = catalog.units.get(name)
            if unit is not None and _is_notable(unit):
                tiers[unit.id] = min(tiers.get(unit.id, tier), tier)
    return tuple(
        Notable(
            unit=unit,
            tier=tiers[unit.id],
            key=Key(
                armor=unit.armor,
                airborne=unit.has(Role.AIRBORNE),
                naval=unit.has(Role.NAVAL),
            ),
        )
        for unit in catalog.units.values()
        if unit.id in tiers
    )


# --- Gates -----------------------------------------------------------
#
# The AI skips unit prerequisites: the building a trigger waits for is
# all that holds a unit back until its tech stands.


def at_tier(country: Country, tier: int) -> Gate | None:
    """While the country stands at a tier.

    Tier 1 runs until the country owns its tier-2 building (the one
    that unlocks most of that tier); higher tiers once it owns theirs.
    """
    building = country.gates.get(max(tier, 2))
    if building is None:
        return None
    return Gate.house_lacks(building) if tier == 1 else Gate.house_owns(building)


def from_tier(
    country: Country, tier: int, *, factory: Factory = Factory.BARRACKS
) -> Gate | None:
    """From a tier on: once the country owns the building it unlocks at.

    Tier 1 is unlocked by a factory: the barracks, or the shipyard for
    a ship.
    """
    building = country.factories.get(factory) if tier == 1 else country.gates.get(tier)
    return None if building is None else Gate.house_owns(building)


def unlocked(country: Country, crew: Crew, *, floor: int = 1) -> Gate | None:
    """From the highest tier among a crew's units on."""
    tiers = (country.units[member.unit.id.lower()] for member in crew)
    return from_tier(country, max(floor, *tiers))


def owned(building: str | None) -> Gate | None:
    """Once the house owns a building, if its country has one at all."""
    return None if building is None else Gate.house_owns(building)


# --- Doctrines --------------------------------------------------------
#
# How each kind of squad behaves; a squad's members then adjust it (see
# `Squad.conduct`).

# Drives straight in, fighting on the way.
ASSAULT: Final[Conduct] = Conduct(recruiter=True, mind_control=MindControl.JOIN_TEAM)
# Routes round the defences to the far side of the chosen enemy.
FLANK: Final[Conduct] = replace(ASSAULT, avoid_threats=True, enemy_only=True)
# Hunts the army; harassed on the way, it closes ranks first.
HUNTER: Final[Conduct] = replace(ASSAULT, annoyance=True)
# Slips past fights to its target.
RAID: Final[Conduct] = Conduct(aggressive=False, avoid_threats=True, recruiter=True)
# Makes itself seen at the chosen enemy's far side.
FEINT: Final[Conduct] = Conduct(enemy_only=True)
# Answers a threat the enemy fielded: it hunts only the chosen enemy's.
COUNTER: Final[Conduct] = replace(ASSAULT, enemy_only=True)
# Goes for one place and nothing else, ignoring damage on the way:
# agents, occupiers, charges and the MCV.
BEELINE: Final[Conduct] = Conduct(aggressive=False, avoid_threats=True, suicide=True)
# Drives agents in by transport and sends the transport home.
DROP: Final[Conduct] = replace(BEELINE, transports_return=True)
# Holds ground: closes ranks when harassed, refills when worn down,
# and sends the units it takes after the enemy.
GUARD: Final[Conduct] = Conduct(
    annoyance=True, reinforce=True, mind_control=MindControl.HUNT
)
WATCH: Final[Conduct] = replace(GUARD, base_defense=True)
# Flies to its target past what it meets.
SORTIE: Final[Conduct] = Conduct(aggressive=False, avoid_threats=True)
# Flies at what threatens the house, from the base or the front.
AIR_SUPPORT: Final[Conduct] = Conduct(recruiter=True)
# Crosses the water and lands behind the chosen enemy's base; the
# empty transport sails home.
LANDING: Final[Conduct] = replace(FLANK, transports_return=True)
# Goes where the house's forward units are and works beside them.
ESCORT: Final[Conduct] = Conduct(recruiter=True, annoyance=True)
# Flies now: it takes the craft it needs out of the squadron that has
# them, as MO's own aircraft did against a superweapon.
SCRAMBLE: Final[Conduct] = replace(SORTIE, urgent=True)
# --- Squads and their calls ------------------------------------------

# The rating of a squad's only member type: among its own kind any
# member may lead.
_SOLO_RANK: Final[int] = 8


def alone(unit: Unit, count: int) -> Crew:
    """A crew of one unit type."""
    return (Member(count, unit, _SOLO_RANK),)


# Airfield-bound craft fly in pairs: each needs a pad.
_FLIGHT: Final[int] = 4
_DOCKED_FLIGHT: Final[int] = 2


def squadron(craft: Unit) -> Crew:
    """A squadron's worth of one aircraft type."""
    return alone(craft, _DOCKED_FLIGHT if craft.has(Role.DOCKED) else _FLIGHT)


def on_call(squad: Squad, gate: Gate, weight: int) -> Iterator[Order]:
    """A squad, and a trigger of its number and name that raises it."""
    yield squad
    yield Call(squad.number, squad.label, squad=squad.number, gate=gate, weight=weight)


def answering(
    squad: Squad, gates: Iterable[tuple[str, Gate]], weight: int, *, step: int = 1
) -> Iterator[Order]:
    """A squad with a trigger per gate, numbered on from its own."""
    yield squad
    for index, (label, gate) in enumerate(gates, start=1):
        number = squad.number + step * index
        yield Call(number, label, squad=squad.number, gate=gate, weight=weight)


# Variants of a team: the best unit per slot, then the second and third
# best, so a side fields its whole roster and no two waves need look
# alike. Weights fall with the rank.
_VARIANT_SHARES: Final[tuple[float, ...]] = (1.0, 0.6, 0.4)


@dataclass(frozen=True, slots=True)
class Variant:
    """One filling of a team's slots: the best units, or the next."""

    tier: int
    rank: int
    crew: Crew

    def number(self, series: Series) -> int:
        return series.variant(self.tier, self.rank)

    def label(self, name: str) -> str:
        """The team's name, tier and, past the best, a letter."""
        letter = f" {chr(ord('A') + self.rank)}" if self.rank else ""
        return f"{name} T{self.tier}{letter}"

    def weight(self, weight: int) -> int:
        return max(1, round(weight * _VARIANT_SHARES[self.rank]))


def variants_of(
    seats: Seats,
    units: tuple[Unit, ...],
    tier: int,
    *,
    required: tuple[Slot, ...] = (),
) -> Iterator[Variant]:
    """Each distinct filling of the slots, best first."""
    seen: set[tuple[tuple[int, str], ...]] = set()
    for rank in range(len(_VARIANT_SHARES)):
        crew = fill(seats, units, tier, required=required, rank=rank)
        if crew is None:
            continue
        roll = tuple((member.count, member.unit.id) for member in crew)
        if roll not in seen:
            seen.add(roll)
            yield Variant(tier, rank, crew)


@dataclass(frozen=True, slots=True)
class Combo:
    """A trigger that raises two squads in the same frame.

    Attributes:
        series: The trigger's series.
        name: What the pair is.
        lead: The series of Team1's squad.
        support: The series of Team2's squad.
        weights: The trigger's weight at each tier.
    """

    series: Series
    name: str
    lead: Series
    support: Series
    weights: ByTier

    def calls(self, tier: int, gate: Gate) -> Iterator[Call]:
        """The trigger at a tier, if the pair is called there."""
        weight = self.weights[tier - 1]
        if weight:
            yield Call(
                self.series.at(tier),
                f"{self.name} T{tier}",
                squad=self.lead.variant(tier),
                gate=gate,
                weight=weight,
                support=self.support.variant(tier),
            )


# --- What a unit goes for --------------------------------------------


class Aim(Enum):
    """The class of target a unit hurts most."""

    BUILDINGS = "buildings"
    VEHICLES = "vehicles"
    INFANTRY = "infantry"


def harm(fire: Firepower, aim: Aim) -> float:
    """A firepower's damage per second against a class of target."""
    match aim:
        case Aim.BUILDINGS:
            return fire.building
        case Aim.VEHICLES:
            return fire.vehicle
        case Aim.INFANTRY:
            return fire.infantry


def aim_of(unit: Unit) -> Aim:
    """What a unit hurts most; a tie goes to what stands still."""
    return max(Aim, key=lambda aim: harm(unit.firepower, aim))


@dataclass(frozen=True, slots=True)
class Course:
    """A script number, and the two quarries a team takes in turn."""

    code: int
    quarries: tuple[Quarry, Quarry]


# --- A country's roster ----------------------------------------------

ARMED: Final[frozenset[Role]] = frozenset({Role.GUN, Role.EFFECT})
# A unit with one of these jobs fights in no ordinary squad.
OTHER_JOBS: Final[frozenset[Role]] = frozenset(
    {
        Role.HARVESTER,
        Role.MCV,
        Role.DEPLOYER,
        Role.ENGINEER,
        Role.INFILTRATOR,
        Role.HERO,
        Role.TRANSPORT,
        Role.CHARGER,
    }
)
OFF_GROUND: Final[frozenset[Role]] = frozenset({Role.AIRBORNE, Role.NAVAL})


def roster(
    ctx: Context, country: Country, fits: Callable[[Unit], bool]
) -> Iterator[tuple[Unit, int]]:
    """The country's units that fit, with their tiers."""
    for name, tier in country.units.items():
        unit = ctx.catalog.units.get(name)
        if unit is None or unit.has(Role.PLAYER_VERSION) or not fits(unit):
            continue
        yield unit, tier
