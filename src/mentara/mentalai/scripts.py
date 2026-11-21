"""The Mental AI's ScriptTypes: what each kind of team does.

How a team fights, from the Phobos v0.5-alpha2 and YR sources:

- Phobos attack lines give every member the leader's target each frame,
  so a mixed team's anti-air and medics would chase a building. Mixed
  teams stage with vanilla moves and push with vanilla `0,q`, which only
  hands the focus to members that have no target of their own, and
  pause in Phobos Area Guard (`10100`), where every member picks its
  own target. Phobos attack lines serve single-role teams and agents.
- Phobos moves and attacks have no timeout; a 16001 timer ends the line
  they run in, and 16002 stops it.
- Not used, broken in alpha2: 12000 (never waits), 10102 (never
  regroups), 18000, the "random" list attacks, and 10104's charge
  test.
"""

from dataclasses import dataclass
from typing import Final

__all__ = [
    "Lines",
    "Script",
    "absorb",
    "air_strike",
    "blitz",
    "capture_tech",
    "chrono_assault",
    "counter_hunt",
    "curtain_charge",
    "drop",
    "economy_raid",
    "feint",
    "garrison",
    "hijack",
    "infiltrate",
    "line_direct",
    "line_flank",
    "line_hunt",
    "make_script",
    "naval_bombard",
    "naval_hunt",
    "naval_line",
    "occupy_bunker",
    "patrol",
    "power_raid",
    "redeploy",
    "siege",
    "superweapon_snipe",
    "tank_bunker",
    "tech_guard",
    "watch",
]

type Lines = tuple[tuple[int, int], ...]

# Vanilla and Ares actions.
_ATTACK: Final[int] = 0
_JUMP: Final[int] = 6  # 1-based line number
_UNLOAD: Final[int] = 8
_DEPLOY: Final[int] = 9
_MISSION: Final[int] = 11
_SUCCESS: Final[int] = 49
_GATHER_AT_ENEMY: Final[int] = 53
_REGROUP_AT_BASE: Final[int] = 54
_TEAM_CAST: Final[int] = 55  # Ares: fire the group's superweapon here
_CHRONOSHIFT_TO_THREAT: Final[int] = 57
_ENTER_TANK_BUNKER: Final[int] = 61
_ENTER_BIO_REACTOR: Final[int] = 62
_OCCUPY_BATTLE_BUNKER: Final[int] = 63
_GARRISON: Final[int] = 64
_TAKE_VEHICLES: Final[int] = 67  # Ares
# Vanilla quarries and missions.
ANYTHING: Final[int] = 1
STRUCTURES: Final[int] = 2
INFANTRY: Final[int] = 4
VEHICLES: Final[int] = 5
FACTORIES: Final[int] = 6
DEFENSES: Final[int] = 7
POWER: Final[int] = 9
OCCUPIED: Final[int] = 10
_HUNT: Final[int] = 15
# Phobos actions.
_P_ATTACK: Final[int] = 10000
_P_ATTACK_ONCE: Final[int] = 10001
_P_ATTACK_LIST_THREAT: Final[int] = 10012
_P_ATTACK_FARTHER: Final[int] = 10005
_P_MOVE_ENEMY: Final[int] = 10050
_P_MOVE_ENEMY_FARTHER: Final[int] = 10056
_P_MOVE_FRIENDLY: Final[int] = 10053
_P_AREA_GUARD: Final[int] = 10100
_P_LOAD: Final[int] = 10103
_P_MOVE_DISTANCE: Final[int] = 12001
_P_REWARD: Final[int] = 14000
_P_TIMEOUT: Final[int] = 16001
_P_TIMEOUT_STOP: Final[int] = 16002
_P_SKIP_CHANCE: Final[int] = 16003
# Phobos target types.
T_STRUCTURES: Final[int] = 2
T_ORE_MINERS: Final[int] = 3
T_FACTORIES: Final[int] = 6
T_DEFENSES: Final[int] = 7
T_POWER: Final[int] = 9
T_TECH: Final[int] = 11
T_REFINERY: Final[int] = 12
T_ECONOMY: Final[int] = 18
T_BARRACKS: Final[int] = 19
T_VEHICLE_FACTORY: Final[int] = 20
T_RADAR: Final[int] = 22
T_TECH_LAB: Final[int] = 23
T_SUPERWEAPON: Final[int] = 25
T_CONSTRUCTION_YARD: Final[int] = 26
T_NAVAL_UNITS: Final[int] = 31
T_MOBILE: Final[int] = 32
# Seconds.
_STAGE_TIMEOUT: Final[int] = 90
_STAGE_FIGHT: Final[int] = 15
_PUSH_PAUSE: Final[int] = 8
_ARRIVAL_FIGHT: Final[int] = 8
_CAST_TIMEOUT: Final[int] = 10
_FLANK_TIMEOUT: Final[int] = 150
_DROP_TIMEOUT: Final[int] = 120
_WATCH: Final[int] = 60
_PATROL_STOP: Final[int] = 30
_AGENT_RETRY: Final[int] = 30
_COUNTER_PAUSE: Final[int] = 10
_SPY_SKIP_PERCENT: Final[int] = 30
_REWARD: Final[int] = 10
_FLANK_DISTANCE: Final[int] = 6
_DROP_DISTANCE: Final[int] = 4
_UNLOAD_KEEP_PASSENGERS: Final[int] = 2  # lose transports, keep units


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
    lines: Lines


def make_script(code: int, name: str, lines: Lines, country_code: str) -> Script:
    """A script, a country's own when it casts that country's weapons.

    Args:
        code: Its ID number.
        name: Display name.
        lines: Its lines.
        country_code: The country's two-letter code.

    Returns:
        `MNTSC<code><country>-G` when a line casts a superweapon, else
        the shared `MNTSC<code>-G`.
    """
    own = any(action == _TEAM_CAST for action, _ in lines)
    suffix = country_code if own else ""
    label = f" ({country_code})" if own else ""
    return Script(f"MNTSC{code}{suffix}-G", name + label, lines)


def _casts(groups: tuple[int, ...]) -> Lines:
    """Cast each team-cast superweapon group at the team.

    Ares's action 55 waits while a superweapon of the group is almost
    charged (`AIMinorSuperReadyPercent`), so each cast runs under a
    timeout; a group the house lacks or has far from charged is
    skipped.
    """
    return tuple(
        line
        for group in groups
        for line in (
            (_P_TIMEOUT, _CAST_TIMEOUT),
            (_TEAM_CAST, group),
            (_P_TIMEOUT_STOP, 0),
        )
    )


def _staged(casts: tuple[int, ...], *push: tuple[int, int]) -> Lines:
    """Conscript, stage near the enemy base, fight there, cast, push."""
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_TIMEOUT, _STAGE_TIMEOUT),
        (_GATHER_AT_ENEMY, 0),
        (_P_TIMEOUT_STOP, 0),
        (_P_AREA_GUARD, _STAGE_FIGHT),
        *_casts(casts),
        *push,
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def line_direct(casts: tuple[int, ...]) -> Lines:
    """Stage, then break the defences and raze the base."""
    return _staged(
        casts,
        (_ATTACK, DEFENSES),
        (_P_AREA_GUARD, _PUSH_PAUSE),
        (_ATTACK, STRUCTURES),
    )


def line_flank(casts: tuple[int, ...]) -> Lines:
    """Circle to the far side of the chosen enemy's base, hit it there.

    Phobos's move to the farthest enemy structure (`10056`, by
    distance) takes the team round the base; the team only targets its
    house's chosen enemy, so the far structure is that enemy's.
    """
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_MOVE_DISTANCE, _FLANK_DISTANCE),
        (_P_TIMEOUT, _FLANK_TIMEOUT),
        (_P_MOVE_ENEMY_FARTHER, T_STRUCTURES),
        (_P_TIMEOUT_STOP, 0),
        (_P_AREA_GUARD, _STAGE_FIGHT),
        *_casts(casts),
        (_ATTACK, STRUCTURES),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def line_hunt(casts: tuple[int, ...]) -> Lines:
    """Stage, then hunt the enemy army; members pick their targets."""
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_TIMEOUT, _STAGE_TIMEOUT),
        (_GATHER_AT_ENEMY, 0),
        (_P_TIMEOUT_STOP, 0),
        *_casts(casts),
        (_MISSION, _HUNT),
    )


def siege(casts: tuple[int, ...]) -> Lines:
    """Stage, then outrange the defences and level the base."""
    return _staged(casts, (_ATTACK, DEFENSES), (_ATTACK, STRUCTURES))


def superweapon_snipe(casts: tuple[int, ...]) -> Lines:
    """Stage, then destroy the enemy's superweapons first."""
    return _staged(
        casts,
        (_P_REWARD, _REWARD * 2),
        (_P_ATTACK_ONCE, T_SUPERWEAPON),
        (_P_ATTACK_ONCE, T_SUPERWEAPON),
        (_ATTACK, STRUCTURES),
    )


def blitz() -> Lines:
    """Fast units straight at the factories, then the yard."""
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_ATTACK, T_VEHICLE_FACTORY),
        (_P_ATTACK, T_BARRACKS),
        (_P_ATTACK, T_CONSTRUCTION_YARD),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def feint() -> Lines:
    """Draw the defence off: hit the enemy's farthest buildings."""
    return (
        (_P_ATTACK_FARTHER, T_STRUCTURES),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def economy_raid() -> Lines:
    """Harvesters first, then refineries and purifiers."""
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_ATTACK, T_ORE_MINERS),
        (_P_ATTACK, T_ECONOMY),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def power_raid() -> Lines:
    """Black out the base: power plants, then radar."""
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_ATTACK, T_POWER),
        (_P_ATTACK, T_RADAR),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def air_strike(*quarries: int) -> Lines:
    """Vanilla quarries, as MO's own air teams use.

    A Phobos attack line found no target for Comanches in a probe game
    and the team hovered in place. Vanilla `0,q` repeats until the
    class is gone, and the engine sends the craft to rearm and back.
    """
    return (
        *((_ATTACK, quarry) for quarry in quarries),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def watch(casts: tuple[int, ...]) -> Lines:
    """Guard the base front, casting home superweapons each round."""
    return (
        (_REGROUP_AT_BASE, 0),
        *_casts(casts),
        (_P_AREA_GUARD, _WATCH),
        (_JUMP, 2),
    )


def patrol() -> Lines:
    """Walk between refineries and power plants, guarding at each."""
    return (
        (_P_MOVE_FRIENDLY, T_REFINERY),
        (_P_AREA_GUARD, _PATROL_STOP),
        (_P_MOVE_FRIENDLY, T_POWER),
        (_P_AREA_GUARD, _PATROL_STOP),
        (_JUMP, 1),
    )


def tech_guard() -> Lines:
    """Hold the tech buildings the house has taken."""
    return (
        (_P_MOVE_FRIENDLY, T_TECH),
        (_P_AREA_GUARD, _WATCH),
        (_JUMP, 1),
    )


def capture_tech() -> Lines:
    """Engineers take the nearest tech building, or wait and look again.

    An agent with no target waits: ending instead frees the trigger at
    once, so every roll would raise the same idle team again (a probe
    game raised one 112 times in eight minutes).
    """
    return (
        (_P_TIMEOUT, _DROP_TIMEOUT),
        (_P_ATTACK_ONCE, T_TECH),
        (_P_TIMEOUT_STOP, 0),
        (_P_AREA_GUARD, _AGENT_RETRY),
        (_JUMP, 1),
    )


def infiltrate(target: int) -> Lines:
    """A spy enters the nearest building of a class, or waits."""
    return (
        (_P_SKIP_CHANCE, _SPY_SKIP_PERCENT),
        (_P_ATTACK_ONCE, target),
        (_P_AREA_GUARD, _AGENT_RETRY),
        (_JUMP, 1),
    )


def drop(target: int) -> Lines:
    """Load agents into the team's transport, drive in, unload, enter.

    Phobos 10103 seats the passengers in the team's own transports;
    vanilla 8,2 unloads and lets the transport leave the team.
    """
    return (
        (_P_LOAD, 0),
        (_P_MOVE_DISTANCE, _DROP_DISTANCE),
        (_P_TIMEOUT, _DROP_TIMEOUT),
        (_P_MOVE_ENEMY, target),
        (_P_TIMEOUT_STOP, 0),
        (_UNLOAD, _UNLOAD_KEEP_PASSENGERS),
        (_P_ATTACK_ONCE, target),
        (_SUCCESS, 0),
    )


def hijack() -> Lines:
    """Stage, then take the nearest enemy vehicles (Ares 67)."""
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_TIMEOUT, _STAGE_TIMEOUT),
        (_GATHER_AT_ENEMY, 0),
        (_P_TIMEOUT_STOP, 0),
        (_TAKE_VEHICLES, 0),
        (_SUCCESS, 0),
    )


def garrison() -> Lines:
    """Garrison the nearest civilian building, then fight from it."""
    return ((_GARRISON, 0), (_SUCCESS, 0), (_ATTACK, VEHICLES), (_ATTACK, ANYTHING))


def occupy_bunker() -> Lines:
    """Occupy the house's own battle bunker."""
    return ((_OCCUPY_BATTLE_BUNKER, 0), (_SUCCESS, 0))


def tank_bunker() -> Lines:
    """Dig into the house's own tank bunker."""
    return ((_ENTER_TANK_BUNKER, 0), (_SUCCESS, 0))


def absorb() -> Lines:
    """Feed infantry into the house's bio reactor."""
    return ((_ENTER_BIO_REACTOR, 0), (_SUCCESS, 0))


def redeploy() -> Lines:
    """Deploy the MCV where it stands."""
    return ((_DEPLOY, 0), (_SUCCESS, 0))


def chrono_assault(quarry: int, casts: tuple[int, ...]) -> Lines:
    """Jump next to the enemy's greatest threat of a class and fight.

    Vanilla 57 waits while the Chronosphere is almost charged and fires
    the sphere the phobos layer pins (`AIChronoSphereSW`); MO's own
    assault used action 56, whose lookup took a sphere the AI never
    owns.
    """
    return (
        (_REGROUP_AT_BASE, 0),
        (_CHRONOSHIFT_TO_THREAT, quarry),
        (_P_AREA_GUARD, _ARRIVAL_FIGHT),
        *_casts(casts),
        (_ATTACK, quarry),
        (_ATTACK, STRUCTURES),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def curtain_charge(curtain: int, casts: tuple[int, ...]) -> Lines:
    """Stage, raise the Iron Curtain, and drive through the defences.

    Under the curtain the whole team takes one target at a time:
    Phobos attack lines give every member the leader's target.
    """
    others = tuple(group for group in casts if group != curtain)
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_TIMEOUT, _STAGE_TIMEOUT),
        (_GATHER_AT_ENEMY, 0),
        (_P_TIMEOUT_STOP, 0),
        *_casts(others),
        *_casts((curtain,)),
        (_P_ATTACK, T_DEFENSES),
        (_P_ATTACK, T_FACTORIES),
        (_ATTACK, STRUCTURES),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )


def counter_hunt(target_list: int) -> Lines:
    """Hunt every enemy unit in an `[AITargetTypes]` list.

    The trigger's weight rises when the team kills one (Phobos 14000).
    """
    return (
        (_REGROUP_AT_BASE, 0),
        (_P_REWARD, _REWARD),
        (_P_ATTACK_LIST_THREAT, target_list),
        (_P_AREA_GUARD, _COUNTER_PAUSE),
        (_ATTACK, ANYTHING),
    )


def naval_line() -> Lines:
    """Stage at sea, then ships, defences and the shore."""
    return _staged(
        (),
        (_P_ATTACK, T_NAVAL_UNITS),
        (_P_ATTACK, T_DEFENSES),
        (_ATTACK, STRUCTURES),
    )


def naval_hunt() -> Lines:
    """Hunt ships and submarines."""
    return ((_P_ATTACK, T_NAVAL_UNITS), (_SUCCESS, 0), (_ATTACK, ANYTHING))


def naval_bombard() -> Lines:
    """Shell the coastal defences, then the base."""
    return (
        (_P_ATTACK, T_DEFENSES),
        (_P_ATTACK, T_FACTORIES),
        (_ATTACK, STRUCTURES),
        (_SUCCESS, 0),
        (_ATTACK, ANYTHING),
    )
