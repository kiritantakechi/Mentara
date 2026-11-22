"""Units whose work is not their gun, and the company they keep.

Mind controllers that go out to take the enemy's army and stand among
the defences at home, infantry companies with a medic, effect
specialists beside the armour they serve, and a support column that
follows the house's forward units.
"""

from typing import Final
lazy from collections.abc import Iterator

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Country, Kind, Role, Unit
from mentara.mentalai.families._kit import (
    ASSAULT,
    ESCORT,
    HUNTER,
    OFF_GROUND,
    OTHER_JOBS,
    TIERS,
    WATCH,
    Context,
    Order,
    Series,
    alone,
    at_tier,
    from_tier,
    on_call,
    roster,
    variants_of,
)
from mentara.mentalai.families.assault import DIRECT, HUNTING
from mentara.mentalai.model import (
    Member,
    Squad,
)
from mentara.mentalai.scripts import Script, Target
from mentara.mentalai.slots import (
    AA,
    CONTROLLER,
    DETECTOR,
    DISABLER,
    FRONT,
    MEDIC,
    SCREEN,
    SUPPORT,
    TANK_HUNTER,
    Seats,
    fill,
)

# A psychic assault spends about this much on its controllers.
_PSYCHIC_BUDGET: Final[int] = 4500
_PSYCHIC_COUNTS: Final[tuple[int, int]] = (2, 4)
_PSYCHIC_ESCORT: Final[Seats] = ((SCREEN, 2), (AA, 1))
# A controller's post at home is numbered this far past its assault.
_POST_PLACE: Final[int] = 50


def psychics(ctx: Context, country: Country) -> Iterator[Order]:
    """Mind controllers take the enemy's army, and guard the defences.

    MO's own AI sent its Adepts, Elites and Masterminds out four at a
    time and stood them by its towers. An assault's controllers go for
    the vehicles first and what they take joins the team; a post's
    send what they take after the enemy.
    """
    assault = Script(8900, "Psychic Assault", sc.psychic_assault(country.front_casts))
    post = Script(8910, "Psychic Post", sc.post(Target.DEFENSES))
    low, high = _PSYCHIC_COUNTS
    controllers = roster(ctx, country, CONTROLLER.fits)
    for index, (unit, tier) in enumerate(controllers, start=1):
        gate = from_tier(country, tier)
        if gate is None:
            continue
        count = min(max(_PSYCHIC_BUDGET // max(unit.cost, 1), low), high)
        escort = fill(_PSYCHIC_ESCORT, ctx.fielded(country, tier), tier) or ()
        squad = Squad(
            Series.PSYCHIC.at(index),
            f"Psychic {unit.id}",
            (Member(count, unit, CONTROLLER.rank), *escort),
            assault,
            ASSAULT,
        )
        yield from on_call(squad, gate, 30)
        squad = Squad(
            Series.PSYCHIC.at(_POST_PLACE + index),
            f"Psychic Post {unit.id}",
            alone(unit, low),
            post,
            WATCH,
            max_teams=1,
        )
        yield from on_call(squad, gate, 15)


_COMPANY_SEATS: Final[Seats] = ((SCREEN, 4), (TANK_HUNTER, 3), (AA, 1), (MEDIC, 1))
_COMPANY_WEIGHT: Final[int] = 30


def companies(ctx: Context, country: Country) -> Iterator[Order]:
    """Infantry companies: riflemen, tank hunters, anti-air and a medic.

    The barracks alone builds one, so it sets out while the war factory
    still works through the teams ahead of it. It hunts the army rather
    than walk into a base's defences.
    """
    script = HUNTING.script(country.front_casts)
    for tier in TIERS:
        gate = at_tier(country, tier)
        if gate is None:
            continue
        infantry = tuple(
            u for u in ctx.fielded(country, tier) if u.kind is Kind.INFANTRY
        )
        for variant in variants_of(_COMPANY_SEATS, infantry, tier, required=(SCREEN,)):
            squad = Squad(
                variant.number(Series.COMPANY),
                variant.label("Company"),
                variant.crew,
                script,
                HUNTER,
            )
            yield from on_call(squad, gate, variant.weight(_COMPANY_WEIGHT))


def _serves_unarmed(unit: Unit) -> bool:
    """A ground unit whose weapon carries an effect and no damage."""
    return (
        unit.has(Role.EFFECT)
        and not unit.roles & (OTHER_JOBS | OFF_GROUND | {Role.GUN, Role.HEALER})
        and DISABLER.fits(unit)
    )


# A specialist rides with this much armour, and leaves the leading to
# it.
_SPECIALISTS: Final[int] = 2
_SPECIALIST_ARMOUR: Final[Seats] = ((FRONT, 4), (AA, 1))


def specialists(ctx: Context, country: Country) -> Iterator[Order]:
    """Each effect specialist beside the armour it serves.

    A painter, a freezer or a jammer with no gun of its own does
    nothing alone, and a line seats only the side's best one. MO paired
    each of its own with tanks, and so does this.
    """
    script = DIRECT.script(country.front_casts)
    for index, (unit, tier) in enumerate(
        roster(ctx, country, _serves_unarmed), start=1
    ):
        gate = from_tier(country, tier)
        armour = fill(
            _SPECIALIST_ARMOUR, ctx.fielded(country, tier), tier, required=(FRONT,)
        )
        if gate is None or armour is None:
            continue
        squad = Squad(
            Series.SPECIALIST.at(index),
            f"Support {unit.id}",
            (*armour, Member(_SPECIALISTS, unit, DISABLER.rank)),
            script,
            ASSAULT,
        )
        yield from on_call(squad, gate, 20)


_ESCORT_SEATS: Final[Seats] = ((AA, 2), (SUPPORT, 2), (DETECTOR, 1), (SCREEN, 2))
# A column's script is numbered by the list it joins, from here.
_ESCORT_CODE: Final[int] = 74000
_ESCORT_TIERS: Final[tuple[int, ...]] = (2, 3)


def escorts(ctx: Context, country: Country) -> Iterator[Order]:
    """A support column that joins the house's forward tanks.

    Anti-air, a medic or a mechanic, a detector and a screen: what a
    line seats one of at most. The column goes where the side's
    front-line tanks are and holds beside them, wherever they have got
    to, covering whichever team is there.
    """
    for tier in _ESCORT_TIERS:
        gate = at_tier(country, tier)
        units = ctx.fielded(country, tier)
        crew = fill(_ESCORT_SEATS, units, tier, required=(AA,))
        front = tuple(u.id for u in units if FRONT.fits(u))
        if gate is None or crew is None or not front:
            continue
        joined = ctx.target_list(front)
        script = Script(_ESCORT_CODE + joined, "Support Column", sc.escort(joined))
        squad = Squad(
            Series.ESCORT.at(tier),
            f"Support Column T{tier}",
            crew,
            script,
            ESCORT,
            max_teams=1,
        )
        yield from on_call(squad, gate, 25)
