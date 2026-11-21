"""The Mental AI as data, from the planner to the emitter."""

from dataclasses import dataclass, field
from enum import IntEnum
lazy from collections.abc import Mapping

lazy from mentara.mentalai.scripts import Script

__all__ = [
    "AIPlan",
    "Call",
    "Comparison",
    "Condition",
    "Conduct",
    "Gate",
    "MindControl",
    "Squad",
    "TaskForce",
    "TeamType",
    "Trigger",
]


class Condition(IntEnum):
    """An AI trigger's condition type (YR's `ConditionMet` table)."""

    ALWAYS = -1
    ENEMY_OWNS = 0
    HOUSE_OWNS = 1
    # The house's chosen enemy makes less power than it drains.
    ENEMY_POWER_SHORT = 3
    # The chosen enemy's credits, against the comparator.
    ENEMY_CREDITS = 4
    IRON_CURTAIN_CHARGED = 5
    CHRONOSPHERE_CHARGED = 6


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
    not choices here.

    Attributes:
        priority: A team of higher priority may take members from one
            of lower priority.
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
        recruitable: Members may join other teams once theirs ends.
        transports_return: Transports released by vanilla 8 drive back
            to where vanilla 14 loaded them.
        mind_control: What to do with units members mind-control.
    """

    priority: int = 5
    aggressive: bool = True
    avoid_threats: bool = False
    recruiter: bool = False
    enemy_only: bool = False
    suicide: bool = False
    annoyance: bool = False
    reinforce: bool = False
    guard_slower: bool = False
    base_defense: bool = False
    recruitable: bool = True
    transports_return: bool = False
    mind_control: MindControl = MindControl.DONT_CARE


@dataclass(frozen=True, slots=True)
class Gate:
    """What a trigger waits for.

    Attributes:
        condition: The condition type.
        building: The object it counts, or `<none>`.
        amount: The comparator's operand.
        comparison: The comparator's operator.
    """

    condition: Condition
    building: str = "<none>"
    amount: int = 0
    comparison: Comparison = Comparison.LESS


@dataclass(frozen=True, slots=True)
class Squad:
    """A TaskForce and the TeamType that runs it, for one country.

    Attributes:
        number: Its four-digit ID number (family, then variant).
        label: What it is ("Line T2").
        members: Count and unit ID per member type.
        script: Its script.
        ranks: Each member's `LeadershipRating`.
        conduct: How the team behaves.
        max_teams: How many may exist at once (`Max`).
        unique: Members the AI must not clone.
    """

    number: int
    label: str
    members: tuple[tuple[int, str], ...]
    script: Script
    ranks: Mapping[str, int]
    conduct: Conduct
    max_teams: int = 2
    unique: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Call:
    """An AI trigger that raises a squad, and maybe a second one.

    Attributes:
        number: Its four-digit ID number.
        label: What it is.
        squad: Team1's squad number.
        gate: What it waits for.
        weight: Its starting weight; it learns between half and double.
        support: Team2's squad number, launched in the same frame.
    """

    number: int
    label: str
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
        support: Team2's ID, or `<none>`.
        country: The country it serves.
        side: The country's side index.
        gate: What it waits for.
        weight: Starting weight.
        base_defense: Whether it raises a base-defence team.
    """

    id: str
    name: str
    team: str
    support: str
    country: str
    side: int
    gate: Gate
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
        target_lists: Phobos `[AITargetTypes]`, in index order.
    """

    task_forces: tuple[TaskForce, ...]
    scripts: tuple[Script, ...]
    teams: tuple[TeamType, ...]
    triggers: tuple[Trigger, ...]
    leadership: dict[str, int]
    unique: frozenset[str]
    target_lists: tuple[tuple[str, ...], ...]
