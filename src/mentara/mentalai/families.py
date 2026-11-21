"""The Mental AI's families of teams: what each country fields and when.

Each family reads a country's units, buildings and superweapons and
yields squads (a TaskForce with its TeamType) and the triggers that call
them. No unit, building or superweapon is named: every choice follows
from the rules data, so the same families serve every side.

Numbers are four digits, the family and then the tier or variant
(`0102` is the tier-2 direct line): see `overlays/README.md`.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Final

from mentara.mentalai import scripts as sc
from mentara.mentalai.catalog import Catalog, Country, Factory, Kind, Role, Unit
from mentara.mentalai.model import Call, Comparison, Condition, Gate, Squad
from mentara.mentalai.scripts import Lines, Script, make_script
from mentara.mentalai.slots import (
    AA,
    AIR,
    ARTILLERY,
    DETECTOR,
    ENGINEER,
    FAST,
    FRONT,
    HERO,
    HIJACKER,
    INFANTRY,
    NAVAL_AA,
    NAVAL_ARTILLERY,
    NAVAL_FRONT,
    NAVAL_HUNTER,
    OCCUPIER,
    RAIDER,
    SCREEN,
    SIEGE,
    SKY_GUARD,
    SPY,
    STEALTH,
    STRIKER,
    SUPPORT,
    TRANSPORT,
    Filled,
    Slot,
    counter_slot,
    fill,
)

__all__ = ["FAMILIES", "Context", "Family", "Order", "country_code"]

type Order = Squad | Call
type Family = Callable[[Context, Country], Iterator[Order]]
type _Slots = tuple[tuple[Slot, int], ...]

_TIERS: Final[tuple[int, ...]] = (1, 2, 3)
_TOP: Final[int] = 3
# Naming only: MO's two-letter country codes and labels (see README).
_COUNTRY_NAMES: Final[dict[str, tuple[str, str]]] = {
    "unitedstates": ("US", "USA"),
    "europeans": ("EU", "Euro"),
    "pacific": ("PA", "Pacific"),
    "ussr": ("RU", "Russia"),
    "latin": ("LA", "Latin"),
    "chinese": ("CH", "China"),
    "psicorps": ("PC", "PsiCorps"),
    "scorpioncell": ("SC", "Scorpion"),
    "headquaters": ("HQ", "HQ"),
    "guild1": ("HA", "Haihead"),
    "guild2": ("CO", "Coronia"),
    "guild3": ("LB", "Last Bastion"),
}
# An enemy unit is worth a counter when it costs this much, flies,
# shells from the sea, or is a hero.
_NOTABLE_COST: Final[int] = 1000
# One such unit is enough to answer when it costs this much.
_ONE_IS_ENOUGH_COST: Final[int] = 2000
_COUNTER_AMOUNT: Final[int] = 2
# A boost assault needs this many members the buff reaches.
_BOOST_MEMBERS_MIN: Final[int] = 4
_SUPERWEAPON_SUFFIX: Final[str] = "special"


def country_code(country: Country) -> str:
    """A country's two-letter code (`overlays/README.md`)."""
    return _COUNTRY_NAMES.get(country.id.lower(), (country.id[:2].upper(), ""))[0]


def country_label(country: Country) -> str:
    """A country's display label."""
    return _COUNTRY_NAMES.get(country.id.lower(), ("", country.id))[1]


@dataclass(frozen=True, slots=True)
class _Key:
    """What a counter answers: an armour, in the air, at sea or not."""

    armor: str
    airborne: bool
    naval: bool


@dataclass(frozen=True, slots=True)
class _Notable:
    unit: Unit
    tier: int
    key: _Key


@dataclass(slots=True)
class Context:
    """What every family shares: the catalog and the rules-side lists.

    Attributes:
        catalog: Units and countries.
        notable: Enemy units worth a counter, from every country.
        keys: The counter keys, in index order.
        airfields: Every country's aircraft factories.
        superweapon_buildings: Every country's superweapon buildings.
        target_lists: Phobos `[AITargetTypes]` lists, registered in
            index order.
    """

    catalog: Catalog
    notable: tuple[_Notable, ...]
    keys: tuple[_Key, ...]
    airfields: tuple[str, ...]
    superweapon_buildings: tuple[str, ...]
    target_lists: list[tuple[str, ...]] = field(default_factory=list)

    @classmethod
    def build(cls, catalog: Catalog) -> Context:
        """Gather the cross-country lists once.

        Args:
            catalog: Units and countries.

        Returns:
            The context.
        """
        notable = _notable_units(catalog)
        keys = tuple(sorted({n.key for n in notable}, key=_key_order))
        return cls(
            catalog=catalog,
            notable=notable,
            keys=keys,
            airfields=_unique(b for c in catalog.countries for b in c.airfields),
            superweapon_buildings=_unique(
                b for c in catalog.countries for b in c.superweapon_buildings
            ),
        )

    def target_list(self, units: tuple[str, ...]) -> int:
        """The index of an `[AITargetTypes]` list, added if new."""
        if units not in self.target_lists:
            self.target_lists.append(units)
        return self.target_lists.index(units)

    def fielded(self, country: Country, tier: int) -> tuple[Unit, ...]:
        """The units a country fields by a tier."""
        return self.catalog.fielded(country, tier)


def _unique(names: Iterator[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def _key_order(key: _Key) -> tuple[bool, bool, str]:
    return (key.airborne, key.naval, key.armor)


def _notable_units(catalog: Catalog) -> tuple[_Notable, ...]:
    """Enemy units worth a counter: costly, flying, shelling or heroic.

    A unit several countries field takes the lowest tier any of them
    reaches it at.
    """
    tiers: dict[str, int] = {}
    for country in catalog.countries:
        for name, tier in country.units.items():
            unit = catalog.units.get(name)
            if unit is None or not _is_notable(unit):
                continue
            tiers[unit.id] = min(tiers.get(unit.id, tier), tier)
    return tuple(
        _Notable(
            unit=unit,
            tier=tiers[unit.id],
            key=_Key(
                armor=unit.armor,
                airborne=unit.has(Role.AIRBORNE),
                naval=unit.has(Role.NAVAL),
            ),
        )
        for unit in catalog.units.values()
        if unit.id in tiers
    )


def _is_notable(unit: Unit) -> bool:
    jobs = {Role.HARVESTER, Role.MCV, Role.DEPLOYER, Role.ENGINEER, Role.INFILTRATOR}
    if unit.roles & jobs or not unit.roles & {Role.GUN, Role.AA}:
        return False
    return (
        unit.cost >= _NOTABLE_COST
        or unit.has(Role.HERO)
        or unit.has(Role.AIRBORNE, Role.GUN)
        or unit.has(Role.NAVAL, Role.ARTILLERY)
    )


# --- Gates -----------------------------------------------------------


def _owns(building: str) -> Gate:
    return Gate(Condition.HOUSE_OWNS, building, 1, Comparison.AT_LEAST)


def _tier_gate(country: Country, tier: int) -> Gate | None:
    """Hold a tier back: the AI skips unit prerequisites.

    Tier 1 runs until the country owns its tier-2 building (the one
    that unlocks most of that tier); higher tiers once it owns theirs.
    """
    if tier == 1:
        upper = country.gates.get(2)
        if upper is None:
            return None
        return Gate(Condition.HOUSE_OWNS, upper, 1, Comparison.LESS)
    building = country.gates.get(tier)
    return None if building is None else _owns(building)


def _unlock_gate(country: Country, tier: int) -> Gate | None:
    """Wait for the building a tier unlocks at; keep running after."""
    if tier == 1:
        barracks = country.factories.get(Factory.BARRACKS)
        return None if barracks is None else _owns(barracks)
    building = country.gates.get(tier)
    return None if building is None else _owns(building)


# --- Helpers ---------------------------------------------------------


def _script(country: Country, code: int, name: str, lines: Lines) -> Script:
    return make_script(code, f"Mental {name}", lines, country_code(country))


def _squad(  # noqa: PLR0913 - every squad flag has its own family
    number: int,
    label: str,
    filled: Filled,
    script: Script,
    *,
    max_teams: int = 2,
    base_defense: bool = False,
    recruiter: bool = False,
    enemy_only: bool = False,
    priority: int = 5,
) -> Squad:
    members, ranks = filled
    return Squad(
        number=number,
        label=label,
        members=members,
        script=script,
        ranks=ranks,
        max_teams=max_teams,
        priority=priority,
        base_defense=base_defense,
        recruiter=recruiter,
        enemy_only=enemy_only,
    )


def _vehicles(units: tuple[Unit, ...]) -> tuple[Unit, ...]:
    return tuple(u for u in units if u.kind is Kind.VEHICLE)


def _strip(name: str) -> str:
    """A superweapon's ID as a label: OverchargeSpecial, Overcharge."""
    if name.lower().endswith(_SUPERWEAPON_SUFFIX):
        return name[: -len(_SUPERWEAPON_SUFFIX)]
    return name


# --- Assault lines ---------------------------------------------------

_LINE_SLOTS: Final[dict[int, _Slots]] = {
    1: ((FRONT, 4), (SCREEN, 3), (AA, 1), (DETECTOR, 1)),
    2: (
        (FRONT, 4),
        (ARTILLERY, 2),
        (SCREEN, 2),
        (AA, 2),
        (SUPPORT, 1),
        (DETECTOR, 1),
    ),
    3: (
        (FRONT, 4),
        (ARTILLERY, 2),
        (HERO, 1),
        (SCREEN, 2),
        (AA, 2),
        (SUPPORT, 1),
    ),
}
# Direct, flank and hunt lines share members; each has its own weight.
_LINE_KINDS: Final[tuple[tuple[int, str, int, tuple[int, int, int]], ...]] = (
    (1, "Line", 1000, (100, 120, 150)),
    (2, "Flank", 1100, (50, 60, 80)),
    (3, "Hunt", 1200, (40, 50, 60)),
)
_LINE_AIR: Final[int] = 4
_LINE_AIR_WEIGHTS: Final[tuple[int, int, int]] = (0, 50, 60)
_AIR: Final[int] = 13


def lines(ctx: Context, country: Country) -> Iterator[Order]:
    """Combined-arms lines: direct, flanking and army-hunting.

    The members are the same; the scripts differ. From tier 2 a second
    trigger launches the line with the tier's air strike as Team2.
    """
    casts = country.front_casts
    builders: dict[int, Callable[[tuple[int, ...]], Lines]] = {
        1: sc.line_direct,
        2: sc.line_flank,
        3: sc.line_hunt,
    }
    for tier in _TIERS:
        gate = _tier_gate(country, tier)
        filled = fill(
            _LINE_SLOTS[tier], ctx.fielded(country, tier), tier, required=("front",)
        )
        if gate is None or filled is None:
            continue
        for code, kind, script_code, weights in _LINE_KINDS:
            number = code * 100 + tier
            script = _script(country, script_code, kind, builders[code](casts))
            yield _squad(
                number,
                f"{kind} T{tier}",
                filled,
                script,
                max_teams=3,
                recruiter=True,
                enemy_only=code == 2,  # noqa: PLR2004 - the flank
            )
            yield Call(number, f"{kind} T{tier}", number, gate, weights[tier - 1])
        if _LINE_AIR_WEIGHTS[tier - 1]:
            yield Call(
                _LINE_AIR * 100 + tier,
                f"Line + Air T{tier}",
                100 + tier,
                gate,
                _LINE_AIR_WEIGHTS[tier - 1],
                support=_AIR * 100 + tier,
            )


_SIEGE: Final[int] = 5
_SIEGE_AIR: Final[int] = 6


def sieges(ctx: Context, country: Country) -> Iterator[Order]:
    """Artillery that out-damages buildings, with tanks and a screen."""
    slots: _Slots = ((SIEGE, 3), (FRONT, 2), (SCREEN, 2), (AA, 1))
    for tier in (2, 3):
        gate = _tier_gate(country, tier)
        filled = fill(slots, ctx.fielded(country, tier), tier, required=("siege",))
        if gate is None or filled is None:
            continue
        number = _SIEGE * 100 + tier
        script = _script(country, 2000, "Siege", sc.siege(country.front_casts))
        yield _squad(number, f"Siege T{tier}", filled, script, recruiter=True)
        yield Call(number, f"Siege T{tier}", number, gate, 70)
        yield Call(
            _SIEGE_AIR * 100 + tier,
            f"Siege + Air T{tier}",
            number,
            gate,
            40,
            support=_AIR * 100 + tier,
        )


def superweapon_snipes(ctx: Context, country: Country) -> Iterator[Order]:
    """When the enemy owns a superweapon, a siege group goes for it."""
    slots: _Slots = ((FRONT, 3), (SIEGE, 2), (AA, 1))
    filled = fill(slots, ctx.fielded(country, _TOP), _TOP, required=("front",))
    if filled is None:
        return
    script = _script(
        country, 2100, "Superweapon Snipe", sc.superweapon_snipe(country.front_casts)
    )
    yield _squad(1900, "Superweapon Snipe", filled, script, recruiter=True)
    for index, building in enumerate(ctx.superweapon_buildings):
        gate = Gate(Condition.ENEMY_OWNS, building, 1, Comparison.AT_LEAST)
        yield Call(1900 + index + 1, f"Snipe {building}", 1900, gate, 60)


# --- Raids and feints ------------------------------------------------

_RAIDS: Final[tuple[tuple[int, str, int, _Slots, tuple[int, ...], int, bool], ...]] = (
    (7, "Blitz", 3000, ((STRIKER, 4), (FAST, 2)), (2, 3), 40, False),
    (8, "Feint", 3100, ((FAST, 4),), (1, 2), 30, True),
    (9, "Economy Raid", 3200, ((RAIDER, 4),), (1, 2), 40, False),
    (10, "Power Raid", 3300, ((STRIKER, 3), (FAST, 2)), (2, 3), 30, False),
    (11, "Stealth Raid", 3400, ((STEALTH, 4),), (1, 2, 3), 30, False),
)
_RAID_SCRIPTS: Final[dict[int, Callable[[], Lines]]] = {
    7: sc.blitz,
    8: sc.feint,
    9: sc.economy_raid,
    10: sc.power_raid,
    11: sc.economy_raid,
}


def raids(ctx: Context, country: Country) -> Iterator[Order]:
    """Fast single-role teams: factory blitzes, feints and raids.

    A feint hits the chosen enemy's farthest buildings to pull the
    defence away from the lines; raids hit the economy and the power.
    """
    for code, name, script_code, slots, tiers, weight, enemy_only in _RAIDS:
        script = _script(country, script_code, name, _RAID_SCRIPTS[code]())
        for tier in tiers:
            gate = _tier_gate(country, tier)
            filled = fill(slots, ctx.fielded(country, tier), tier)
            if gate is None or filled is None:
                continue
            number = code * 100 + tier
            yield _squad(
                number,
                f"{name} T{tier}",
                filled,
                script,
                recruiter=True,
                enemy_only=enemy_only,
            )
            yield Call(number, f"{name} T{tier}", number, gate, weight)


# --- Air -------------------------------------------------------------

_AIR_QUARRIES: Final[dict[str, tuple[int, tuple[int, ...]]]] = {
    "vehicles": (4001, (sc.VEHICLES, sc.DEFENSES)),
    "infantry": (4002, (sc.INFANTRY, sc.OCCUPIED)),
    "defenses": (4003, (sc.DEFENSES, sc.STRUCTURES)),
}


def air_strikes(ctx: Context, country: Country) -> Iterator[Order]:
    """Strike craft on the class they hurt most.

    Airfield-bound craft share one airfield's pads across the tiers,
    one team per tier, and are not cloned: an aircraft with no free pad
    is never built, and the AI abandons it.
    """
    tiers = (2, 3)
    for tier in tiers:
        gate = _tier_gate(country, tier)
        filled = fill(((AIR, 4),), ctx.fielded(country, tier), tier)
        if gate is None or filled is None:
            continue
        members, ranks = filled
        unit = ctx.catalog.units[members[0][1].lower()]
        max_teams, unique = 3, frozenset[str]()
        if unit.has(Role.DOCKED):
            share = country.docks // len(tiers)
            if share <= 0:
                continue
            members = tuple((min(n, share), u) for n, u in members)
            max_teams, unique = 1, frozenset(u for _, u in members)
        fire = unit.firepower
        aim = max(
            ("vehicles", fire.vehicle),
            ("infantry", fire.infantry),
            ("defenses", fire.building),
            key=lambda pair: pair[1],
        )[0]
        code, quarries = _AIR_QUARRIES[aim]
        script = make_script(
            code, f"Mental Air Strike vs {aim}", sc.air_strike(*quarries), ""
        )
        number = _AIR * 100 + tier
        squad = _squad(number, f"Air Strike T{tier}", (members, ranks), script)
        yield Squad(
            number=squad.number,
            label=squad.label,
            members=squad.members,
            script=squad.script,
            ranks=squad.ranks,
            max_teams=max_teams,
            unique=unique,
        )
        yield Call(number, f"Air Strike T{tier}", number, gate, 50)


# --- Defence ---------------------------------------------------------


def defense(ctx: Context, country: Country) -> Iterator[Order]:
    """Base watch, patrols, tech guards and anti-air against enemy air.

    The watch casts the superweapons that belong at home (harvester
    deliveries) each round. The sky guard answers an enemy airfield.
    """
    watch = _script(country, 5000, "Base Watch", sc.watch(country.base_casts))
    for tier in _TIERS:
        gate = _tier_gate(country, tier)
        slots: _Slots = ((FRONT, 2), (SCREEN, 2), (AA, 2))
        filled = fill(slots, ctx.fielded(country, tier), tier)
        if gate is None or filled is None:
            continue
        number = 1500 + tier
        yield _squad(number, f"Base Watch T{tier}", filled, watch, base_defense=True)
        yield Call(number, f"Base Watch T{tier}", number, gate, 60)
    upper = _unlock_gate(country, 2)
    mid = ctx.fielded(country, 2)
    guards: tuple[tuple[int, str, int, Lines, _Slots, int], ...] = (
        (1600, "Patrol", 5100, sc.patrol(), ((SCREEN, 2), (FRONT, 1), (AA, 1)), 15),
        (1700, "Tech Guard", 5300, sc.tech_guard(), ((SCREEN, 2), (FRONT, 1)), 10),
    )
    for number, name, code, script_lines, slots, weight in guards:
        filled = fill(slots, mid, 2)
        if upper is None or filled is None:
            continue
        script = _script(country, code, name, script_lines)
        yield _squad(number, name, filled, script, max_teams=1)
        yield Call(number, name, number, upper, weight)
    filled = fill(((SKY_GUARD, 4), (SCREEN, 1)), mid, 2, required=("sky guard",))
    if filled is None:
        return
    guard = _script(country, 5200, "Sky Guard", sc.watch(()))
    yield _squad(1800, "Sky Guard", filled, guard)
    for index, building in enumerate(ctx.airfields):
        gate = Gate(Condition.ENEMY_OWNS, building, 1, Comparison.AT_LEAST)
        yield Call(1800 + index + 1, f"Sky Guard vs {building}", 1800, gate, 40)


# --- Occupation ------------------------------------------------------


def occupation(ctx: Context, country: Country) -> Iterator[Order]:
    """Garrisons, bunkers, bio reactors, tech capture and hijackers."""
    low = ctx.fielded(country, 1)
    barracks = _unlock_gate(country, 1)
    plans: tuple[tuple[int, str, int, Lines, _Slots, Gate | None, int], ...] = (
        (
            2000,
            "Capture Tech",
            6000,
            sc.capture_tech(),
            ((ENGINEER, 2),),
            barracks,
            20,
        ),
        (
            2100,
            "Garrison",
            6100,
            sc.garrison(),
            ((OCCUPIER, 5),),
            Gate(Condition.ALWAYS),
            20,
        ),
        (
            2200,
            "Battle Bunker",
            6200,
            sc.occupy_bunker(),
            ((OCCUPIER, 4),),
            _owns(country.battle_bunker) if country.battle_bunker else None,
            25,
        ),
        (
            2300,
            "Tank Bunker",
            6300,
            sc.tank_bunker(),
            ((FRONT, 2),),
            _owns(country.tank_bunker) if country.tank_bunker else None,
            25,
        ),
        (
            2400,
            "Bio Reactor",
            6400,
            sc.absorb(),
            ((INFANTRY, 5),),
            _owns(country.absorber) if country.absorber else None,
            20,
        ),
    )
    for number, name, code, script_lines, slots, gate, weight in plans:
        filled = fill(slots, low, 1)
        if gate is None or filled is None:
            continue
        script = _script(country, code, name, script_lines)
        yield _squad(number, name, filled, script, max_teams=1)
        yield Call(number, name, number, gate, weight)
    yield from _agents(
        ctx,
        country,
        2500,
        "Hijack",
        slots=((HIJACKER, 3),),
        code=6500,
        script_lines=sc.hijack(),
        weight=15,
    )


def _agents(  # noqa: PLR0913 - one squad and call per agent kind
    ctx: Context,
    country: Country,
    number: int,
    name: str,
    *,
    slots: _Slots,
    code: int,
    script_lines: Lines,
    weight: int,
) -> Iterator[Order]:
    """An agent squad, gated on the building its agent unlocks at."""
    filled = fill(slots, ctx.fielded(country, _TOP), _TOP)
    if filled is None:
        return
    tier = max(country.units[u.lower()] for _, u in filled[0])
    gate = _unlock_gate(country, tier)
    if gate is None:
        return
    script = _script(country, code, name, script_lines)
    yield _squad(number, name, filled, script, max_teams=1)
    yield Call(number, name, number, gate, weight)


# --- Infiltration ----------------------------------------------------

_SPY_TARGETS: Final[tuple[tuple[int, str], ...]] = (
    (sc.T_POWER, "Power"),
    (sc.T_RADAR, "Radar"),
    (sc.T_VEHICLE_FACTORY, "War Factory"),
    (sc.T_BARRACKS, "Barracks"),
    (sc.T_REFINERY, "Refinery"),
    (sc.T_SUPERWEAPON, "Superweapon"),
    (sc.T_TECH_LAB, "Tech Lab"),
)
_DROP_TARGETS: Final[tuple[tuple[int, str], ...]] = (
    (sc.T_POWER, "Power"),
    (sc.T_FACTORIES, "Factory"),
    (sc.T_CONSTRUCTION_YARD, "Yard"),
)


def infiltration(ctx: Context, country: Country) -> Iterator[Order]:
    """Spies on every class of building, and engineer drops.

    A drop loads engineers into the team's transport (Phobos 10103),
    drives next to the target, unloads and captures it.
    """
    for index, (target, name) in enumerate(_SPY_TARGETS, start=1):
        yield from _agents(
            ctx,
            country,
            2600 + index,
            f"Spy vs {name}",
            slots=((SPY, 1),),
            code=7000 + target,
            script_lines=sc.infiltrate(target),
            weight=6,
        )
    filled = _drop_team(ctx, country)
    gate = _unlock_gate(country, 2)
    if filled is None or gate is None:
        return
    for index, (target, name) in enumerate(_DROP_TARGETS, start=1):
        number = 2700 + index
        script = _script(country, 7100 + target, f"Drop vs {name}", sc.drop(target))
        yield _squad(number, f"Engineer Drop vs {name}", filled, script, max_teams=1)
        yield Call(number, f"Engineer Drop vs {name}", number, gate, 10)


def _drop_team(ctx: Context, country: Country) -> Filled | None:
    """A transport and two engineers that fit in it."""
    units = ctx.fielded(country, _TOP)
    engineers = fill(((ENGINEER, 2),), units, _TOP)
    if engineers is None:
        return None
    engineer = ctx.catalog.units[engineers[0][0][1].lower()]
    carriers = tuple(
        u
        for u in units
        if u.size_limit >= engineer.size and u.passengers >= 2  # noqa: PLR2004
    )
    transport = fill(((TRANSPORT, 1),), carriers, _TOP)
    if transport is None:
        return None
    return (
        transport[0] + engineers[0],
        {**transport[1], **engineers[1]},
    )


# --- Naval -----------------------------------------------------------

_NAVAL: Final[tuple[tuple[int, str, int, Callable[[], Lines], _Slots, int], ...]] = (
    (
        30,
        "Navy",
        9000,
        sc.naval_line,
        ((NAVAL_FRONT, 3), (NAVAL_ARTILLERY, 2), (NAVAL_AA, 1)),
        80,
    ),
    (31, "Sub Hunt", 9100, sc.naval_hunt, ((NAVAL_HUNTER, 4),), 50),
    (
        32,
        "Bombardment",
        9200,
        sc.naval_bombard,
        ((NAVAL_ARTILLERY, 3), (NAVAL_AA, 1)),
        50,
    ),
)


def naval(ctx: Context, country: Country) -> Iterator[Order]:
    """Navies once a shipyard stands; ships only reach water targets."""
    shipyard = country.factories.get(Factory.SHIPYARD)
    for code, name, script_code, builder, slots, weight in _NAVAL:
        script = _script(country, script_code, name, builder())
        for tier in (1, _TOP):
            if tier == 1:
                gate = None if shipyard is None else _owns(shipyard)
            else:
                gate = _unlock_gate(country, tier)
            lead = slots[0][0].name
            filled = fill(slots, ctx.fielded(country, tier), tier, required=(lead,))
            if gate is None or filled is None:
                continue
            number = code * 100 + tier
            yield _squad(number, f"{name} T{tier}", filled, script)
            yield Call(number, f"{name} T{tier}", number, gate, weight)


# --- Superweapon assaults --------------------------------------------

_CHRONO: Final[tuple[tuple[int, int, str], ...]] = (
    (1, sc.FACTORIES, "Factories"),
    (2, sc.POWER, "Power"),
    (3, sc.DEFENSES, "Defenses"),
)


def superweapon_assaults(ctx: Context, country: Country) -> Iterator[Order]:
    """Chronosphere jumps, Iron Curtain charges and boost assaults.

    The sphere moves only what stands in its 3x3 cells and kills the
    infantry it moves, so jumps and curtain charges take vehicles. A
    boost assault is built from the units a team-cast buff reaches.
    """
    casts = country.front_casts
    heavy = _vehicles(ctx.fielded(country, _TOP))
    if country.chronosphere:
        slots: _Slots = ((FRONT, 4), (ARTILLERY, 2), (AA, 1))
        filled = fill(slots, heavy, _TOP, required=("front",))
        for variant, quarry, name in _CHRONO if filled is not None else ():
            number = 3500 + variant
            assert filled is not None  # noqa: S101 - narrowed by the loop
            lines_ = sc.chrono_assault(quarry, casts)
            script = _script(country, 8100 + quarry, f"Chrono vs {name}", lines_)
            label = f"Chrono Assault vs {name}"
            yield _squad(number, label, filled, script, max_teams=1)
            gate = Gate(Condition.CHRONOSPHERE_CHARGED)
            yield Call(number, label, number, gate, 80)
    curtain = country.curtain
    if curtain is not None:
        filled = fill(((FRONT, 5), (AA, 1)), heavy, _TOP, required=("front",))
        if filled is not None:
            script = _script(
                country, 8200, "Curtain Charge", sc.curtain_charge(curtain, casts)
            )
            yield _squad(3600, "Curtain Charge", filled, script, max_teams=1)
            gate = Gate(Condition.IRON_CURTAIN_CHARGED)
            yield Call(3600, "Curtain Charge", 3600, gate, 150)
    yield from _boosts(ctx, country)


def _boosts(ctx: Context, country: Country) -> Iterator[Order]:
    seen: set[int] = set()
    slots: _Slots = ((FRONT, 4), (SCREEN, 3), (ARTILLERY, 2), (AA, 1), (HERO, 1))
    for cast in country.casts:
        affects = cast.affects
        if cast.home or cast.curtain or affects is None or cast.group in seen:
            continue
        seen.add(cast.group)
        reached = tuple(u for u in ctx.fielded(country, _TOP) if u.armor in affects)
        filled = fill(slots, reached, _TOP)
        if filled is None or sum(n for n, _ in filled[0]) < _BOOST_MEMBERS_MIN:
            continue
        order = (cast.group, *(g for g in country.front_casts if g != cast.group))
        name = f"{_strip(cast.name)} Assault"
        script = _script(country, 8300 + cast.group, name, sc.line_direct(order))
        number = 3700 + cast.group
        yield _squad(number, name, filled, script, recruiter=True)
        yield Call(number, name, number, _owns(cast.building), 70)


# --- Counters --------------------------------------------------------


def counters(ctx: Context, country: Country) -> Iterator[Order]:
    """Answer each notable enemy unit with what kills its armour best.

    A trigger per enemy unit waits until the house's chosen enemy owns
    some; it raises a squad shared by every unit of the same armour,
    which hunts them through an `[AITargetTypes]` list. Air is answered
    by anti-air holding the base.
    """
    made: set[int] = set()
    for index, notable in enumerate(ctx.notable):
        key, tier = notable.key, notable.tier
        number = 6000 + 10 * ctx.keys.index(key) + tier
        if number not in made:
            squad = _counter_squad(ctx, country, notable, number)
            if squad is None:
                continue
            made.add(number)
            yield squad
        unit = notable.unit
        one = unit.has(Role.HERO) or unit.cost >= _ONE_IS_ENOUGH_COST
        amount = 1 if one else _COUNTER_AMOUNT
        gate = Gate(Condition.ENEMY_OWNS, unit.id, amount, Comparison.AT_LEAST)
        yield Call(5000 + index, f"Counter {unit.id}", number, gate, 20)


def _counter_squad(
    ctx: Context,
    country: Country,
    notable: _Notable,
    number: int,
) -> Squad | None:
    key, tier = notable.key, notable.tier
    slot = counter_slot(key.armor, airborne=key.airborne, naval=key.naval)
    if key.airborne:
        slots: _Slots = ((slot, 4), (SCREEN, 1))
    elif key.naval:
        slots = ((slot, 4),)
    else:
        slots = ((slot, 4), (SCREEN, 2), (AA, 1))
    filled = fill(slots, ctx.fielded(country, tier), tier, required=(slot.name,))
    if filled is None:
        return None
    if key.airborne:
        script = _script(country, 5200, "Sky Guard", sc.watch(()))
    else:
        hunted = tuple(n.unit.id for n in ctx.notable if n.key == key)
        target_list = ctx.target_list(hunted)
        script = make_script(
            9500 + target_list,
            f"Mental Counter {key.armor}",
            sc.counter_hunt(target_list),
            "",
        )
    label = f"Counter {key.armor}{' air' if key.airborne else ''} T{tier}"
    return _squad(number, label, filled, script, recruiter=True)


# --- The yard --------------------------------------------------------


def redeploy(ctx: Context, country: Country) -> Iterator[Order]:
    """A new MCV when the construction yard is lost."""
    del ctx
    if not country.mcv or not country.construction_yard:
        return
    script = _script(country, 8000, "Redeploy MCV", sc.redeploy())
    filled: Filled = (((1, country.mcv),), {country.mcv: 1})
    yield _squad(9900, "Redeploy MCV", filled, script, max_teams=1, priority=10)
    gate = Gate(Condition.HOUSE_OWNS, country.construction_yard, 1, Comparison.LESS)
    yield Call(9900, "Redeploy MCV", 9900, gate, 500)


FAMILIES: Final[tuple[Family, ...]] = (
    lines,
    sieges,
    superweapon_snipes,
    raids,
    air_strikes,
    defense,
    occupation,
    infiltration,
    naval,
    superweapon_assaults,
    counters,
    redeploy,
)
