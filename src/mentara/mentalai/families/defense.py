"""Holding the base: watch, posts, patrol, tech guard and sky guard."""

from typing import Final
lazy from collections.abc import Iterator, Mapping

from mentara.mentalai import scripts as sc
from mentara.mentalai.families._kit import (
    GUARD,
    TIERS,
    WATCH,
    Context,
    Order,
    Series,
    answering,
    at_tier,
    from_tier,
    on_call,
)
from mentara.mentalai.model import (
    Gate,
    Squad,
)
from mentara.mentalai.scripts import Script, Target
from mentara.mentalai.slots import (
    AA,
    FRONT,
    SCREEN,
    SKY_GUARD,
    Seats,
    fill,
)
lazy from mentara.mentalai.catalog import Country

# Anti-air holding the base: against an enemy airfield, against enemy
# aircraft, and by interceptors.
SKY_WATCH: Final[Script] = Script(5200, "Sky Guard", sc.stand_guard())


def defense(ctx: Context, country: Country) -> Iterator[Order]:
    """Base watch, patrol, tech guard and anti-air against enemy air."""
    yield from _base_watch(ctx, country)
    yield from _posts(ctx, country)
    yield from _patrol(ctx, country)
    yield from _tech_guard(ctx, country)
    yield from _sky_guard(ctx, country)


_WATCH_SEATS: Final[Seats] = ((FRONT, 2), (SCREEN, 2), (AA, 2))


def _base_watch(ctx: Context, country: Country) -> Iterator[Order]:
    """A watch at each tier, casting the home superweapons."""
    script = Script(5000, "Base Watch", sc.watch(country.base_casts))
    for tier in TIERS:
        gate = at_tier(country, tier)
        crew = fill(_WATCH_SEATS, ctx.fielded(country, tier), tier)
        if gate is None or crew is None:
            continue
        squad = Squad(Series.WATCH.at(tier), f"Base Watch T{tier}", crew, script, WATCH)
        yield from on_call(squad, gate, 60)


# The classes of own building a watch is posted at, and their names.
_POSTS: Final[Mapping[Target, str]] = frozendict(
    {
        Target.DEFENSES: "Defence",
        Target.FACTORIES: "Factory",
        Target.POWER: "Power",
    }
)
_POST_CODE: Final[int] = 5400
# A class's posts are numbered ten apart, by tier.
_POST_STEP: Final[int] = 10


def _posts(ctx: Context, country: Country) -> Iterator[Order]:
    """A watch's crew posted beside the defences, factories or power.

    The base watch stands where the house gathers; MO's own AI kept
    its defenders at its turrets and walked them between its buildings
    (167 of its teams). These are base-defence teams too, so the engine
    keeps as many posts and watches together as it kept watches.
    """
    for tier in TIERS:
        gate = at_tier(country, tier)
        crew = fill(_WATCH_SEATS, ctx.fielded(country, tier), tier)
        if gate is None or crew is None:
            continue
        for place, (target, name) in enumerate(_POSTS.items(), start=1):
            script = Script(_POST_CODE + target, f"{name} Post", sc.post(target))
            squad = Squad(
                Series.WATCH.at(_POST_STEP * place + tier),
                f"{name} Post T{tier}",
                crew,
                script,
                WATCH,
                max_teams=1,
            )
            yield from on_call(squad, gate, 30)


def _patrol(ctx: Context, country: Country) -> Iterator[Order]:
    gate = from_tier(country, 2)
    crew = fill(((SCREEN, 2), (FRONT, 1), (AA, 1)), ctx.fielded(country, 2), 2)
    if gate is None or crew is None:
        return
    script = Script(5100, "Patrol", sc.patrol())
    squad = Squad(Series.PATROL.at(), "Patrol", crew, script, GUARD, max_teams=1)
    yield from on_call(squad, gate, 15)


def _tech_guard(ctx: Context, country: Country) -> Iterator[Order]:
    """A guard for tech the house has taken.

    Tier-1 units, which the tech building it waits for does not put
    beyond reach.
    """
    crew = fill(((SCREEN, 2), (FRONT, 1)), ctx.fielded(country, 1), 1)
    if crew is None:
        return
    script = Script(5300, "Tech Guard", sc.post(Target.TECH))
    squad = Squad(
        Series.TECH_GUARD.at(), "Tech Guard", crew, script, GUARD, max_teams=1
    )
    gates = (
        (f"Tech Guard {building}", Gate.house_owns(building))
        for building in ctx.catalog.tech_buildings
    )
    yield from answering(squad, gates, 10)


def _sky_guard(ctx: Context, country: Country) -> Iterator[Order]:
    """Anti-air that answers each kind of enemy airfield."""
    seats: Seats = ((SKY_GUARD, 4), (SCREEN, 1))
    crew = fill(seats, ctx.fielded(country, 2), 2, required=(SKY_GUARD,))
    if crew is None:
        return
    squad = Squad(Series.SKY_GUARD.at(), "Sky Guard", crew, SKY_WATCH, GUARD)
    gates = (
        (f"Sky Guard vs {building}", Gate.enemy_owns(building))
        for building in ctx.airfields
    )
    yield from answering(squad, gates, 40)
