"""The Mental AI as data, from the planner to the emitter.

The planner's types (`Squad`, `Call`) speak of units, scripts and
numbers; the emitter's (`TaskForce`, `ScriptType`, `TeamType`,
`Trigger`) are the INI objects, each with its ID.
"""

from dataclasses import KW_ONLY, dataclass, replace
from enum import IntEnum
from typing import Final
lazy from collections.abc import Mapping

from mentara.mentalai.catalog import Role
lazy from mentara.mentalai.catalog import Unit
lazy from mentara.mentalai.scripts import Lines, Script

__all__ = [
    "AIPlan",
    "Call",
    "Comparison",
    "Condition",
    "Conduct",
    "Crew",
    "Gate",
    "Member",
    "MindControl",
    "ScriptType",
    "Squad",
    "TaskForce",
    "TeamType",
    "Trigger",
]

# The engine counts a member slow at this speed or below.
_SLOW_SPEED: Final[float] = 5.0


class Condition(IntEnum):
    """An AI trigger's condition type (YR's `ConditionMet` table)."""

    ALWAYS = -1
    ENEMY_OWNS = 0
    HOUSE_OWNS = 1
    # The house's chosen enemy has under 100 power to spare.
    ENEMY_POWER_LOW = 2
    # The house's chosen enemy makes less power than it drains.
    ENEMY_POWER_SHORT = 3
    # The chosen enemy's credits, against the comparator.
    ENEMY_CREDITS = 4
    IRON_CURTAIN_CHARGED = 5
    CHRONOSPHERE_CHARGED = 6
    # A neutral house owns the object: tech nobody has taken yet.
    NEUTRAL_OWNS = 7


class Comparison(IntEnum):
    """An AI trigger comparator's operator."""

    LESS = 0
    AT_LEAST = 3


class MindControl(IntEnum):
    """What a team does with units its members mind-control.

    `MindControlDecision`, in YR's order (as ModEnc documents it).
    """

    DONT_CARE = 0
    JOIN_TEAM = 1
    GRIND = 2
    BIO_REACTOR = 3
    HUNT = 4
    NOTHING = 5


@dataclass(frozen=True, slots=True)
class Conduct:
    """How a team behaves: the TeamType keys the engine reads for it.

    `Loadable`, `Full`, `Whiner`, `LooseRecruit` and `Prebuild` have no
    effect on teams the AI's triggers raise (gamemd: AI teams are
    created empty and filled by production and recruiting), so they are
    not choices here. Nor is `Priority` as a ranking: a team takes
    recruitable members out of any team of lower priority (gamemd
    0x6EA7C7), marching and fighting ones included, since only a few
    missions such as Hunt bar recruiting. With priorities by kind,
    lines stripped raids as fast as they were built and no raid ever
    set out, so teams have one priority and keep their members until
    they end; then they return to the pool (Phobos
    `SetRecruitableOnLiberate`). The one exception is `urgent`.

    Attributes:
        aggressive: Members look for targets while moving and fight on
            (attack-move for vanilla moves).
        avoid_threats: Pathfinding routes round known threats.
        recruiter: The team takes idle units of its types from anywhere,
            so survivors fill it before the factories do.
        enemy_only: Phobos lines target only the house's chosen enemy.
        suicide: The team ignores damage and members never retaliate.
        annoyance: Hit on the move by something other than its target,
            the team stops and regroups.
        reinforce: At a third of its strength the team stops, regroups
            and recruits replacements.
        guard_slower: Slow members count double in the team's centre,
            so it gathers where they are.
        base_defense: A base-defence team (capped apart).
        transports_return: Transports released by vanilla 8 drive back
            to where vanilla 14 loaded them.
        urgent: The team outranks the others and fills at once with
            members taken out of them. An empty team takes the unit
            nearest the map's first cell, wherever the house stands,
            and then the ones nearest that (gamemd 0x6EAA90): in a
            probe game it emptied a team at the enemy's gate and left
            the same units at home. So it is for aircraft of one type
            alone, which are retasked from wherever they fly and whose
            pads hold no second squadron.
        mind_control: What to do with units members mind-control.
    """

    aggressive: bool = True
    avoid_threats: bool = False
    recruiter: bool = False
    enemy_only: bool = False
    suicide: bool = False
    annoyance: bool = False
    reinforce: bool = False
    guard_slower: bool = False
    base_defense: bool = False
    transports_return: bool = False
    urgent: bool = False
    mind_control: MindControl = MindControl.DONT_CARE


@dataclass(frozen=True, slots=True)
class Gate:
    """What a trigger waits for.

    A trigger has one condition: a gate on an own building cannot also
    wait on the enemy, nor the other way round.

    Attributes:
        condition: The condition type.
        subject: The building or unit it counts, if it counts one.
        amount: The comparator's operand.
        comparison: The comparator's operator.
    """

    condition: Condition
    subject: str | None = None
    amount: int = 0
    comparison: Comparison = Comparison.LESS

    @classmethod
    def house_owns(cls, building: str) -> Gate:
        """Once the house owns a building.

        Args:
            building: The building's ID.

        Returns:
            The gate.
        """
        return cls(Condition.HOUSE_OWNS, building, 1, Comparison.AT_LEAST)

    @classmethod
    def house_lacks(cls, building: str) -> Gate:
        """While the house owns none of a building.

        Args:
            building: The building's ID.

        Returns:
            The gate.
        """
        return cls(Condition.HOUSE_OWNS, building, 1, Comparison.LESS)

    @classmethod
    def enemy_owns(cls, subject: str, amount: int = 1) -> Gate:
        """Once the house's chosen enemy owns enough of something.

        Args:
            subject: A building's or a unit's ID.
            amount: How many it takes.

        Returns:
            The gate.
        """
        return cls(Condition.ENEMY_OWNS, subject, amount, Comparison.AT_LEAST)

    @classmethod
    def neutral_owns(cls, building: str) -> Gate:
        """While a neutral house owns a building.

        Args:
            building: The building's ID.

        Returns:
            The gate.
        """
        return cls(Condition.NEUTRAL_OWNS, building, 1, Comparison.AT_LEAST)

    @classmethod
    def enemy_credits_under(cls, limit: int) -> Gate:
        """While the chosen enemy has fewer credits than a limit.

        Args:
            limit: The credits it must stay under.

        Returns:
            The gate.
        """
        return cls(Condition.ENEMY_CREDITS, None, limit, Comparison.LESS)


@dataclass(frozen=True, slots=True)
class Member:
    """A unit type in a squad.

    Attributes:
        count: How many of it.
        unit: The unit.
        rank: The `LeadershipRating` its place gives it: a team's
            highest-rated member leads it and picks its targets.
    """

    count: int
    unit: Unit
    rank: int


type Crew = tuple[Member, ...]


@dataclass(frozen=True, slots=True)
class Squad:
    """A TaskForce and the TeamType that runs it, for one country.

    Attributes:
        number: Its four-digit ID number (series, then variant).
        label: What it is ("Line T2").
        members: Its member types, the leader's first.
        script: What it does.
        doctrine: How its kind of squad behaves.
        max_teams: How many may exist at once (`Max`).
    """

    number: int
    label: str
    members: Crew
    script: Script
    doctrine: Conduct
    max_teams: int = 2

    @property
    def conduct(self) -> Conduct:
        """The doctrine as these members carry it out.

        Only a squad with a mind controller decides what becomes of
        the units it takes, and slow members among fast ones draw the
        team's gathering point to them.
        """
        units = [member.unit for member in self.members]
        controls = any(unit.has(Role.MIND_CONTROL) for unit in units)
        slow = [unit.speed <= _SLOW_SPEED for unit in units]
        return replace(
            self.doctrine,
            mind_control=(
                self.doctrine.mind_control if controls else MindControl.DONT_CARE
            ),
            guard_slower=any(slow) and not all(slow),
        )

    @property
    def docked(self) -> frozenset[str]:
        """Its airfield-bound members: the AI must not clone them.

        Mental AI's cloning builds a copy per extra factory, and a
        copy of such a craft has no pad, so the AI abandons it.
        """
        return frozenset(
            member.unit.id for member in self.members if member.unit.has(Role.DOCKED)
        )


@dataclass(frozen=True, slots=True)
class Call:
    """An AI trigger that raises a squad, and maybe a second one.

    Attributes:
        number: Its four-digit ID number.
        label: What it is.
        squad: Team1's squad number.
        gate: What it waits for.
        weight: Its starting weight. It learns between half and double
            when its squad's script reports how the team fared, and
            stays put when it does not.
        support: Team2's squad number, launched in the same frame. A
            call with a second team leads with a TeamType of its own,
            so it learns apart from its squad's other calls.
    """

    number: int
    label: str
    _: KW_ONLY
    squad: int
    gate: Gate
    weight: int
    support: int | None = None


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
class ScriptType:
    """A ScriptType: what a team does, line by line.

    Attributes:
        id: Section ID.
        name: Display name.
        lines: Action and argument per line, at most fifty.
    """

    id: str
    name: str
    lines: Lines


@dataclass(frozen=True, slots=True)
class TeamType:
    """A TeamType: a task force running a script.

    Attributes:
        id: Section ID.
        name: Display name.
        task_force: Its TaskForce ID.
        script: Its ScriptType ID.
        max_teams: How many may exist at once per house (`Max`).
        conduct: How the team behaves.
    """

    id: str
    name: str
    task_force: str
    script: str
    max_teams: int
    conduct: Conduct


@dataclass(frozen=True, slots=True)
class Trigger:
    """An AITriggerType line.

    Attributes:
        id: Key in `[AITriggerTypes]`.
        name: Display name.
        team: Team1's ID.
        support: Team2's ID, if it raises a second team.
        country: The country it serves.
        side: The country's side index.
        gate: What it waits for.
        weight: Starting weight.
        base_defense: Whether it raises a base-defence team.
        steady: Whether the weight stays put: the team's script does
            not report how it fared.
    """

    id: str
    name: str
    team: str
    support: str | None
    country: str
    side: int
    gate: Gate
    weight: int
    base_defense: bool
    steady: bool


@dataclass(frozen=True, slots=True)
class AIPlan:
    """Everything the Mental AI adds.

    Attributes:
        task_forces: TaskForces in emission order.
        scripts: ScriptTypes in emission order.
        teams: TeamTypes in emission order.
        triggers: AITriggerTypes in emission order.
        leadership: Unit ID to `LeadershipRating`, for every member.
        docked: Airfield-bound members, which the AI must not clone
            (Phobos `ForbidParallelAIQueues`).
        target_lists: Phobos `[AITargetTypes]`, in index order.
        stand_offs: Weapon type to the distance, in cells, an AI firer
            keeps from its target while the weapon reloads (Phobos
            `KeepRange`).
    """

    task_forces: tuple[TaskForce, ...]
    scripts: tuple[ScriptType, ...]
    teams: tuple[TeamType, ...]
    triggers: tuple[Trigger, ...]
    leadership: Mapping[str, int]
    docked: frozenset[str]
    target_lists: tuple[tuple[str, ...], ...]
    stand_offs: Mapping[str, float]
