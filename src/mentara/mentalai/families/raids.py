"""Fast single-role ground teams: raids, blitzes and feints."""

from dataclasses import dataclass
from typing import Final
lazy from collections.abc import Callable, Iterator

from mentara.mentalai import scripts as sc
from mentara.mentalai.families._kit import (
    FEINT,
    RAID,
    Context,
    Order,
    Series,
    at_tier,
    on_call,
    variants_of,
)
from mentara.mentalai.model import (
    Conduct,
    Squad,
)
from mentara.mentalai.scripts import Lines, Script
from mentara.mentalai.slots import (
    FAST,
    RAIDER,
    STEALTH,
    STRIKER,
    Seats,
)
lazy from mentara.mentalai.catalog import Country


@dataclass(frozen=True, slots=True)
class _RaidKind:
    """A fast single-role team, the tiers it runs at and its weight."""

    series: Series
    name: str
    code: int
    write: Callable[[], Lines]
    seats: Seats
    tiers: tuple[int, ...]
    weight: int
    doctrine: Conduct

    def script(self) -> Script:
        return Script(self.code, self.name, self.write())


_RAIDS: Final[tuple[_RaidKind, ...]] = (
    _RaidKind(
        Series.BLITZ,
        "Blitz",
        3000,
        sc.blitz,
        ((STRIKER, 4), (FAST, 2)),
        (2, 3),
        40,
        RAID,
    ),
    _RaidKind(Series.FEINT, "Feint", 3100, sc.feint, ((FAST, 4),), (1, 2), 30, FEINT),
    _RaidKind(
        Series.ECONOMY_RAID,
        "Economy Raid",
        3200,
        sc.economy_raid,
        ((RAIDER, 4),),
        (1, 2),
        40,
        RAID,
    ),
    _RaidKind(
        Series.POWER_RAID,
        "Power Raid",
        3300,
        sc.power_raid,
        ((STRIKER, 3), (FAST, 2)),
        (1, 2, 3),
        30,
        RAID,
    ),
    _RaidKind(
        Series.STEALTH_RAID,
        "Stealth Raid",
        3400,
        sc.economy_raid,
        ((STEALTH, 4),),
        (1, 2, 3),
        30,
        RAID,
    ),
)


def raids(ctx: Context, country: Country) -> Iterator[Order]:
    """Fast single-role teams: factory blitzes, feints and raids.

    A feint hits the chosen enemy's farthest buildings to pull the
    defence away from the lines; raids hit the economy and the power.
    """
    for raid in _RAIDS:
        script = raid.script()
        for tier in raid.tiers:
            gate = at_tier(country, tier)
            if gate is None:
                continue
            for variant in variants_of(raid.seats, ctx.fielded(country, tier), tier):
                squad = Squad(
                    variant.number(raid.series),
                    variant.label(raid.name),
                    variant.crew,
                    script,
                    raid.doctrine,
                )
                yield from on_call(squad, gate, variant.weight(raid.weight))
