"""What the enemy does decides these.

Counters to the units it fields, strikes when it runs short of power
or credits, and a new MCV when it takes the yard.
"""

from typing import Final
lazy from collections.abc import Iterator

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Country, Role
from mentara.mentalai.families._kit import (
    BEELINE,
    COUNTER,
    Context,
    Notable,
    Order,
    Series,
    on_call,
)
from mentara.mentalai.families.defense import SKY_WATCH
from mentara.mentalai.model import (
    Call,
    Condition,
    Gate,
    Member,
    Squad,
)
from mentara.mentalai.scripts import Script
from mentara.mentalai.slots import (
    SCREEN,
    Seats,
    counter_slot,
    fill,
)

# One such unit is enough to answer when it costs this much.
_ONE_IS_ENOUGH_COST: Final[int] = 2000
_COUNTER_AMOUNT: Final[int] = 2
_COUNTER_CODE: Final[int] = 9500
# A counter's squads are numbered ten apart per armour, by tier.
_COUNTER_STEP: Final[int] = 10


def counters(ctx: Context, country: Country) -> Iterator[Order]:
    """Answer each notable enemy unit with what kills its armour best.

    A trigger per enemy unit waits until the house's chosen enemy owns
    some; it raises a squad shared by every unit of the same armour,
    which hunts them through an `[AITargetTypes]` list. Air is answered
    by anti-air holding the base.
    """
    made: set[int] = set()
    for index, notable in enumerate(ctx.notable):
        place = _COUNTER_STEP * ctx.keys.index(notable.key) + notable.tier
        number = Series.COUNTER.at(place)
        if number not in made:
            squad = _counter_squad(ctx, country, notable, number)
            if squad is None:
                continue
            made.add(number)
            yield squad
        unit = notable.unit
        one = unit.has(Role.HERO) or unit.cost >= _ONE_IS_ENOUGH_COST
        yield Call(
            Series.COUNTER_CALL.at(index),
            f"Counter {unit.id}",
            squad=number,
            gate=Gate.enemy_owns(unit.id, 1 if one else _COUNTER_AMOUNT),
            weight=20,
        )


def _counter_squad(
    ctx: Context, country: Country, notable: Notable, number: int
) -> Squad | None:
    key, tier = notable.key, notable.tier
    slot = counter_slot(key.armor, airborne=key.airborne, naval=key.naval)
    # Hunters only: on a Phobos attack line the highest-rated member
    # picks the targets, and an escort that outranked the hunters found
    # none for them (an anti-air leader sees no ground target at all).
    seats: Seats = ((slot, 5),)
    if key.airborne:
        seats = ((slot, 4), (SCREEN, 1))
    elif key.naval:
        seats = ((slot, 4),)
    crew = fill(seats, ctx.fielded(country, tier), tier, required=(slot,))
    if crew is None:
        return None
    if key.airborne:
        script = SKY_WATCH
    else:
        hunted = tuple(n.unit.id for n in ctx.notable if n.key == key)
        target_list = ctx.target_list(hunted)
        script = Script(
            _COUNTER_CODE + target_list,
            f"Counter {key.armor}",
            sc.counter_hunt(target_list),
        )
    label = f"Counter {key.armor}{' air' if key.airborne else ''} T{tier}"
    return Squad(number, label, crew, script, COUNTER)


# An enemy this short of credits cannot rebuild what it loses.
_BROKE_CREDITS: Final[int] = 500
# One this short feels every harvester it loses at once.
_LEAN_CREDITS: Final[int] = 2000


def opportunities(_ctx: Context, _country: Country) -> Iterator[Order]:
    """Strike when the chosen enemy is weak, whatever the tier.

    With little power to spare, a power raid tips it into a blackout;
    when it drains more than it makes, its defences are off line and a
    line goes in with a factory blitz beside it. Short of credits, its
    harvesters are raided; nearly out, hunting lines go after what it
    has left. The squads are the country's own lines, blitzes and
    raids; a call whose squad the country lacks is dropped.
    """
    strained = Gate(Condition.ENEMY_POWER_LOW)
    blackout = Gate(Condition.ENEMY_POWER_SHORT)
    lean = Gate.enemy_credits_under(_LEAN_CREDITS)
    broke = Gate.enemy_credits_under(_BROKE_CREDITS)
    for tier in (1, 2):
        # No blitz forms at tier 1: a feint goes in beside the line.
        beside = Series.BLITZ if tier > 1 else Series.FEINT
        yield Call(
            Series.GRID.at(tier),
            f"Grid Strike T{tier}",
            squad=Series.POWER_RAID.variant(tier),
            gate=strained,
            weight=80,
        )
        yield Call(
            Series.STARVE.at(tier),
            f"Starve T{tier}",
            squad=Series.ECONOMY_RAID.variant(tier),
            gate=lean,
            weight=60,
        )
        yield Call(
            Series.BLACKOUT.at(tier),
            f"Blackout Assault T{tier}",
            squad=Series.LINE.variant(tier),
            gate=blackout,
            weight=150,
            support=beside.variant(tier),
        )
        yield Call(
            Series.FINISH.at(tier),
            f"Finishing Hunt T{tier}",
            squad=Series.HUNT.variant(tier),
            gate=broke,
            weight=100,
            support=Series.ECONOMY_RAID.variant(tier),
        )


_MCV_RANK: Final[int] = 1


def redeploy(ctx: Context, country: Country) -> Iterator[Order]:
    """A new MCV when the construction yard is lost."""
    if country.mcv is None or country.construction_yard is None:
        return
    mcv = ctx.catalog.units[country.mcv.lower()]
    script = Script(8000, "Redeploy MCV", sc.redeploy())
    squad = Squad(
        Series.YARD.at(),
        script.name,
        (Member(1, mcv, _MCV_RANK),),
        script,
        BEELINE,
        max_teams=1,
    )
    yield from on_call(squad, Gate.house_lacks(country.construction_yard), 500)
