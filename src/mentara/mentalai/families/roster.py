"""Every unit its job.

Slots take a side's best units; these families give every other unit a
squad of its own, so a side fields its whole roster: each strike craft,
each hero, each unit that deploys forward, each bomb planter, each
carrier and each charger, and last a strike group for whatever no
squad has taken.
"""

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
    Aim,
    Context,
    Course,
    Order,
    Series,
    aim_of,
    alone,
    from_tier,
    on_call,
    roster,
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
    INFANTRY,
    SCREEN,
    Seats,
    fill,
)


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
            alone(unit, 2 if docked else 4),
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


def deployers(ctx: Context, country: Country) -> Iterator[Order]:
    """Units that unfold into something deploy by the enemy base."""
    script = Script(8500, "Forward Deploy", sc.forward_deploy())
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
            script,
            ASSAULT,
        )
        yield from on_call(squad, gate, 25)


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


_CARRIERS: Final[int] = 2
# A carrier takes this many riders at most, however many it seats.
_RIDERS_MAX: Final[int] = 2


def carriers(ctx: Context, country: Country) -> Iterator[Order]:
    """Each armed carrier rides out with the infantry that fit it best.

    An IFV fights with its passenger's weapon, an open-topped carrier
    lets its squad fire from inside: MO's IFV and carrier combinations.
    The carriers lead as a front line does.
    """
    script = Script(8700, "Mounted Line", sc.mounted(country.front_casts))
    for index, (unit, tier) in enumerate(roster(ctx, country, _armed_carrier), start=1):
        gate = from_tier(country, tier)
        infantry = tuple(
            u
            for u in ctx.fielded(country, tier)
            if u.kind is Kind.INFANTRY and u.size <= unit.size_limit
        )
        riders = fill(((SCREEN, 1),), infantry, tier) or fill(
            ((INFANTRY, 1),), infantry, tier
        )
        if gate is None or riders is None:
            continue
        seats = _CARRIERS * min(unit.passengers, _RIDERS_MAX)
        squad = Squad(
            Series.CARRIER.at(index),
            f"Mounted {unit.id}",
            (
                Member(_CARRIERS, unit, FRONT.rank),
                Member(seats, riders[-1].unit, SCREEN.rank),
            ),
            script,
            ASSAULT,
        )
        yield from on_call(squad, gate, 40)


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
