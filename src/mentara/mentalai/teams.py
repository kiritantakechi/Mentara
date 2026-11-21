"""The Mental AI's teams: role slots filled per country, and scripts.

A template lists role slots. Each slot is a predicate over a unit's role
tags and a score; per country and tier the best-scoring unit the country
can field fills it. Scripts are shared by every country.

How a team fights, from the Phobos v0.5-alpha2 and YR sources:

- Phobos attack lines give every member the leader's target each frame,
  so
  a mixed team's AA and medics would chase a building. Mixed teams stage
  with vanilla moves and push with vanilla `0,q`, which only hands the
  focus to members that have no target of their own, and pause in Phobos
  Area Guard (`10100`), where every member picks its own target.
- The leader is the member with the highest `LeadershipRating`. Each
  slot
  carries a rank, so the front line leads and picks the team's targets.
- Several Phobos actions are broken in alpha2 and are not used: 12000
  (never waits), 10102 (never regroups), 18000, the "random" list
  attacks, and 10104's charge test.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Final
lazy from collections.abc import Iterable

from mentara.mentalai.catalog import Catalog, Country, Factory, Kind, Role, Unit

__all__ = [
    "AIPlan",
    "Comparison",
    "Condition",
    "Script",
    "TaskForce",
    "TeamType",
    "Trigger",
    "plan_ai",
]

# A TaskForce holds at most six member types (TaskForceClass::Entries).
_TASK_FORCE_TYPES_MAX: Final[int] = 6
# A ScriptType holds at most fifty lines.
_SCRIPT_LINES_MAX: Final[int] = 50
# The engine keeps 24 characters of an ID.
_ID_LENGTH_MAX: Final[int] = 24
_COST_MIN: Final[int] = 1
_SCREEN_RANGE_MIN: Final[float] = 3.0
_ROSTER_TIERS: Final[tuple[int, ...]] = (1, 2, 3)
# Naming only: MO's two-letter country codes and labels
# (overlays/README).
_COUNTRY_NAMES: Final[dict[str, tuple[str, str]]] = {
    "unitedstates": ("US", "USA"),
    "europeans": ("EU", "Euro"),
    "pacific": ("PA", "Pacific"),
    "ussr": ("RU", "Russia"),
    "latin": ("LA", "Latin"),
    "chinese": ("CH", "China"),
    "psicorps": ("PC", "PsiCorps"),
    "scorpioncell": ("SC", "Scorpion"),
    "headquaters": ("HQ", "HQ"),
    "guild1": ("HA", "Haihead"),
    "guild2": ("CO", "Coronia"),
    "guild3": ("LB", "Last Bastion"),
}


class Condition(IntEnum):
    """An AI trigger's condition type (YR's `ConditionMet` table)."""

    HOUSE_OWNS = 1
    CHRONOSPHERE_CHARGED = 6


class Comparison(IntEnum):
    """An AI trigger comparator's operator."""

    LESS = 0
    AT_LEAST = 3


@dataclass(frozen=True, slots=True)
class TaskForce:
    """Members a team builds or recruits.

    Attributes:
        id: Section ID.
        name: Display name, its members ("4 HTNK, 2 FLAKT").
        members: Count and unit ID per member type, at most six types.
    """

    id: str
    name: str
    members: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class Script:
    """A ScriptType.

    Attributes:
        id: Section ID.
        name: Display name.
        lines: Action and argument per line.
    """

    id: str
    name: str
    lines: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class TeamType:
    """A TeamType: a task force running a script.

    Attributes:
        id: Section ID.
        name: Display name.
        task_force: Its TaskForce ID.
        script: Its ScriptType ID.
        max_teams: How many may exist at once per house (`Max`).
        priority: Recruiting priority; a higher one may take members.
        base_defense: Whether it is a base-defence team.
        recruitable: Whether its members may join other teams later.
    """

    id: str
    name: str
    task_force: str
    script: str
    max_teams: int
    priority: int
    base_defense: bool
    recruitable: bool


@dataclass(frozen=True, slots=True)
class Trigger:
    """An AITriggerType line.

    Attributes:
        id: Key in `[AITriggerTypes]`.
        name: Display name.
        team: Team1's ID.
        country: The country it serves.
        side: The country's side index.
        condition: Condition type.
        condition_object: The building the condition counts, or
            `<none>`. amount: The comparator's operand. comparison: The
            comparator's operator. weight: Starting weight; it learns
            between half and double. base_defense: Whether it raises a
            base-defence team.
    """

    id: str
    name: str
    team: str
    country: str
    side: int
    condition: Condition
    condition_object: str
    amount: int
    comparison: Comparison
    weight: int
    base_defense: bool


@dataclass(frozen=True, slots=True)
class AIPlan:
    """Everything the Mental AI adds.

    Attributes:
        task_forces: TaskForces in emission order.
        scripts: ScriptTypes in emission order.
        teams: TeamTypes in emission order.
        triggers: AITriggerTypes in emission order.
        leadership: Unit ID to `LeadershipRating`, for every member.
        unique: Members the AI must not clone (Phobos
            `ForbidParallelAIQueues`): Mental AI's cloning builds a copy
            per extra factory, and an airfield-bound craft's copy has no
            pad, so the AI abandons it.
    """

    task_forces: tuple[TaskForce, ...]
    scripts: tuple[Script, ...]
    teams: tuple[TeamType, ...]
    triggers: tuple[Trigger, ...]
    leadership: dict[str, int]
    unique: frozenset[str]


# --- Slots ----------------------------------------------------------

type _Score = Callable[[Unit, int], float]
type _Fits = Callable[[Unit], bool]


@dataclass(frozen=True, slots=True)
class _Slot:
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
    fallback: _Slot | None = None


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
    exponent = 0.0 if tier >= max(_ROSTER_TIERS) else 0.5
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


# A side with no main battle tank at a tier leads with its best armed
# combat vehicle instead, an armed carrier included.
_FRONT_FALLBACK: Final[_Slot] = _Slot(
    "front",
    lambda u: (
        _fighter(u)
        and u.kind is Kind.VEHICLE
        and u.has(Role.GUN)
        and bool(u.roles & {Role.ANTI_ARMOUR, Role.DUAL})
        and not u.roles & {Role.ARTILLERY, Role.HERO}
    ),
    _front_score,
    rank=12,
)
_FRONT: Final[_Slot] = _Slot(
    "front",
    lambda u: _fighter(u) and u.has(Role.MBT) and not u.has(Role.HERO),
    _front_score,
    rank=12,
    fallback=_FRONT_FALLBACK,
)
_SCREEN: Final[_Slot] = _Slot(
    "screen",
    _screen_fits,
    lambda u, _t: u.firepower.infantry / _cost(u) * _vitality(u),
    rank=8,
)
_AA: Final[_Slot] = _Slot(
    "aa",
    lambda u: (
        _fighter(u) and u.has(Role.AA) and not u.roles & {Role.HERO, Role.TRANSPORT}
    ),
    _aa_score,
    rank=6,
)
_ARTILLERY: Final[_Slot] = _Slot(
    "artillery",
    lambda u: _fighter(u) and u.has(Role.ARTILLERY) and not u.has(Role.HERO),
    _artillery_score,
    rank=10,
)
_SIEGE: Final[_Slot] = _Slot(
    "siege",
    lambda u: _fighter(u) and u.has(Role.SIEGE) and not u.has(Role.HERO),
    _siege_score,
    rank=10,
)
_SUPPORT: Final[_Slot] = _Slot(
    "support",
    lambda u: _fighter(u) and bool(u.roles & {Role.HEALER, Role.REPAIRER}),
    lambda u, _t: 1 / _cost(u),
    rank=4,
)
_DETECTOR: Final[_Slot] = _Slot(
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
_HERO: Final[_Slot] = _Slot(
    "hero",
    lambda u: u.kind is Kind.INFANTRY and _fighter(u) and u.has(Role.HERO, Role.GUN),
    lambda u, _t: u.firepower.infantry + u.firepower.vehicle + u.firepower.building,
    rank=9,
)
_RAIDER: Final[_Slot] = _Slot(
    "raider",
    lambda u: (
        _fighter(u)
        and u.kind is Kind.VEHICLE
        and u.has(Role.GUN)
        and bool(u.roles & {Role.ANTI_ARMOUR, Role.DUAL})
        and not u.roles & {Role.ARTILLERY, Role.HERO}
    ),
    lambda u, _t: u.firepower.vehicle * u.speed / _cost(u),
    rank=8,
)
_AIR: Final[_Slot] = _Slot(
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
_NAVAL_FRONT: Final[_Slot] = _Slot(
    "naval front",
    lambda u: (
        u.has(Role.NAVAL, Role.GUN) and not u.roles & (_NON_COMBAT | {Role.TRANSPORT})
    ),
    lambda u, _t: (
        u.strength * max(u.firepower.vehicle, u.firepower.building) / _cost(u) ** 0.5
    ),
    rank=12,
)
_NAVAL_AA: Final[_Slot] = _Slot(
    "naval aa",
    lambda u: u.has(Role.NAVAL, Role.AA) and not u.roles & _NON_COMBAT,
    _aa_score,
    rank=6,
)
_NAVAL_ARTILLERY: Final[_Slot] = _Slot(
    "naval artillery",
    lambda u: u.has(Role.NAVAL, Role.ARTILLERY) and not u.roles & _NON_COMBAT,
    _siege_score,
    rank=10,
)
_ENGINEER: Final[_Slot] = _Slot(
    "engineer",
    lambda u: u.kind is Kind.INFANTRY and u.has(Role.ENGINEER),
    lambda u, _t: 1 / _cost(u),
    rank=1,
)
_SPY: Final[_Slot] = _Slot(
    "spy",
    lambda u: u.kind is Kind.INFANTRY and u.has(Role.INFILTRATOR),
    lambda u, _t: 1 / _cost(u),
    rank=1,
)

# --- Scripts ---------------------------------------------------------

type _Lines = tuple[tuple[int, int], ...]

# Vanilla actions.
_ATTACK: Final[int] = 0
_JUMP: Final[int] = 6  # 1-based line number
_DEPLOY: Final[int] = 9
_SUCCESS: Final[int] = 49
_GATHER_AT_ENEMY: Final[int] = 53
_REGROUP_AT_BASE: Final[int] = 54
_CHRONOSHIFT_TO_THREAT: Final[int] = 57
# Ares: fire the team-cast superweapon of a `SW.Group` at the team.
_TEAM_CAST: Final[int] = 55
# Vanilla quarries.
_ANYTHING: Final[int] = 1
_STRUCTURES: Final[int] = 2
_INFANTRY: Final[int] = 4
_VEHICLES: Final[int] = 5
_FACTORIES: Final[int] = 6
_DEFENSES: Final[int] = 7
_OCCUPIED: Final[int] = 10
# Phobos actions and target types.
_PHOBOS_ATTACK_CLOSER: Final[int] = 10000
_PHOBOS_ATTACK_CLOSER_ONCE: Final[int] = 10001
_PHOBOS_AREA_GUARD: Final[int] = 10100
_PHOBOS_TIMEOUT: Final[int] = 16001
_PHOBOS_TIMEOUT_STOP: Final[int] = 16002
_PHOBOS_SKIP_CHANCE: Final[int] = 16003
_TARGET_FACTORIES: Final[int] = 6
_TARGET_DEFENSES: Final[int] = 7
_TARGET_POWER: Final[int] = 9
_TARGET_TECH: Final[int] = 11
_TARGET_ORE_MINERS: Final[int] = 3
_TARGET_ECONOMY: Final[int] = 18
_TARGET_RADAR: Final[int] = 22
_TARGET_NAVAL_UNITS: Final[int] = 31
# Seconds.
_STAGE_TIMEOUT: Final[int] = 90
_STAGE_FIGHT: Final[int] = 15
_PUSH_PAUSE: Final[int] = 8
_ARRIVAL_FIGHT: Final[int] = 8
_CAST_TIMEOUT: Final[int] = 10
_DEFENSE_WATCH: Final[int] = 60
_CAPTURE_TIMEOUT: Final[int] = 120
_SPY_SKIP_PERCENT: Final[int] = 50
_AGENT_RETRY: Final[int] = 30


def _casts(groups: tuple[int, ...]) -> _Lines:
    """Cast each team-cast superweapon group at the team.

    Ares's action 55 waits while a superweapon of the group is almost
    charged (`AIMinorSuperReadyPercent`), so each cast runs under a
    timeout; a group the house lacks or has far from charged is skipped.
    """
    return tuple(
        line
        for group in groups
        for line in (
            (_PHOBOS_TIMEOUT, _CAST_TIMEOUT),
            (_TEAM_CAST, group),
            (_PHOBOS_TIMEOUT_STOP, 0),
        )
    )


def _staged(casts: tuple[int, ...], *push: tuple[int, int]) -> _Lines:
    """Conscript, stage near the enemy base, fight there, cast, push."""
    return (
        (_REGROUP_AT_BASE, 0),
        (_PHOBOS_TIMEOUT, _STAGE_TIMEOUT),
        (_GATHER_AT_ENEMY, 0),
        (_PHOBOS_TIMEOUT_STOP, 0),
        (_PHOBOS_AREA_GUARD, _STAGE_FIGHT),
        *_casts(casts),
        *push,
        (_SUCCESS, 0),
        (_ATTACK, _ANYTHING),
    )


@dataclass(frozen=True, slots=True)
class _ScriptPlan:
    """A script whose lines may depend on the country.

    Attributes:
        code: Its ID number.
        name: Display name.
        lines: The lines for a country.
    """

    code: int
    name: str
    lines: Callable[[Country], _Lines]

    def build(self, country: Country, country_code: str) -> Script:
        """The script for a country.

        Args:
            country: The country.
            country_code: Its two-letter code.

        Returns:
            A country's own script when it casts superweapons, else the
            shared one.
        """
        lines = self.lines(country)
        own = any(action == _TEAM_CAST for action, _ in lines)
        suffix = country_code if own else ""
        label = f" ({country_code})" if own else ""
        return Script(f"MNTSC{self.code}{suffix}-G", self.name + label, lines)


def _fixed(lines: _Lines) -> Callable[[Country], _Lines]:
    return lambda _country: lines


_LINE_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    100,
    "Mental Staged Line",
    lambda c: _staged(
        c.front_casts,
        (_ATTACK, _DEFENSES),
        (_PHOBOS_AREA_GUARD, _PUSH_PAUSE),
        (_ATTACK, _STRUCTURES),
    ),
)
_SIEGE_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    200,
    "Mental Siege",
    lambda c: _staged(c.front_casts, (_ATTACK, _DEFENSES), (_ATTACK, _STRUCTURES)),
)
_RAID_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    300,
    "Mental Economy Raid",
    _fixed(
        (
            (_REGROUP_AT_BASE, 0),
            (_PHOBOS_ATTACK_CLOSER, _TARGET_ORE_MINERS),
            (_PHOBOS_ATTACK_CLOSER, _TARGET_ECONOMY),
            (_SUCCESS, 0),
            (_ATTACK, _ANYTHING),
        )
    ),
)


def _air_script(code: int, name: str, *quarries: int) -> Script:
    # Vanilla quarries, as MO's own air teams use: a Phobos attack line
    # found no target for Comanches in a probe game and the team hovered
    # in place. Vanilla `0,q` repeats until the class is gone, and the
    # engine sends the craft to rearm and back on its own.
    return Script(
        f"MNTSC{code}-G",
        f"Mental Air Strike {name}",
        (
            *((_ATTACK, quarry) for quarry in quarries),
            (_SUCCESS, 0),
            (_ATTACK, _ANYTHING),
        ),
    )


_AIR_SCRIPTS: Final[dict[str, Script]] = {
    "vehicle": _air_script(401, "vs Vehicles", _VEHICLES, _DEFENSES),
    "infantry": _air_script(402, "vs Infantry", _INFANTRY, _OCCUPIED),
    "building": _air_script(403, "vs Defenses", _DEFENSES, _STRUCTURES),
}
# The watch casts the superweapons that belong at home (harvester
# deliveries) each time round.
_DEFENSE_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    500,
    "Mental Base Watch",
    lambda c: (
        (_REGROUP_AT_BASE, 0),
        *_casts(c.base_casts),
        (_PHOBOS_AREA_GUARD, _DEFENSE_WATCH),
        (_JUMP, 2),
    ),
)
# An agent with no target waits and looks again. Ending instead frees
# the trigger at once, so every roll would raise the same idle team
# again (a probe game created one 112 times in eight minutes).
_ENGINEER_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    600,
    "Mental Capture Tech",
    _fixed(
        (
            (_PHOBOS_TIMEOUT, _CAPTURE_TIMEOUT),
            (_PHOBOS_ATTACK_CLOSER_ONCE, _TARGET_TECH),
            (_PHOBOS_TIMEOUT_STOP, 0),
            (_PHOBOS_AREA_GUARD, _AGENT_RETRY),
            (_JUMP, 1),
        )
    ),
)
_SPY_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    700,
    "Mental Infiltrate",
    _fixed(
        (
            (_PHOBOS_SKIP_CHANCE, _SPY_SKIP_PERCENT),
            (_PHOBOS_ATTACK_CLOSER_ONCE, _TARGET_POWER),
            (_PHOBOS_SKIP_CHANCE, _SPY_SKIP_PERCENT),
            (_PHOBOS_ATTACK_CLOSER_ONCE, _TARGET_RADAR),
            (_PHOBOS_ATTACK_CLOSER_ONCE, _TARGET_FACTORIES),
            (_PHOBOS_AREA_GUARD, _AGENT_RETRY),
            (_JUMP, 1),
        )
    ),
)
_MCV_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    800,
    "Mental Redeploy MCV",
    _fixed(((_DEPLOY, 0), (_SUCCESS, 0))),
)
# Vanilla 57 jumps next to the leader's greatest threat of a quarry.
# It waits while the Chronosphere is almost charged and fires the
# sphere the phobos layer pins (`AIChronoSphereSW`); MO's own assault
# used action 56, whose lookup took a sphere the AI never owns.
_CHRONO_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    810,
    "Mental Chrono Assault",
    lambda c: (
        (_REGROUP_AT_BASE, 0),
        (_CHRONOSHIFT_TO_THREAT, _FACTORIES),
        (_PHOBOS_AREA_GUARD, _ARRIVAL_FIGHT),
        *_casts(c.front_casts),
        (_ATTACK, _FACTORIES),
        (_ATTACK, _STRUCTURES),
        (_SUCCESS, 0),
        (_ATTACK, _ANYTHING),
    ),
)
_NAVAL_SCRIPT: Final[_ScriptPlan] = _ScriptPlan(
    900,
    "Mental Naval Line",
    _fixed(
        _staged(
            (),
            (_PHOBOS_ATTACK_CLOSER, _TARGET_NAVAL_UNITS),
            (_PHOBOS_ATTACK_CLOSER, _TARGET_DEFENSES),
            (_ATTACK, _STRUCTURES),
        )
    ),
)

# --- Families --------------------------------------------------------


def _has_chronosphere(country: Country) -> bool:
    return country.chronosphere


@dataclass(frozen=True, slots=True)
class _Family:
    """A kind of team, built once per country and tier.

    Attributes:
        code: First digit of its three-digit ID number.
        name: Display name.
        slots: Role slots and their counts, in leading order.
        script: Its script, or None to pick an air strike per team.
        tiers: The tiers it is built for.
        weight: Trigger weight.
        max_teams: TeamType `Max`.
        base_defense: Whether its teams defend the base.
        gate_factory: A factory the trigger waits for, or None for the
            tier gate.
        required: Slot names that must be filled for the team to exist.
        docked: Whether airfield-bound members share one airfield's
            pads across the tiers, one team per tier: an aircraft with
            no free pad is never built, and the AI abandons it.
        condition: The trigger's condition; anything but "house owns"
            replaces the tier gate.
        vehicles_only: Whether only vehicles may fill the slots.
        needs: What the country must have for the family to exist.
    """

    code: int
    name: str
    slots: tuple[tuple[_Slot, int], ...]
    script: _ScriptPlan | None
    tiers: tuple[int, ...]
    weight: int
    max_teams: int
    base_defense: bool = False
    gate_factory: Factory | None = None
    required: tuple[str, ...] = ()
    docked: bool = False
    condition: Condition = Condition.HOUSE_OWNS
    vehicles_only: bool = False
    needs: Callable[[Country], bool] | None = None


_FAMILIES: Final[tuple[_Family, ...]] = (
    _Family(
        1,
        "Line",
        ((_FRONT, 4), (_SCREEN, 3), (_AA, 1), (_DETECTOR, 1)),
        _LINE_SCRIPT,
        (1,),
        weight=100,
        max_teams=4,
        required=("front",),
    ),
    _Family(
        1,
        "Line",
        (
            (_FRONT, 4),
            (_ARTILLERY, 2),
            (_SCREEN, 2),
            (_AA, 2),
            (_SUPPORT, 1),
            (_DETECTOR, 1),
        ),
        _LINE_SCRIPT,
        (2,),
        weight=120,
        max_teams=4,
        required=("front",),
    ),
    _Family(
        1,
        "Line",
        (
            (_FRONT, 4),
            (_ARTILLERY, 2),
            (_HERO, 1),
            (_SCREEN, 2),
            (_AA, 2),
            (_SUPPORT, 1),
        ),
        _LINE_SCRIPT,
        (3,),
        weight=150,
        max_teams=4,
        required=("front",),
    ),
    _Family(
        2,
        "Siege",
        ((_SIEGE, 3), (_FRONT, 2), (_SCREEN, 2), (_AA, 1)),
        _SIEGE_SCRIPT,
        (2, 3),
        weight=70,
        max_teams=2,
        required=("siege",),
    ),
    _Family(
        3,
        "Raid",
        ((_RAIDER, 4),),
        _RAID_SCRIPT,
        (1, 2),
        weight=40,
        max_teams=2,
        required=("raider",),
    ),
    _Family(
        4,
        "Air Strike",
        ((_AIR, 4),),
        None,
        (2, 3),
        weight=50,
        max_teams=3,
        required=("air",),
        docked=True,
    ),
    _Family(
        5,
        "Base Watch",
        ((_FRONT, 2), (_SCREEN, 2), (_AA, 2)),
        _DEFENSE_SCRIPT,
        (1, 2, 3),
        weight=60,
        max_teams=2,
        base_defense=True,
    ),
    _Family(
        6,
        "Engineers",
        ((_ENGINEER, 2),),
        _ENGINEER_SCRIPT,
        (1,),
        weight=20,
        max_teams=1,
        gate_factory=Factory.BARRACKS,
        required=("engineer",),
    ),
    _Family(
        7,
        "Spy",
        ((_SPY, 1),),
        _SPY_SCRIPT,
        (2, 3),
        weight=10,
        max_teams=2,
        required=("spy",),
    ),
    # The sphere moves only what stands in its 3x3 cells, and kills the
    # infantry it moves, so the assault is a few vehicles.
    _Family(
        8,
        "Chrono Assault",
        ((_FRONT, 4), (_ARTILLERY, 2), (_AA, 1)),
        _CHRONO_SCRIPT,
        (3,),
        weight=150,
        max_teams=1,
        required=("front",),
        condition=Condition.CHRONOSPHERE_CHARGED,
        vehicles_only=True,
        needs=_has_chronosphere,
    ),
    _Family(
        9,
        "Navy",
        ((_NAVAL_FRONT, 3), (_NAVAL_ARTILLERY, 2), (_NAVAL_AA, 1)),
        _NAVAL_SCRIPT,
        (1, 3),
        weight=80,
        max_teams=3,
        gate_factory=Factory.SHIPYARD,
        required=("naval front",),
    ),
)
_MCV_CODE: Final[int] = 800
_MCV_WEIGHT: Final[int] = 500
_MCV_PRIORITY: Final[int] = 10
_PRIORITY: Final[int] = 5
_FALLBACK_RANK: Final[int] = 1
_NO_OBJECT: Final[str] = "<none>"


@dataclass(frozen=True, slots=True)
class _Gate:
    condition: Condition
    building: str
    amount: int
    comparison: Comparison


def plan_ai(catalog: Catalog) -> AIPlan:
    """Build every TaskForce, TeamType and trigger of the Mental AI.

    Args:
        catalog: Units and countries from the rules.

    Returns:
        The plan, in a stable order.
    """
    builder = _Builder(catalog)
    for country in catalog.countries:
        for family in _FAMILIES:
            if family.needs is not None and not family.needs(country):
                continue
            for tier in family.tiers:
                builder.add_family(country, family, tier)
        builder.add_mcv(country)
    return builder.plan()


class _Builder:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._task_forces: list[TaskForce] = []
        self._teams: list[TeamType] = []
        self._triggers: list[Trigger] = []
        self._scripts: dict[str, Script] = {}
        self._leadership: dict[str, int] = {}
        self._unique: set[str] = set()

    def plan(self) -> AIPlan:
        return AIPlan(
            task_forces=tuple(self._task_forces),
            scripts=tuple(sorted(self._scripts.values(), key=lambda s: s.id)),
            teams=tuple(self._teams),
            triggers=tuple(self._triggers),
            leadership=dict(sorted(self._leadership.items())),
            unique=frozenset(self._unique),
        )

    def add_family(self, country: Country, family: _Family, tier: int) -> None:
        fielded = self._catalog.fielded(country, tier)
        if family.vehicles_only:
            fielded = tuple(u for u in fielded if u.kind is Kind.VEHICLE)
        filled = _fill(family, fielded, tier)
        gate = self._gate(country, family, tier)
        if filled is None or gate is None:
            return
        members, ranks = filled
        max_teams = family.max_teams
        if family.docked and self._is_docked(members):
            # Every tier's team may be up at once, and the AI may own
            # one airfield: together they must fit its pads.
            share = country.docks // len(family.tiers)
            if share <= 0:
                return
            members = tuple((min(n, share), unit) for n, unit in members)
            max_teams = 1
            self._unique.update(unit for _, unit in members)
        if family.script is None:
            script = _air_script_for(members, self._catalog)
        else:
            script = family.script.build(country, _country_code(country))
        self._add(
            country,
            number=family.code * 100 + tier,
            label=f"{family.name} T{tier}",
            members=members,
            script=script,
            gate=gate,
            weight=family.weight,
            max_teams=max_teams,
            base_defense=family.base_defense,
        )
        for unit_id, rank in ranks.items():
            self._leadership[unit_id] = max(self._leadership.get(unit_id, 0), rank)

    def _is_docked(self, members: tuple[tuple[int, str], ...]) -> bool:
        return any(
            self._catalog.units[unit.lower()].has(Role.DOCKED) for _, unit in members
        )

    def add_mcv(self, country: Country) -> None:
        if not country.mcv or not country.construction_yard:
            return
        self._add(
            country,
            number=_MCV_CODE,
            label="Redeploy MCV",
            members=((1, country.mcv),),
            script=_MCV_SCRIPT.build(country, _country_code(country)),
            gate=_Gate(
                Condition.HOUSE_OWNS, country.construction_yard, 1, Comparison.LESS
            ),
            weight=_MCV_WEIGHT,
            max_teams=1,
            base_defense=False,
            priority=_MCV_PRIORITY,
        )
        self._leadership.setdefault(country.mcv, _FALLBACK_RANK)

    def _gate(self, country: Country, family: _Family, tier: int) -> _Gate | None:
        """What a family's trigger waits for.

        The AI skips unit prerequisites when it fills a team, so the
        trigger holds each tier back: tier 1 runs until the country owns
        its tier-2 building, higher tiers once it owns theirs. A family
        with a condition of its own (a charged Chronosphere) waits for
        that instead.
        """
        if family.condition is not Condition.HOUSE_OWNS:
            return _Gate(family.condition, _NO_OBJECT, 0, Comparison.LESS)
        owns = Condition.HOUSE_OWNS
        if family.gate_factory is not None and tier == min(family.tiers):
            factory = country.factories.get(family.gate_factory)
            if factory is None:
                return None
            return _Gate(owns, factory, 1, Comparison.AT_LEAST)
        if tier == 1:
            upper = country.gates.get(2)
            return None if upper is None else _Gate(owns, upper, 1, Comparison.LESS)
        building = country.gates.get(tier)
        if building is None:
            return None
        return _Gate(owns, building, 1, Comparison.AT_LEAST)

    def _add(  # noqa: PLR0913 - one call site per kind of team
        self,
        country: Country,
        *,
        number: int,
        label: str,
        members: tuple[tuple[int, str], ...],
        script: Script,
        gate: _Gate,
        weight: int,
        max_teams: int,
        base_defense: bool,
        priority: int = _PRIORITY,
    ) -> None:
        suffix = f"{number:03d}{_country_code(country)}-G"
        task_force = TaskForce(
            id=_checked_id(f"MNTTF{suffix}"),
            name=", ".join(f"{count} {unit}" for count, unit in members),
            members=members,
        )
        team = TeamType(
            id=_checked_id(f"MNTTT{suffix}"),
            name=f"{_country_label(country)} - Mental {label}",
            task_force=task_force.id,
            script=script.id,
            max_teams=max_teams,
            priority=priority,
            base_defense=base_defense,
            recruitable=not base_defense,
        )
        trigger = Trigger(
            id=_checked_id(f"MNTTR{suffix}"),
            name=team.name,
            team=team.id,
            country=country.id,
            side=country.side,
            condition=gate.condition,
            condition_object=gate.building,
            amount=gate.amount,
            comparison=gate.comparison,
            weight=weight,
            base_defense=base_defense,
        )
        if len(script.lines) > _SCRIPT_LINES_MAX:
            detail = f"script {script.id} has more than {_SCRIPT_LINES_MAX} lines"
            raise ValueError(detail)
        self._scripts[_checked_id(script.id)] = script
        self._task_forces.append(task_force)
        self._teams.append(team)
        self._triggers.append(trigger)


def _country_code(country: Country) -> str:
    return _COUNTRY_NAMES.get(country.id.lower(), (country.id[:2].upper(), ""))[0]


def _country_label(country: Country) -> str:
    return _COUNTRY_NAMES.get(country.id.lower(), ("", country.id))[1]


def _fill(
    family: _Family,
    fielded: Iterable[Unit],
    tier: int,
) -> tuple[tuple[tuple[int, str], ...], dict[str, int]] | None:
    """Fill a family's slots from the units a country fields.

    Each slot takes its best-scoring unit; a unit already chosen for an
    earlier slot adds to that member instead of a new type. A detector
    slot is skipped when a chosen unit already detects.

    Returns:
        The members and each member's leadership rank, or None when a
        required slot stays empty.
    """
    units = tuple(fielded)
    counts: dict[str, int] = {}
    ranks: dict[str, int] = {}
    chosen: dict[str, Unit] = {}
    for slot, count in family.slots:
        if slot is _DETECTOR and any(u.has(Role.DETECTOR) for u in chosen.values()):
            continue
        candidates = [u for u in units if slot.fits(u)]
        if not candidates and slot.fallback is not None:
            candidates = [u for u in units if slot.fallback.fits(u)]
        if not candidates:
            if slot.name in family.required:
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


def _air_script_for(members: tuple[tuple[int, str], ...], catalog: Catalog) -> Script:
    """The air strike suiting the strike craft's best damage class."""
    unit = catalog.units[members[0][1].lower()]
    fire = unit.firepower
    best = max(
        ("vehicle", fire.vehicle),
        ("infantry", fire.infantry),
        ("building", fire.building),
        key=lambda pair: pair[1],
    )
    return _AIR_SCRIPTS[best[0]]


def _checked_id(identifier: str) -> str:
    if len(identifier) > _ID_LENGTH_MAX:
        detail = f"AI ID {identifier!r} is longer than {_ID_LENGTH_MAX} characters"
        raise ValueError(detail)
    return identifier
