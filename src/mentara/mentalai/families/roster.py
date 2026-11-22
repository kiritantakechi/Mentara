"""Every unit its job.

Slots take a side's best units; these families give every other unit a
squad of its own, so a side fields its whole roster: each strike craft,
each hero, each unit that deploys forward, each bomb planter, each
carrier and each charger, and last a strike group for whatever no
squad has taken.
"""

from dataclasses import dataclass
from typing import Final
lazy from collections.abc import Iterator, Mapping

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Country, Factory, Kind, Role, Unit
from mentara.mentalai.families._kit import (
    ARMED,
    ASSAULT,
    BEELINE,
    HUNTER,
    OFF_GROUND,
    OTHER_JOBS,
    RAID,
    SORTIE,
    TOP,
    Aim,
    Context,
    Course,
    Order,
    Series,
    aim_of,
    alone,
    from_tier,
    harm,
    on_call,
    roster,
    squadron,
    unlocked,
)
from mentara.mentalai.families.assault import DIRECT, HUNTING
from mentara.mentalai.families.defense import SKY_WATCH
from mentara.mentalai.families.raids import air_script
from mentara.mentalai.model import (
    Condition,
    Crew,
    Gate,
    Member,
    Squad,
)
from mentara.mentalai.scripts import Quarry, Script
from mentara.mentalai.slots import (
    AA,
    ANY_HERO,
    BOMBER,
    FRONT,
    HERO,
    INFANTRY,
    SCREEN,
    Seats,
    fill,
)
lazy from mentara.mentalai.catalog import Firepower


def _flies_to_fight(unit: Unit) -> bool:
    if not unit.has(Role.AIRBORNE) or unit.roles & (OTHER_JOBS | {Role.NAVAL}):
        return False
    return bool(unit.roles & (ARMED | {Role.AA}))


def _fighting_hero(unit: Unit) -> bool:
    return unit.has(Role.HERO) and bool(unit.roles & ARMED)


def _fights_on_ground(unit: Unit) -> bool:
    return bool(unit.roles & ARMED) and not unit.roles & (OTHER_JOBS | OFF_GROUND)


def _ground_deployer(unit: Unit) -> bool:
    return unit.has(Role.DEPLOYER) and not unit.roles & OFF_GROUND


def _armed_carrier(unit: Unit) -> bool:
    return (
        unit.kind is Kind.VEHICLE
        and unit.has(Role.TRANSPORT)
        and bool(unit.roles & ARMED)
        and unit.size_limit > 0
        and not unit.roles & (OFF_GROUND | {Role.HARVESTER, Role.MCV, Role.HERO})
    )


def _charger(unit: Unit) -> bool:
    return unit.has(Role.CHARGER) and not unit.has(Role.HERO)


def squadrons(ctx: Context, country: Country) -> Iterator[Order]:
    """A squadron per strike craft.

    Airfield-bound craft fly in pairs, one team at a time: each needs a
    pad. An interceptor holds the sky over the base.
    """
    for index, (unit, tier) in enumerate(
        roster(ctx, country, _flies_to_fight), start=1
    ):
        gate = from_tier(country, tier)
        if gate is None:
            continue
        docked = unit.has(Role.DOCKED)
        squad = Squad(
            Series.SQUADRON.at(index),
            f"Squadron {unit.id}",
            squadron(unit),
            SKY_WATCH if unit.has(Role.AA_ONLY) else air_script(unit),
            SORTIE,
            max_teams=1 if docked else 2,
        )
        yield from on_call(squad, gate, 30)


_HERO_ESCORT: Final[Seats] = ((ANY_HERO, 1), (FRONT, 2), (SCREEN, 2), (AA, 1))


def heroes(ctx: Context, country: Country) -> Iterator[Order]:
    """Each hero leads an escort; a wrecker goes for the yards.

    A hero that hurts buildings most, such as M.A.D.M.A.N.'s AI twin,
    goes for the construction yards first.

    Mental AI lets the AI pass `BuildLimit`, so heroes return when lost.
    """
    casts = country.front_casts
    for index, (unit, tier) in enumerate(roster(ctx, country, _fighting_hero), start=1):
        gate = from_tier(country, tier)
        if gate is None:
            continue
        if unit.has(Role.AIRBORNE):
            crew: Crew | None = alone(unit, 1)
        else:
            others = (u for u in ctx.fielded(country, tier) if not u.has(Role.HERO))
            crew = fill(_HERO_ESCORT, (unit, *others), tier, required=(ANY_HERO,))
        if crew is None:
            continue
        if aim_of(unit) is Aim.BUILDINGS:
            script = Script(8400, "Decapitation", sc.decapitate(casts))
        else:
            script = DIRECT.script(casts)
        squad = Squad(
            Series.HERO.at(index),
            f"Hero {unit.id}",
            crew,
            script,
            ASSAULT,
            max_teams=1,
        )
        yield from on_call(squad, gate, 40)


# A deployer leaves the leading to its escort.
_DEPLOYER_RANK: Final[int] = 2


# A unit's emplacement at home is numbered this far past its forward
# one.
_EMPLACE_PLACE: Final[int] = 50


def deployers(ctx: Context, country: Country) -> Iterator[Order]:
    """Units that unfold into something deploy at the enemy's gate.

    And, less often, beside the house's own defences, as MO's own AI
    dug its Irritators and Sweepers in.
    """
    forward = Script(8500, "Forward Deploy", sc.forward_deploy())
    home = Script(8510, "Emplace", sc.emplace())
    for index, (unit, tier) in enumerate(
        roster(ctx, country, _ground_deployer), start=1
    ):
        gate = from_tier(country, tier)
        if gate is None:
            continue
        escort = fill(((SCREEN, 2),), ctx.fielded(country, tier), tier) or ()
        count = 1 if unit.has(Role.HERO) else 2
        squad = Squad(
            Series.DEPLOYER.at(index),
            f"Forward {unit.id}",
            (Member(count, unit, _DEPLOYER_RANK), *escort),
            forward,
            ASSAULT,
        )
        yield from on_call(squad, gate, 25)
        squad = Squad(
            Series.DEPLOYER.at(_EMPLACE_PLACE + index),
            f"Emplace {unit.id}",
            alone(unit, count),
            home,
            BEELINE,
            max_teams=1,
        )
        yield from on_call(squad, gate, 10)


_BOMB_COURSES: Final[Mapping[Aim, Course]] = frozendict(
    {
        Aim.VEHICLES: Course(8601, (Quarry.VEHICLES, Quarry.HARVESTERS)),
        Aim.INFANTRY: Course(8602, (Quarry.INFANTRY, Quarry.OCCUPIED)),
        Aim.BUILDINGS: Course(8603, (Quarry.POWER, Quarry.FACTORIES)),
    }
)


def bombers(ctx: Context, country: Country) -> Iterator[Order]:
    """Bomb-planting infantry slip in to what their bombs stick to.

    A planter's warhead says which classes it touches (an Arsonist's
    only buildings, a Repulsor's only vehicles), however little damage
    the planting itself does.
    """
    for index, (unit, tier) in enumerate(roster(ctx, country, BOMBER.fits), start=1):
        gate = from_tier(country, tier)
        if gate is None:
            continue
        aim = aim_of(unit)
        course = _BOMB_COURSES[aim]
        script = Script(
            course.code, f"Bombing {aim.value}", sc.bombing(*course.quarries)
        )
        squad = Squad(
            Series.BOMBER.at(index),
            f"Bombers {unit.id}",
            alone(unit, 3),
            script,
            RAID,
        )
        yield from on_call(squad, gate, 20)


# A mounted line's carriers are its front, as many as a line's tanks:
# with two, 4 of 29 that set out in three games lived through the
# break-in, the fewest of any line.
_CARRIERS: Final[int] = 4
# A carrier takes this many riders at most, however many it seats.
_RIDERS_MAX: Final[int] = 2
# The classes a rider is chosen for, the first the carrier's main crew.
_RIDER_AIMS: Final[tuple[Aim, ...]] = (Aim.VEHICLES, Aim.INFANTRY, Aim.BUILDINGS)
# Weights: the main crew, each other crew, a mixed one, a hero's. A
# carrier's crews together weigh about what its one crew did: more
# kinds of mounted line, not more of them.
_MOUNT_WEIGHT: Final[int] = 20
_OTHER_MOUNT_WEIGHT: Final[int] = 12
_MIXED_MOUNT_WEIGHT: Final[int] = 12
_HERO_MOUNT_WEIGHT: Final[int] = 10
# A carrier's squads are numbered ten apart, nine to a carrier.
_MOUNT_STEP: Final[int] = 10
_MOUNTS_MAX: Final[int] = 9


def _aboard(carrier: Unit, rider: Unit) -> Firepower:
    """What a rider fights with aboard a carrier.

    The weapon it gives a gunner vehicle (the vehicle's first where it
    has none for the rider); from inside an open-topped carrier, what
    its own weapons reach; on foot beside a closed one, all it has.
    """
    if carrier.has(Role.GUNNER):
        return carrier.mounts.get(rider.seat_mode) or carrier.firepower
    return rider.ranged if carrier.has(Role.OPEN_TOPPED) else rider.firepower


def _room(carrier: Unit, rider: Unit) -> int:
    """How many of a rider one carrier takes, the cap on riders kept."""
    return min(carrier.passengers // max(rider.size, 1), _RIDERS_MAX)


@dataclass(frozen=True, slots=True)
class _Mount:
    """A carrier's crew of riders, and how often it is raised."""

    riders: tuple[tuple[int, Unit, int], ...]
    weight: int
    max_teams: int = 2

    @property
    def label(self) -> str:
        """The riders' names, as the squad's name carries them."""
        return "+".join(unit.id for _, unit, _ in self.riders)


def _mounts(
    ctx: Context, country: Country, carrier: Unit, tier: int
) -> Iterator[_Mount]:
    """The crews a carrier rides out with, the main one first.

    At each tier from the carrier's own, the rider that hurts each class
    of target most aboard; then, where a carrier seats two, the first
    two of them side by side; and last the hero that does most aboard,
    with the main crew in the other carriers. MO's own AI seated a
    dozen kinds of infantry in an IFV, mixed crews in a Battle Fortress
    and its heroes in both.
    """
    fits = [u for u in ctx.fielded(country, TOP) if 0 < u.size <= carrier.size_limit]
    crews: list[Unit] = []
    for at in range(tier, TOP + 1):
        fielded = {u.id for u in ctx.fielded(country, at)}
        riders = [u for u in fits if u.id in fielded and INFANTRY.fits(u)]
        for aim in _RIDER_AIMS:
            best = max(
                riders,
                key=lambda u: (harm(_aboard(carrier, u), aim), -u.cost, u.id),
                default=None,
            )
            if (
                best is not None
                and best not in crews
                and harm(_aboard(carrier, best), aim) > 0
                and _room(carrier, best) > 0
            ):
                crews.append(best)
    for place, rider in enumerate(crews):
        seats = _CARRIERS * _room(carrier, rider)
        weight = _OTHER_MOUNT_WEIGHT if place else _MOUNT_WEIGHT
        yield _Mount(((seats, rider, SCREEN.rank),), weight)
    if not crews:
        return
    first = crews[0]
    if len(crews) > 1 and min(_room(carrier, u) for u in crews[:2]) > 1:
        half = _CARRIERS * _RIDERS_MAX // 2
        pair = tuple((half, unit, SCREEN.rank) for unit in crews[:2])
        yield _Mount(pair, _MIXED_MOUNT_WEIGHT)
    heroes = [u for u in fits if HERO.fits(u) and _room(carrier, u) > 0]
    hero = max(
        heroes,
        key=lambda u: (sum(harm(_aboard(carrier, u), aim) for aim in Aim), u.id),
        default=None,
    )
    escort = _CARRIERS * _room(carrier, first) - 1
    if hero is not None and escort > 0:
        riders = ((1, hero, HERO.rank), (escort, first, SCREEN.rank))
        yield _Mount(riders, _HERO_MOUNT_WEIGHT, max_teams=1)


def carriers(ctx: Context, country: Country) -> Iterator[Order]:
    """Each armed carrier rides out with the infantry that suit it.

    An IFV fights with its passenger's weapon and an open-topped carrier
    lets its squad fire from inside, so their riders stay aboard; any
    other carrier sets its riders down at the enemy's gate and fights
    beside them. The carriers lead as a front line does.
    """
    casts = country.front_casts
    aboard = Script(8700, "Mounted Line", sc.mounted(casts))
    on_foot = Script(8710, "Mechanised Line", sc.mechanised(casts))
    for index, (unit, tier) in enumerate(roster(ctx, country, _armed_carrier), start=1):
        stays = bool(unit.roles & {Role.GUNNER, Role.OPEN_TOPPED})
        mounts = tuple(_mounts(ctx, country, unit, tier))[:_MOUNTS_MAX]
        for place, mount in enumerate(mounts, start=1):
            crew = (
                Member(_CARRIERS, unit, FRONT.rank),
                *(Member(count, rider, rank) for count, rider, rank in mount.riders),
            )
            gate = unlocked(country, crew)
            if gate is None:
                continue
            squad = Squad(
                Series.CARRIER.at(_MOUNT_STEP * index + place),
                f"Mounted {unit.id} {mount.label}",
                crew,
                aboard if stays else on_foot,
                ASSAULT,
                max_teams=mount.max_teams,
            )
            yield from on_call(squad, gate, mount.weight)


_CHARGE_COURSES: Final[Mapping[Aim, Course]] = frozendict(
    {
        Aim.VEHICLES: Course(8801, (Quarry.VEHICLES, Quarry.STRUCTURES)),
        Aim.INFANTRY: Course(8802, (Quarry.INFANTRY, Quarry.VEHICLES)),
        Aim.BUILDINGS: Course(8803, (Quarry.FACTORIES, Quarry.STRUCTURES)),
    }
)
# A charge under the Iron Curtain is numbered this far past its own.
_CURTAIN_CODE_STEP: Final[int] = 100
# A charge spends about this much on its members, cheap ones in swarms.
_CHARGE_BUDGET: Final[int] = 2800
_CHARGE_COUNTS: Final[tuple[int, int]] = (2, 8)


def charges(ctx: Context, country: Country) -> Iterator[Order]:
    """Units that are spent on their target run straight at it.

    Walking bombs and units that must deploy to fire go for the class
    they hurt most, in a swarm their cost allows. With the Iron Curtain
    charged, the vehicles among them go in under it.
    """
    curtain = country.curtain
    casts = tuple(group for group in country.front_casts if group != curtain)
    low, high = _CHARGE_COUNTS
    for index, (unit, tier) in enumerate(roster(ctx, country, _charger), start=1):
        naval = unit.has(Role.NAVAL)
        factory = Factory.SHIPYARD if naval else Factory.BARRACKS
        gate = from_tier(country, tier, factory=factory)
        if gate is None:
            continue
        aim = aim_of(unit)
        course = _CHARGE_COURSES[aim]
        crew = alone(unit, min(max(_CHARGE_BUDGET // max(unit.cost, 1), low), high))
        script = Script(
            course.code, f"Charge vs {aim.value}", sc.charge(*course.quarries, casts)
        )
        squad = Squad(
            Series.CHARGE.at(index), f"Charge {unit.id}", crew, script, BEELINE
        )
        yield from on_call(squad, gate, 30)
        if curtain is None or naval or unit.kind is not Kind.VEHICLE:
            continue
        script = Script(
            course.code + _CURTAIN_CODE_STEP,
            f"Curtain Charge vs {aim.value}",
            sc.charge(*course.quarries, (*casts, curtain)),
        )
        squad = Squad(
            Series.CURTAIN_CHARGE.at(index),
            f"Curtain {unit.id}",
            crew,
            script,
            BEELINE,
            max_teams=1,
        )
        yield from on_call(squad, Gate(Condition.IRON_CURTAIN_CHARGED), 120)


def leftovers(ctx: Context, country: Country, used: frozenset[str]) -> Iterator[Order]:
    """A strike group for every combat unit no other squad fields.

    Runs after the other families, given the units their squads use, so
    a side's whole roster takes the field.
    """
    script = HUNTING.script(country.front_casts)
    unused = (
        (unit, tier)
        for unit, tier in roster(ctx, country, _fights_on_ground)
        if unit.id not in used
    )
    for index, (unit, tier) in enumerate(unused, start=1):
        gate = from_tier(country, tier)
        if gate is None:
            continue
        squad = Squad(
            Series.STRIKE_GROUP.at(index),
            f"Strike Group {unit.id}",
            alone(unit, 4),
            script,
            HUNTER,
        )
        yield from on_call(squad, gate, 25)
