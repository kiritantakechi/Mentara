"""Role slots: which unit fills each place in a team.

A slot is a predicate over a unit's role tags and a score; per country
and tier the best-scoring unit the country fields fills it. A slot's
rank becomes its unit's `LeadershipRating`: the member with the highest
rating leads a team and picks its targets.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
lazy from collections.abc import Iterable

from mentara.mentalai.catalog import Kind, Role, Unit

__all__ = [
    "AA",
    "AIR",
    "ARTILLERY",
    "DETECTOR",
    "ENGINEER",
    "FAST",
    "FRONT",
    "HERO",
    "HIJACKER",
    "INFANTRY",
    "NAVAL_AA",
    "NAVAL_ARTILLERY",
    "NAVAL_FRONT",
    "NAVAL_HUNTER",
    "OCCUPIER",
    "RAIDER",
    "SCREEN",
    "SIEGE",
    "SKY_GUARD",
    "SPY",
    "STEALTH",
    "STRIKER",
    "SUPPORT",
    "TRANSPORT",
    "Filled",
    "Slot",
    "counter_slot",
    "fill",
]

# A TaskForce holds at most six member types (TaskForceClass::Entries).
_TASK_FORCE_TYPES_MAX: Final[int] = 6
_COST_MIN: Final[int] = 1
_SCREEN_RANGE_MIN: Final[float] = 3.0
_TOP_TIER: Final[int] = 3

type _Score = Callable[[Unit, int], float]
type _Fits = Callable[[Unit], bool]
type Filled = tuple[tuple[tuple[int, str], ...], dict[str, int]]


@dataclass(frozen=True, slots=True)
class Slot:
    """A role in a team.

    Attributes:
        name: Display name; families name required slots by it.
        fits: Whether a unit may fill the slot.
        score: How well a unit fills it at a tier; the best is taken.
        rank: The `LeadershipRating` its unit gets.
        fallback: A slot tried when no unit fits this one.
    """

    name: str
    fits: _Fits
    score: _Score
    rank: int
    fallback: Slot | None = None


def _ground(unit: Unit) -> bool:
    return not unit.roles & {Role.AIRBORNE, Role.NAVAL}


# Units with a job of their own never fill a combat slot.
_NON_COMBAT: Final[frozenset[Role]] = frozenset(
    {
        Role.HARVESTER,
        Role.MCV,
        Role.DEPLOYER,
        Role.ENGINEER,
        Role.INFILTRATOR,
    }
)


def _fighter(unit: Unit) -> bool:
    return _ground(unit) and not unit.roles & _NON_COMBAT


def _vitality(unit: Unit) -> float:
    return math.sqrt(max(unit.strength, 1) / 100)


def _cost(unit: Unit) -> float:
    return float(max(unit.cost, _COST_MIN))


def _front_score(unit: Unit, tier: int) -> float:
    # Late waves buy the strongest hull; early ones the best value.
    exponent = 0.0 if tier >= _TOP_TIER else 0.5
    return unit.strength * unit.firepower.vehicle / math.pow(_cost(unit), exponent)


def _screen_fits(unit: Unit) -> bool:
    fire = unit.firepower
    return (
        _fighter(unit)
        and unit.has(Role.GUN)
        and fire.range >= _SCREEN_RANGE_MIN
        and (
            unit.has(Role.ANTI_INFANTRY)
            or (unit.has(Role.DUAL) and fire.infantry >= fire.vehicle)
        )
        and not unit.roles & {Role.ARTILLERY, Role.HERO, Role.TRANSPORT}
    )


def _aa_score(unit: Unit, _tier: int) -> float:
    double = 2.0 if unit.has(Role.AA_ONLY) else 1.0
    return unit.firepower.air / _cost(unit) * _vitality(unit) * double


def _artillery_score(unit: Unit, _tier: int) -> float:
    fire = unit.firepower
    best = max(fire.infantry, fire.vehicle, fire.building)
    return fire.range * best * _vitality(unit) / _cost(unit)


def _siege_score(unit: Unit, _tier: int) -> float:
    fire = unit.firepower
    return fire.range * fire.building * _vitality(unit) / _cost(unit)


def _cheapest(unit: Unit, _tier: int) -> float:
    return 1 / _cost(unit)


def _armed_vehicle(unit: Unit) -> bool:
    return (
        _fighter(unit)
        and unit.kind is Kind.VEHICLE
        and unit.has(Role.GUN)
        and bool(unit.roles & {Role.ANTI_ARMOUR, Role.DUAL})
        and not unit.roles & {Role.ARTILLERY, Role.HERO}
    )


# A side with no main battle tank at a tier leads with its best armed
# combat vehicle instead, an armed carrier included.
_FRONT_FALLBACK: Final[Slot] = Slot("front", _armed_vehicle, _front_score, rank=12)
FRONT: Final[Slot] = Slot(
    "front",
    lambda u: _fighter(u) and u.has(Role.MBT) and not u.has(Role.HERO),
    _front_score,
    rank=12,
    fallback=_FRONT_FALLBACK,
)
SCREEN: Final[Slot] = Slot(
    "screen",
    _screen_fits,
    lambda u, _t: u.firepower.infantry / _cost(u) * _vitality(u),
    rank=8,
)
AA: Final[Slot] = Slot(
    "aa",
    lambda u: (
        _fighter(u) and u.has(Role.AA) and not u.roles & {Role.HERO, Role.TRANSPORT}
    ),
    _aa_score,
    rank=6,
)
# Anti-air that stays home for aircraft: anti-air-only units first.
SKY_GUARD: Final[Slot] = Slot("sky guard", AA.fits, _aa_score, rank=6)
ARTILLERY: Final[Slot] = Slot(
    "artillery",
    lambda u: _fighter(u) and u.has(Role.ARTILLERY) and not u.has(Role.HERO),
    _artillery_score,
    rank=10,
)
SIEGE: Final[Slot] = Slot(
    "siege",
    lambda u: _fighter(u) and u.has(Role.SIEGE) and not u.has(Role.HERO),
    _siege_score,
    rank=10,
)
SUPPORT: Final[Slot] = Slot(
    "support",
    lambda u: _fighter(u) and bool(u.roles & {Role.HEALER, Role.REPAIRER}),
    _cheapest,
    rank=4,
)
DETECTOR: Final[Slot] = Slot(
    "detector",
    lambda u: (
        _fighter(u)
        and u.has(Role.DETECTOR, Role.GUN)
        and u.firepower.range >= _SCREEN_RANGE_MIN
        and not u.has(Role.HERO)
    ),
    lambda u, _t: (u.firepower.infantry + u.firepower.vehicle) / _cost(u),
    rank=4,
)
HERO: Final[Slot] = Slot(
    "hero",
    lambda u: u.kind is Kind.INFANTRY and _fighter(u) and u.has(Role.HERO, Role.GUN),
    lambda u, _t: u.firepower.infantry + u.firepower.vehicle + u.firepower.building,
    rank=9,
)
RAIDER: Final[Slot] = Slot(
    "raider",
    _armed_vehicle,
    lambda u, _t: u.firepower.vehicle * u.speed / _cost(u),
    rank=8,
)
# The fastest armed units that hurt buildings, for feints that must
# outrun the response.
FAST: Final[Slot] = Slot(
    "fast",
    lambda u: (
        _fighter(u)
        and u.has(Role.GUN)
        and u.firepower.building > 0
        and not u.roles & {Role.ARTILLERY, Role.HERO}
    ),
    lambda u, _t: (
        u.speed * max(u.firepower.infantry, u.firepower.vehicle) / math.sqrt(_cost(u))
    ),
    rank=8,
)
# Fast vehicles that hurt buildings, for factory blitzes and power
# raids; a raider only needs to hurt vehicles (harvesters).
STRIKER: Final[Slot] = Slot(
    "striker",
    lambda u: _armed_vehicle(u) and u.firepower.building > 0,
    lambda u, _t: u.firepower.building * u.speed / _cost(u),
    rank=8,
)
STEALTH: Final[Slot] = Slot(
    "stealth",
    lambda u: _fighter(u) and u.has(Role.STEALTH, Role.GUN) and not u.has(Role.HERO),
    lambda u, _t: (u.firepower.vehicle + u.firepower.building) / _cost(u),
    rank=8,
)
AIR: Final[Slot] = Slot(
    "air",
    lambda u: (
        u.has(Role.AIRBORNE, Role.GUN)
        and not u.roles & (_NON_COMBAT | {Role.HERO, Role.NAVAL})
    ),
    lambda u, _t: (
        max(u.firepower.infantry, u.firepower.vehicle, u.firepower.building) / _cost(u)
    ),
    rank=8,
)
NAVAL_FRONT: Final[Slot] = Slot(
    "naval front",
    lambda u: (
        u.has(Role.NAVAL, Role.GUN) and not u.roles & (_NON_COMBAT | {Role.TRANSPORT})
    ),
    lambda u, _t: (
        u.strength
        * max(u.firepower.vehicle, u.firepower.building)
        / math.sqrt(_cost(u))
    ),
    rank=12,
)
NAVAL_HUNTER: Final[Slot] = Slot(
    "naval hunter",
    lambda u: (
        u.has(Role.NAVAL, Role.GUN)
        and bool(u.roles & {Role.ANTI_ARMOUR, Role.DUAL})
        and not u.roles & (_NON_COMBAT | {Role.TRANSPORT, Role.ARTILLERY})
    ),
    lambda u, _t: u.firepower.vehicle * _vitality(u) / _cost(u),
    rank=12,
)
NAVAL_AA: Final[Slot] = Slot(
    "naval aa",
    lambda u: u.has(Role.NAVAL, Role.AA) and not u.roles & _NON_COMBAT,
    _aa_score,
    rank=6,
)
NAVAL_ARTILLERY: Final[Slot] = Slot(
    "naval artillery",
    lambda u: u.has(Role.NAVAL, Role.ARTILLERY) and not u.roles & _NON_COMBAT,
    _siege_score,
    rank=10,
)
ENGINEER: Final[Slot] = Slot(
    "engineer",
    lambda u: u.kind is Kind.INFANTRY and u.has(Role.ENGINEER),
    _cheapest,
    rank=1,
)
SPY: Final[Slot] = Slot(
    "spy",
    lambda u: u.kind is Kind.INFANTRY and u.has(Role.INFILTRATOR),
    _cheapest,
    rank=1,
)
HIJACKER: Final[Slot] = Slot(
    "hijacker",
    lambda u: u.kind is Kind.INFANTRY and u.has(Role.HIJACKER),
    _cheapest,
    rank=2,
)
OCCUPIER: Final[Slot] = Slot(
    "occupier",
    lambda u: (
        u.kind is Kind.INFANTRY and _fighter(u) and u.has(Role.OCCUPIER, Role.GUN)
    ),
    lambda u, _t: max(u.firepower.infantry, u.firepower.vehicle) / _cost(u),
    rank=3,
)
INFANTRY: Final[Slot] = Slot(
    "infantry",
    lambda u: u.kind is Kind.INFANTRY and _fighter(u) and not u.has(Role.HERO),
    _cheapest,
    rank=2,
)
TRANSPORT: Final[Slot] = Slot(
    "transport",
    lambda u: (
        _ground(u)
        and u.kind is Kind.VEHICLE
        and u.has(Role.TRANSPORT)
        and u.size_limit > 0
        and not u.roles & _NON_COMBAT
    ),
    lambda u, _t: u.passengers * u.speed * _vitality(u) / _cost(u),
    rank=5,
)


def counter_slot(armor: str, *, airborne: bool, naval: bool) -> Slot:
    """The slot for units that kill one armour best for their cost.

    Args:
        armor: The target's armour, lower-case.
        airborne: Whether the target flies: anti-air weapons count.
        naval: Whether the target is a ship: our ships fill the slot.

    Returns:
        The slot.
    """

    def damage(unit: Unit) -> float:
        fire = unit.firepower
        table = fire.air_against if airborne else fire.against
        return table.get(armor, 0.0)

    def fits(unit: Unit) -> bool:
        if unit.roles & (_NON_COMBAT | {Role.HERO, Role.TRANSPORT}):
            return False
        place = unit.has(Role.NAVAL) if naval else _ground(unit)
        return place and damage(unit) > 0

    # A unit's rating is global: a counter must not outrank the front
    # line in the mixed teams the same unit joins.
    return Slot(
        f"counter {armor}",
        fits,
        lambda u, _t: damage(u) * _vitality(u) / _cost(u),
        rank=5,
    )


def fill(
    slots: Iterable[tuple[Slot, int]],
    units: Iterable[Unit],
    tier: int,
    *,
    required: Iterable[str] = (),
    skip_detector: bool = True,
) -> Filled | None:
    """Fill slots from the units a country fields.

    Each slot takes its best-scoring unit; a unit already chosen for an
    earlier slot adds to that member instead of a new type. A detector
    slot is skipped when a chosen unit already detects.

    Args:
        slots: Slots and their counts, in leading order.
        units: The units to choose from.
        tier: The tier the team is built for.
        required: Slot names that must be filled.
        skip_detector: Whether a chosen detector makes the detector slot
            redundant.

    Returns:
        The members and each member's leadership rank, or None when a
        required slot stays empty or nothing fits.
    """
    pool = tuple(units)
    needed = frozenset(required)
    counts: dict[str, int] = {}
    ranks: dict[str, int] = {}
    chosen: dict[str, Unit] = {}
    for slot, count in slots:
        detects = any(u.has(Role.DETECTOR) for u in chosen.values())
        if slot is DETECTOR and skip_detector and detects:
            continue
        candidates = [u for u in pool if slot.fits(u)]
        if not candidates and slot.fallback is not None:
            candidates = [u for u in pool if slot.fallback.fits(u)]
        if not candidates:
            if slot.name in needed:
                return None
            continue
        best = max(candidates, key=lambda u: (slot.score(u, tier), u.id))
        if best.id not in counts and len(counts) >= _TASK_FORCE_TYPES_MAX:
            continue
        counts[best.id] = counts.get(best.id, 0) + count
        ranks[best.id] = max(ranks.get(best.id, 0), slot.rank)
        chosen[best.id] = best
    if not counts:
        return None
    ordered = sorted(counts, key=lambda unit_id: -ranks[unit_id])
    return tuple((counts[u], u) for u in ordered), ranks
