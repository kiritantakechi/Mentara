"""The Mental AI's scripts: what each kind of team does.

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

How a trigger learns (gamemd 0x6E8DE0, 0x41FD60, 0x41FE20): when a team
ends, every trigger it leads gains weight if the team ran `49,0` and
loses weight if not, more the longer its record runs one way. So `49,0`
stands where a team has done its job: alive when its first objective
ends, by the clock or because nothing of the class is left. For a team
on Phobos attack lines the first objective is one kill (the odd-numbered
actions end on a member's kill). A script whose outcome cannot be read
(an agent is spent when it succeeds) marks nothing, and its trigger
keeps a steady weight.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Final, Protocol

__all__ = [
    "Line",
    "Lines",
    "Quarry",
    "Script",
    "Target",
    "absorb",
    "air_strike",
    "blitz",
    "bombing",
    "bridge_repair",
    "capture_tech",
    "charge",
    "chrono_assault",
    "counter_hunt",
    "curtain_charge",
    "decapitate",
    "drop",
    "economy_raid",
    "feint",
    "forward_deploy",
    "garrison",
    "hijack",
    "infiltrate",
    "line_direct",
    "line_flank",
    "line_hunt",
    "mounted",
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

type Line = tuple[int, int]
type Lines = tuple[Line, ...]


class Quarry(IntEnum):
    """What a vanilla attack line (`0,q`) goes for."""

    ANYTHING = 1
    STRUCTURES = 2
    HARVESTERS = 3
    INFANTRY = 4
    VEHICLES = 5
    FACTORIES = 6
    DEFENSES = 7
    POWER = 9
    OCCUPIED = 10


class Target(IntEnum):
    """What a Phobos attack or move line goes for (its target types)."""

    STRUCTURES = 2
    ORE_MINERS = 3
    FACTORIES = 6
    DEFENSES = 7
    POWER = 9
    TECH = 11
    REFINERY = 12
    ECONOMY = 18
    BARRACKS = 19
    VEHICLE_FACTORY = 20
    RADAR = 22
    TECH_LAB = 23
    SUPERWEAPON = 25
    CONSTRUCTION_YARD = 26
    BROKEN_BRIDGE_HUT = 37


class _Action(IntEnum):
    """The actions used: vanilla and Ares below 10000, Phobos above."""

    ATTACK = 0
    JUMP = 6  # to a 1-based line number
    UNLOAD = 8
    DEPLOY = 9
    MISSION = 11
    LOAD = 14
    SUCCESS = 49
    GATHER_AT_ENEMY = 53
    REGROUP_AT_BASE = 54
    TEAM_CAST = 55  # Ares: fire the group's superweapon on the team
    CHRONOSHIFT_TO_THREAT = 57
    ENTER_TANK_BUNKER = 61
    ENTER_BIO_REACTOR = 62
    OCCUPY_BATTLE_BUNKER = 63
    GARRISON = 64
    TAKE_VEHICLES = 67  # Ares
    STRIKE = 10000
    STRIKE_FARTHER = 10005
    STRIKE_LISTED = 10012  # the closest, most threatening of a list
    MOVE_TO_ENEMY = 10050
    MOVE_TO_OWN = 10053
    MOVE_TO_FAR_ENEMY = 10056
    AREA_GUARD = 10100
    BOARD = 10103
    MOVE_DISTANCE = 12001
    MOVE_END = 12002
    REWARD = 14000
    TIMEOUT = 16001
    TIMEOUT_STOP = 16002
    SKIP_CHANCE = 16003


# A Phobos attack action repeats until its class is gone; the next
# number is the same attack ended by the first kill a member makes.
_ONCE: Final[int] = 1
_HUNT_MISSION: Final[int] = 15
_UNLOAD_KEEP_PASSENGERS: Final[int] = 2  # lose transports, keep units
_ALL_ARRIVE: Final[int] = 2  # Phobos 12002: every member arrives
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
_CLOSER_TIMEOUT: Final[int] = 60
# How long a first objective may take before the team moves on. A team
# alive at its end has done its job (the success mark follows it).
_BREAK_IN: Final[int] = 100  # a line against the defences
_STRIKE: Final[int] = 60  # an opening strike before the push
_HUNT_PROOF: Final[int] = 120
_RAID_PROOF: Final[int] = 150  # a raid's first target, the way included
_SORTIE: Final[int] = 90
# Cells.
_FLANK_DISTANCE: Final[int] = 6
_DROP_DISTANCE: Final[int] = 4
# Ares: 53,n gathers n cells nearer the enemy's base than its safe
# distance when negative.
_CLOSER: Final[int] = -10
_AGENT_TRIES: Final[int] = 3
_SPY_SKIP_PERCENT: Final[int] = 30
_REWARD: Final[int] = 10


@dataclass(frozen=True, slots=True)
class Script:
    """What a kind of team does: a ScriptType before it has an ID.

    Attributes:
        code: Its number among the Mental AI's scripts.
        name: What it is ("Line").
        lines: Action and argument per line.
    """

    code: int
    name: str
    lines: Lines

    @property
    def casts(self) -> bool:
        """Whether a line fires a superweapon, a country's own."""
        return any(action == _Action.TEAM_CAST for action, _ in self.lines)

    @property
    def measured(self) -> bool:
        """Whether it tells its trigger how the team fared.

        It does when a line marks success or pays for a kill.
        """
        told = {_Action.SUCCESS, _Action.REWARD}
        return any(action in told for action, _ in self.lines)


# --- Lines -----------------------------------------------------------
#
# The engine's action numbers appear here only; the scripts below are
# written in these words.

_REGROUP: Final[Line] = (_Action.REGROUP_AT_BASE, 0)
_SUCCESS: Final[Line] = (_Action.SUCCESS, 0)
_HUNT: Final[Line] = (_Action.MISSION, _HUNT_MISSION)
_DEPLOY: Final[Line] = (_Action.DEPLOY, 0)
_LOAD: Final[Line] = (_Action.LOAD, 0)
_BOARD: Final[Line] = (_Action.BOARD, 0)
_UNLOAD: Final[Line] = (_Action.UNLOAD, _UNLOAD_KEEP_PASSENGERS)
_ALL_MUST_ARRIVE: Final[Line] = (_Action.MOVE_END, _ALL_ARRIVE)
_TAKE_VEHICLES: Final[Line] = (_Action.TAKE_VEHICLES, 0)


def _attack(quarry: Quarry) -> Line:
    """Vanilla attack, until nothing of the class is left."""
    return (_Action.ATTACK, quarry)


class _Strike(Protocol):
    """A Phobos attack line on a class, to its end or to one kill."""

    def __call__(self, target: int, *, once: bool = False) -> Line: ...


def _strike(target: int, *, once: bool = False) -> Line:
    """Phobos attack on the nearest of a class."""
    return (_Action.STRIKE + _ONCE * once, target)


def _strike_farther(target: int, *, once: bool = False) -> Line:
    """Phobos attack on the farthest of a class."""
    return (_Action.STRIKE_FARTHER + _ONCE * once, target)


def _strike_listed(target: int, *, once: bool = False) -> Line:
    """Phobos attack on an `[AITargetTypes]` list, by its index."""
    return (_Action.STRIKE_LISTED + _ONCE * once, target)


def _guard(seconds: int) -> Line:
    """Phobos Area Guard: every member picks its own targets."""
    return (_Action.AREA_GUARD, seconds)


def _gather(offset: int = 0) -> Line:
    """Vanilla gathering outside the enemy base, nearer if negative."""
    return (_Action.GATHER_AT_ENEMY, offset)


def _jump(line: int) -> Line:
    """Vanilla jump to a line, counted from 1."""
    return (_Action.JUMP, line)


def _timed(seconds: int, *lines: Line) -> Lines:
    """Lines that end after a time at most (Phobos 16001, 16002)."""
    return ((_Action.TIMEOUT, seconds), *lines, (_Action.TIMEOUT_STOP, 0))


def _proven(seconds: int, *lines: Line) -> Lines:
    """A first objective under a clock, then the success mark."""
    return (*_timed(seconds, *lines), _SUCCESS)


def _first_kill(strike: _Strike, target: int) -> Lines:
    """One kill of a class under a clock, the mark, then the rest of it.

    The clock covers the way there: a raid that has made its kill, or
    is still alive when the clock runs out, has got in.
    """
    return (*_proven(_RAID_PROOF, strike(target, once=True)), strike(target))


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
        for line in _timed(_CAST_TIMEOUT, (_Action.TEAM_CAST, group))
    )


def _tries(*attempt: Line) -> Lines:
    """An agent's attempt, made a few times with a wait between.

    Then the team ends and its agents are free for the next team that
    wants them. A team that waited for ever held a place under the
    team cap; one that ended at once was raised again on the next roll
    (112 times in eight minutes in a probe game).
    """
    again = (*attempt, _guard(_AGENT_RETRY)) * (_AGENT_TRIES - 1)
    return (*again, *attempt)


# A mutable builder: a branch's jump is counted from the lines so far.
@dataclass(slots=True)
class _Draft:
    """A script under construction, with random branches.

    Phobos 16003 skips the next line with a chance; when that line is a
    vanilla jump over a block, the block runs with that chance. Each
    team rolls for itself (`ScenarioClass::Random`, the same on every
    machine), so no two waves need take the same road.
    """

    lines: list[Line] = field(default_factory=list)

    def then(self, *lines: Line) -> _Draft:
        self.lines.extend(lines)
        return self

    def maybe(self, percent: int, *block: Line) -> _Draft:
        """Run a block with a chance in percent."""
        after = len(self.lines) + 2 + len(block)
        return self.then(
            (_Action.SKIP_CHANCE, percent),
            _jump(after + 1),
            *block,
        )

    def either(self, percent: int, first: Lines, second: Lines) -> _Draft:
        """Run `first` with a chance in percent, else `second`."""
        second_at = len(self.lines) + 2 + len(first) + 1
        end = second_at + len(second)
        return self.then(
            (_Action.SKIP_CHANCE, percent),
            _jump(second_at + 1),
            *first,
            _jump(end + 1),
            *second,
        )

    def gather(self, *, closer: int) -> _Draft:
        """Gather outside the enemy base.

        With a chance in percent the team gathers again, nearer: waves
        do not all stop at the same line.
        """
        return self.then(*_timed(_STAGE_TIMEOUT, _gather())).maybe(
            closer, *_timed(_CLOSER_TIMEOUT, _gather(_CLOSER))
        )

    def done(self) -> Lines:
        return tuple(self.lines)


def _stage(*, closer: int) -> _Draft:
    """Conscript, then gather outside the enemy base."""
    return _Draft().then(_REGROUP).gather(closer=closer)


_MOP_UP: Final[Lines] = (_attack(Quarry.ANYTHING),)


def _push() -> Lines:
    """Break the defences, hold a moment inside, then raze the base."""
    return (
        *_timed(_BREAK_IN, _attack(Quarry.DEFENSES)),
        _guard(_PUSH_PAUSE),
        _SUCCESS,
        _attack(Quarry.STRUCTURES),
        *_MOP_UP,
    )


# --- Assaults --------------------------------------------------------


def line_direct(casts: tuple[int, ...]) -> Lines:
    """Stage, then break the defences and raze the base.

    Each wave rolls its own approach: how near it gathers, whether it
    fights at the gathering point or rushes, and whether it opens on the
    factories or the power (a power cut takes the defences off line)
    before the defences.
    """
    return (
        _stage(closer=50)
        .maybe(70, _guard(_STAGE_FIGHT))
        .then(*_casts(casts))
        .maybe(35, *_timed(_STRIKE, _attack(Quarry.FACTORIES)))
        .maybe(35, *_timed(_STRIKE, _attack(Quarry.POWER)))
        .then(*_push())
        .done()
    )


def line_flank(casts: tuple[int, ...]) -> Lines:
    """Circle to the far side of the chosen enemy's base, hit it there.

    Phobos's move to the farthest enemy building of a class (`10056`, by
    distance) takes the team round the base, all members arriving
    together; the team only targets its house's chosen enemy, so the
    far building is that enemy's. The team rolls which class it circles
    to (power plants or any building) and what it hits first.
    """

    def circle(target: Target) -> Lines:
        return (
            (_Action.MOVE_DISTANCE, _FLANK_DISTANCE),
            _ALL_MUST_ARRIVE,
            *_timed(_FLANK_TIMEOUT, (_Action.MOVE_TO_FAR_ENEMY, target)),
        )

    return (
        _Draft()
        .then(_REGROUP)
        .either(50, circle(Target.POWER), circle(Target.STRUCTURES))
        .maybe(70, _guard(_STAGE_FIGHT))
        .then(*_casts(casts))
        .either(
            50,
            _timed(_BREAK_IN, _attack(Quarry.POWER)),
            _timed(_BREAK_IN, _attack(Quarry.FACTORIES)),
        )
        .then(_SUCCESS, _attack(Quarry.STRUCTURES), *_MOP_UP)
        .done()
    )


def line_hunt(casts: tuple[int, ...]) -> Lines:
    """Stage, then hunt the enemy army; members pick their targets."""
    return (
        _stage(closer=50)
        .then(*_casts(casts), *_proven(_HUNT_PROOF, _HUNT), _HUNT)
        .done()
    )


def siege(casts: tuple[int, ...]) -> Lines:
    """Stage, then outrange the defences and level the base.

    Some sieges shell the power first, to take the defences off line.
    """
    return (
        _stage(closer=0)
        .maybe(60, _guard(_STAGE_FIGHT))
        .then(*_casts(casts))
        .maybe(40, *_timed(_STRIKE, _attack(Quarry.POWER)))
        .then(
            *_proven(_BREAK_IN, _attack(Quarry.DEFENSES)),
            _attack(Quarry.STRUCTURES),
            *_MOP_UP,
        )
        .done()
    )


def superweapon_snipe(casts: tuple[int, ...]) -> Lines:
    """Stage, then destroy the enemy's superweapons first."""
    return (
        _stage(closer=50)
        .then(
            *_casts(casts),
            (_Action.REWARD, _REWARD * 2),
            *_first_kill(_strike, Target.SUPERWEAPON),
            _attack(Quarry.STRUCTURES),
            *_MOP_UP,
        )
        .done()
    )


def decapitate(casts: tuple[int, ...]) -> Lines:
    """Stage, then go for the construction yards, then everything.

    For a hero that out-damages buildings, such as a walking bomb.
    """
    return (
        _stage(closer=50)
        .then(
            *_casts(casts),
            *_first_kill(_strike, Target.CONSTRUCTION_YARD),
            _attack(Quarry.FACTORIES),
            _attack(Quarry.STRUCTURES),
            *_MOP_UP,
        )
        .done()
    )


def mounted(casts: tuple[int, ...]) -> Lines:
    """Board the team's own carriers, ride out, fight from them.

    Phobos 10103 seats each passenger in a transport of the same team
    (an IFV takes its weapon from its passenger; an open-topped carrier
    lets its squad fire); then the team attacks as a line.
    """
    return (
        _Draft()
        .then(_REGROUP, _BOARD)
        .gather(closer=50)
        .maybe(70, _guard(_STAGE_FIGHT))
        .then(*_casts(casts), *_push())
        .done()
    )


def forward_deploy() -> Lines:
    """Stage outside the enemy base and deploy there (vanilla 9).

    For units that unfold into a turret, a minefield or an outpost; the
    escort then fights from the new position. Deployed is done.
    """
    return _stage(closer=50).then(_DEPLOY, _SUCCESS, *_MOP_UP).done()


def charge(first: Quarry, second: Quarry, casts: tuple[int, ...]) -> Lines:
    """Drive straight at what the team hurts most (vanilla quarries).

    For units that explode on their target or must deploy to fire:
    Phobos picks targets with the leader's undeployed weapon and finds
    none for them. The charge spends the team, so reaching the staging
    line alive is its success.
    """
    return (
        _REGROUP,
        *_proven(_STAGE_TIMEOUT, _gather()),
        *_casts(casts),
        _attack(first),
        _attack(second),
        *_MOP_UP,
    )


def chrono_assault(quarry: Quarry, casts: tuple[int, ...]) -> Lines:
    """Jump next to the enemy's greatest threat of a class and fight.

    Vanilla 57 waits while the Chronosphere is almost charged and fires
    the sphere the phobos layer pins (`AIChronoSphereSW`); MO's own
    assault used action 56, whose lookup took a sphere the AI never
    owns.
    """
    return (
        _REGROUP,
        (_Action.CHRONOSHIFT_TO_THREAT, quarry),
        _guard(_ARRIVAL_FIGHT),
        *_casts(casts),
        *_proven(_BREAK_IN, _attack(quarry)),
        _attack(Quarry.STRUCTURES),
        *_MOP_UP,
    )


def curtain_charge(curtain: int, casts: tuple[int, ...]) -> Lines:
    """Stage, raise the Iron Curtain, and drive through the defences.

    Under the curtain the whole team takes one target at a time:
    Phobos attack lines give every member the leader's target.
    """
    others = tuple(group for group in casts if group != curtain)
    return (
        _REGROUP,
        *_timed(_STAGE_TIMEOUT, _gather()),
        *_casts(others),
        *_casts((curtain,)),
        *_first_kill(_strike, Target.DEFENSES),
        _strike(Target.FACTORIES),
        _attack(Quarry.STRUCTURES),
        *_MOP_UP,
    )


def counter_hunt(target_list: int) -> Lines:
    """Hunt every enemy unit in an `[AITargetTypes]` list.

    The trigger's weight rises at once when the team kills one (Phobos
    14000).
    """
    return (
        _REGROUP,
        (_Action.REWARD, _REWARD),
        *_first_kill(_strike_listed, target_list),
        _guard(_COUNTER_PAUSE),
        *_MOP_UP,
    )


# --- Raids -----------------------------------------------------------


def _raid(percent: int, first: Target, second: Target, *later: Target) -> Lines:
    """Phobos attack lines on two classes, in an order a raid rolls."""

    def opening(target: Target, other: Target) -> Lines:
        return (*_first_kill(_strike, target), _strike(other))

    return (
        _Draft()
        .then(_REGROUP)
        .either(percent, opening(first, second), opening(second, first))
        .then(*map(_strike, later), *_MOP_UP)
        .done()
    )


def blitz() -> Lines:
    """Fast units straight at the factories, then the yard."""
    return _raid(50, Target.VEHICLE_FACTORY, Target.BARRACKS, Target.CONSTRUCTION_YARD)


def economy_raid() -> Lines:
    """Harvesters and refineries, in an order each raid rolls."""
    return _raid(60, Target.ORE_MINERS, Target.ECONOMY)


def power_raid() -> Lines:
    """Black out the base: power plants and radar, in either order."""
    return _raid(60, Target.POWER, Target.RADAR)


def feint() -> Lines:
    """Draw the defence off: hit the enemy's farthest buildings."""
    return (
        _Draft()
        .then(_REGROUP)
        .either(
            50,
            _first_kill(_strike_farther, Target.POWER),
            _first_kill(_strike_farther, Target.STRUCTURES),
        )
        .then(*_MOP_UP)
        .done()
    )


def bombing(first: Quarry, second: Quarry) -> Lines:
    """Bomb planters walk up to two classes, in an order they roll.

    Vanilla quarries: a planter's bomb does the damage, not its weapon,
    and Phobos, judging the leader's weapon, found nothing for an
    Arsonist or a Repulsor to attack in play.
    """

    def opening(quarry: Quarry, other: Quarry) -> Lines:
        return (*_proven(_RAID_PROOF, _attack(quarry)), _attack(other))

    return (
        _Draft()
        .then(_REGROUP)
        .either(50, opening(first, second), opening(second, first))
        .then(_attack(first), _attack(second), *_MOP_UP)
        .done()
    )


def air_strike(first: Quarry, second: Quarry) -> Lines:
    """Two vanilla quarries, in an order each strike rolls.

    Vanilla quarries, as MO's own air teams use: a Phobos attack line
    found no target for Comanches in a probe game and the team hovered
    in place. Vanilla `0,q` repeats until the class is gone, and the
    engine sends the craft to rearm and back. A squadron still flying
    after a strike on each class is a success: one the enemy's
    anti-air shoots down first is not, and its trigger loses weight.
    Both strikes come before the mark, so a class with nothing in it
    does not hand the squadron its success unfought.
    """

    def opening(quarry: Quarry, other: Quarry) -> Lines:
        return (
            *_timed(_SORTIE, _attack(quarry)),
            *_proven(_SORTIE, _attack(other)),
        )

    return (
        _Draft()
        .either(65, opening(first, second), opening(second, first))
        .then(_attack(first), _attack(second), *_MOP_UP)
        .done()
    )


# --- Holding ground --------------------------------------------------


def watch(casts: tuple[int, ...]) -> Lines:
    """Guard the base front, casting home superweapons each round."""
    return (_REGROUP, *_casts(casts), _guard(_WATCH), _jump(2))


def patrol() -> Lines:
    """Walk between refineries and power plants, guarding at each."""
    return (
        (_Action.MOVE_TO_OWN, Target.REFINERY),
        _guard(_PATROL_STOP),
        (_Action.MOVE_TO_OWN, Target.POWER),
        _guard(_PATROL_STOP),
        _jump(1),
    )


def tech_guard() -> Lines:
    """Hold the tech buildings the house has taken."""
    return ((_Action.MOVE_TO_OWN, Target.TECH), _guard(_WATCH), _jump(1))


def garrison() -> Lines:
    """Garrison the nearest civilian building, then fight from it."""
    return ((_Action.GARRISON, 0), _attack(Quarry.VEHICLES), *_MOP_UP)


def occupy_bunker() -> Lines:
    """Occupy the house's own battle bunker."""
    return ((_Action.OCCUPY_BATTLE_BUNKER, 0),)


def tank_bunker() -> Lines:
    """Dig into the house's own tank bunker."""
    return ((_Action.ENTER_TANK_BUNKER, 0),)


def absorb() -> Lines:
    """Feed infantry into the house's bio reactor."""
    return ((_Action.ENTER_BIO_REACTOR, 0),)


def redeploy() -> Lines:
    """Deploy the MCV where it stands."""
    return (_DEPLOY,)


# --- Agents ----------------------------------------------------------


def capture_tech() -> Lines:
    """Engineers take the nearest tech building, one after another."""
    return _tries(*_timed(_DROP_TIMEOUT, _strike(Target.TECH, once=True)))


def bridge_repair() -> Lines:
    """An engineer mends the nearest broken bridge, or waits for one."""
    return (
        _strike(Target.BROKEN_BRIDGE_HUT, once=True),
        _guard(_AGENT_RETRY),
        _jump(1),
    )


def infiltrate(target: Target) -> Lines:
    """A spy enters the nearest building of a class.

    Each try is skipped with a chance, so spies do not all set out the
    moment they are trained.
    """
    return _tries((_Action.SKIP_CHANCE, _SPY_SKIP_PERCENT), _strike(target, once=True))


def drop(target: Target) -> Lines:
    """Load agents into the team's transport, drive in, unload, enter.

    Vanilla 14 seats the passengers and saves the transport's place, so
    with `TransportsReturnOnUnload` vanilla 8,2 sends the empty
    transport home to serve again (Phobos 10103 saves no place). The
    agents on the ground by their target are the success.
    """
    return (
        _LOAD,
        (_Action.MOVE_DISTANCE, _DROP_DISTANCE),
        *_timed(_DROP_TIMEOUT, (_Action.MOVE_TO_ENEMY, target)),
        _UNLOAD,
        _SUCCESS,
        _strike(target, once=True),
    )


def hijack() -> Lines:
    """Stage, then take the nearest enemy vehicles (Ares 67)."""
    return (_REGROUP, *_timed(_STAGE_TIMEOUT, _gather()), _TAKE_VEHICLES)


# --- At sea ----------------------------------------------------------


def naval_line() -> Lines:
    """Stage at sea, then fight whatever the fleet can reach.

    Vanilla quarries, as MO's own fleets use: the engine gives each
    ship a target it can hit. A Phobos line asks the leader, and a
    submarine leading found nothing on shore for the ships behind it
    (36 times for one team type in a probe game).
    """
    return (
        _stage(closer=0)
        .maybe(70, _guard(_STAGE_FIGHT))
        .then(
            *_proven(_BREAK_IN, _attack(Quarry.ANYTHING)),
            _attack(Quarry.STRUCTURES),
            *_MOP_UP,
        )
        .done()
    )


def naval_hunt() -> Lines:
    """Hunt ships and submarines (to a ship, the vehicles in reach)."""
    hunt = _attack(Quarry.VEHICLES)
    return (*_proven(_BREAK_IN, hunt), hunt, *_MOP_UP)


def naval_bombard() -> Lines:
    """Shell the coastal defences, then the base."""
    return (
        *_proven(_BREAK_IN, _attack(Quarry.DEFENSES)),
        _attack(Quarry.DEFENSES),
        _attack(Quarry.STRUCTURES),
        *_MOP_UP,
    )
