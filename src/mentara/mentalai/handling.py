"""How the Mental AI's units handle their weapons.

Apart from what a team's script tells its members, Phobos has keys that
only the units of an AI house obey. The ones used here are read from the
rules, per weapon: no unit is named.
"""

from typing import Final
lazy from collections.abc import Iterator, Mapping

from mentara.mentalai.catalog import Kind, Role
lazy from mentara.mentalai.catalog import Catalog, Unit

__all__ = ["stand_offs"]

# The part of its range a unit keeps to fire from, in cells. Phobos
# counts a firer with too thin a band as unable to fire, and names
# one cell for a vehicle and two for infantry.
_BAND: Final[Mapping[Kind, float]] = frozendict({Kind.VEHICLE: 1.0, Kind.INFANTRY: 2.0})
# Giving ground takes time: a weapon that reloads in fewer frames only
# makes its unit dither.
_RELOAD_MIN: Final[float] = 60.0
# A weapon that reaches across the largest map (256 cells a side) has
# its target in range from anywhere, and keeps no distance.
_MAP_SPAN: Final[float] = 256.0
# These hold their ground: craft and ships move by other rules, a
# charger closes in, and a unit that digs in cannot move and fire.
_STANDS_FAST: Final[frozenset[Role]] = frozenset(
    {Role.AIRBORNE, Role.NAVAL, Role.CHARGER, Role.DIGS_IN, Role.PLAYER_VERSION}
)
_TOP_TIER: Final[int] = 3


def stand_offs(catalog: Catalog) -> Mapping[str, float]:
    """The distance each long gun keeps from its target as it reloads.

    Phobos `KeepRange` makes a firer treat a distance as its minimum
    range while its weapon rearms, so it backs away from a target that
    comes nearer. A gun earns one when the distance it would keep lies
    beyond the reach of every main battle tank the rules field, so its
    unit can stay out of the return fire it outranges, and when it
    reloads slowly enough to move meanwhile. Staged with three AI
    howitzers against three tanks that closed on them, the howitzers
    died in place without it and killed all three with it.

    Args:
        catalog: Units and countries from the rules.

    Returns:
        Weapon type to the distance it keeps, in cells, sorted by
        weapon. A weapon two units share keeps the shorter distance.
    """
    units = tuple(_fielded(catalog))
    reach = max((u.firepower.range for u in units if u.has(Role.MBT)), default=0.0)
    kept: dict[str, float] = {}
    for unit in units:
        band = _BAND.get(unit.kind)
        if band is None or unit.roles & _STANDS_FAST:
            continue
        for gun in unit.firepower.guns:
            keep = gun.range - band
            if (
                gun.reload < _RELOAD_MIN
                or gun.range >= _MAP_SPAN
                or keep <= max(reach, gun.minimum_range)
            ):
                continue
            for weapon in gun.types:
                kept[weapon] = min(keep, kept.get(weapon, keep))
    return frozendict(sorted(kept.items()))


def _fielded(catalog: Catalog) -> Iterator[Unit]:
    """Every unit some country fields, once."""
    seen: set[str] = set()
    for country in catalog.countries:
        for unit in catalog.fielded(country, _TOP_TIER):
            if unit.id not in seen:
                seen.add(unit.id)
                yield unit
