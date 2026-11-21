"""What each country can field, and the role each unit plays.

Every rule here reads the rules data; no unit is named. A unit's roles
come from its weapons against each class of armour, its hull and its
flags, so the same rules hold for every side and survive balance
changes.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, TypedDict
lazy from collections.abc import Iterable, Mapping

from mentara.mentalai.ini import IniData, split_list

__all__ = [
    "Catalog",
    "Country",
    "Factory",
    "Firepower",
    "Kind",
    "Role",
    "TeamCast",
    "Unit",
    "build_catalog",
]


class Kind(StrEnum):
    """The registry a unit is listed in."""

    INFANTRY = "InfantryTypes"
    VEHICLE = "VehicleTypes"
    AIRCRAFT = "AircraftTypes"


class Factory(StrEnum):
    """The kind of building that produces a unit."""

    BARRACKS = "barracks"
    WAR_FACTORY = "war factory"
    SHIPYARD = "shipyard"
    AIRFIELD = "airfield"


class Role(StrEnum):
    """A tag derived from a unit's data; a unit carries several."""

    AIRBORNE = "airborne"
    NAVAL = "naval"
    GUN = "gun"
    AA = "aa"
    AA_ONLY = "aa-only"
    ANTI_INFANTRY = "anti-infantry"
    ANTI_ARMOUR = "anti-armour"
    DUAL = "dual"
    ARTILLERY = "artillery"
    SIEGE = "siege"
    MBT = "mbt"
    HEALER = "healer"
    REPAIRER = "repairer"
    DETECTOR = "detector"
    TRANSPORT = "transport"
    HERO = "hero"
    ENGINEER = "engineer"
    INFILTRATOR = "infiltrator"
    HARVESTER = "harvester"
    MCV = "mcv"
    DEPLOYER = "deployer"
    DOCKED = "docked"
    OCCUPIER = "occupier"
    HIJACKER = "hijacker"
    STEALTH = "stealth"


# The engine's base armour classes, in the order `Verses=` lists them.
_BASE_ARMORS: Final[tuple[str, ...]] = (
    "none",
    "flak",
    "plate",
    "light",
    "medium",
    "heavy",
    "wood",
    "steel",
    "concrete",
    "special_1",
    "special_2",
)
_INFANTRY_ARMORS: Final[tuple[str, ...]] = ("none", "flak", "plate")
_VEHICLE_ARMORS: Final[tuple[str, ...]] = ("light", "medium", "heavy")
_BUILDING_ARMORS: Final[tuple[str, ...]] = ("wood", "steel", "concrete")
_ARMOURED: Final[frozenset[str]] = frozenset({"medium", "heavy"})
# Armour types inherit from one another; MO's chains are a few links
# long.
_ARMOR_DEPTH_MAX: Final[int] = 16
# Damage per second at the engine's 15 frames a second.
_FRAMES_PER_SECOND: Final[float] = 15.0
# A single hit below this only carries an effect (EMP, a designator).
_GUN_HIT_MIN: Final[float] = 10.0
# One damage class must deal twice the other to count as specialised.
_SPECIALISED_RATIO: Final[float] = 2.0
_ARTILLERY_RANGE_MIN: Final[float] = 9.0
_LOBBED_RANGE_MIN: Final[float] = 7.0
_MINIMUM_RANGE_MIN: Final[float] = 2.0
_SIEGE_SHARE_MIN: Final[float] = 0.75
_MBT_STRENGTH_MIN: Final[int] = 300
_MBT_VEHICLE_DPS_MIN: Final[float] = 8.0
_TECH_LEVEL_MIN: Final[int] = 1
# Skirmish's default tech level; higher levels lock a type away.
_TECH_LEVEL_MAX: Final[int] = 10
# Tiers by the tech level of the building that unlocks a unit.
_TIER_2_TECH_LEVEL: Final[int] = 5
_TIER_3_TECH_LEVEL: Final[int] = 8
# Ares's targeting mode for a superweapon only a team script fires.
_TEAM_CAST: Final[str] = "ironcurtain"
_CHRONOSPHERE: Final[str] = "chronosphere"
_IRON_CURTAIN: Final[str] = "ironcurtain"
_WARHEAD_CAST: Final[str] = "genericwarhead"
_GRANT_KEYS: Final[tuple[str, ...]] = ("SuperWeapon", "SuperWeapon2")
# YR's built-in rockets: the `[General]` key prefix and warhead key.
_ROCKETS: Final[tuple[tuple[str, str], ...]] = (
    ("V3Rocket", "V3Warhead"),
    ("DMisl", "DMislWarhead"),
    ("CMisl", "CMislWarhead"),
)
_JUMPJET_LOCOMOTOR: Final[str] = "{92612C46-F71F-11D1-AC9F-006008055BB5}"
_FLY_LOCOMOTOR: Final[str] = "{4A582746-9839-11D1-B709-00A024DDAFD1}"
# YR's built-in generic prerequisites, read from `[General]`.
_BUILT_IN_GROUPS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("power", ("PrerequisitePower",)),
    ("factory", ("PrerequisiteFactory",)),
    ("barracks", ("PrerequisiteBarracks",)),
    ("radar", ("PrerequisiteRadar",)),
    ("tech", ("PrerequisiteTech",)),
    ("proc", ("PrerequisiteProc", "PrerequisiteProcAlternate")),
)


@dataclass(frozen=True, slots=True)
class Firepower:
    """A unit's best damage per second against each class of target.

    Attributes:
        infantry: Mean over the infantry armours.
        vehicle: Mean over the vehicle armours.
        building: Mean over the building armours.
        air: Mean over the vehicle armours, anti-air weapons only.
        hit: The strongest single ground hit.
        range: The longest ground weapon range, in cells.
        minimum_range: The longest ground weapon's minimum range.
        lobbed: Whether a long ground weapon arcs or launches craft.
        heals: Whether a weapon heals infantry.
        repairs: Whether a weapon repairs vehicles.
        against: Best ground damage per second against each armour in
            the rules, by lower-case armour name.
        air_against: The same for anti-air weapons.
    """

    infantry: float
    vehicle: float
    building: float
    air: float
    hit: float
    range: float
    minimum_range: float
    lobbed: bool
    heals: bool
    repairs: bool
    against: Mapping[str, float]
    air_against: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Unit:
    """A unit type and the roles its data gives it.

    Attributes:
        id: The type's ID as the rules spell it.
        kind: Its registry.
        cost: Build cost.
        speed: Movement speed.
        strength: Hit points.
        factory: The building kind that produces it.
        firepower: Its damage profile.
        roles: Every role tag it carries.
        passengers: Transport capacity.
        armor: Its armour, lower-case.
        size: The room it takes in a transport.
        size_limit: The largest passenger a transport takes.
    """

    id: str
    kind: Kind
    cost: int
    speed: float
    strength: int
    factory: Factory
    firepower: Firepower
    roles: frozenset[Role]
    passengers: int
    armor: str
    size: int
    size_limit: int

    def has(self, *roles: Role) -> bool:
        """Whether the unit carries every role given.

        Args:
            *roles: Role tags.

        Returns:
            True when all are present.
        """
        return all(role in self.roles for role in roles)


@dataclass(frozen=True, slots=True)
class TeamCast:
    """A superweapon only a team fires: Ares action 55 on its group.

    Attributes:
        group: Its `SW.Group`.
        name: The superweapon's ID.
        building: A building that grants it.
        home: Whether it belongs at home: it delivers only harvesters.
        curtain: Whether it is an Iron Curtain (`Type=IronCurtain`).
        affects: For a warhead cast, the armours it changes (any
            `Versus` other than 0); None for other kinds.
    """

    group: int
    name: str
    building: str
    home: bool
    curtain: bool
    affects: frozenset[str] | None


@dataclass(frozen=True, slots=True)
class Country:
    """A playable country and what its AI can field.

    Attributes:
        id: The country's ID.
        side: Its 1-based index in `[Sides]`, as AI triggers number
            sides.
        units: Each unit it can field, mapped to the tier it unlocks at.
        buildings: Every building it can own, lower-case.
        factories: The first building of each factory kind it can own.
        gates: For tiers 2 and 3, the building that unlocks most of its
            units of that tier.
        construction_yard: The yard its MCV deploys into.
        mcv: Its MCV.
        docks: Pads of its first airfield, which bound how many
            airfield-bound aircraft it can keep.
        casts: The team-cast superweapons it can own, by group.
        chronosphere: Whether it can own a Chronosphere the AI may use.
        airfields: The aircraft factories it can own.
        superweapon_buildings: The buildings at the top tech level it
            can own that grant a superweapon the AI uses: its strategic
            superweapons.
        absorber: A power plant it can own that infantry enter to boost
            (`InfantryAbsorb`), or "".
        tank_bunker: A tank bunker it can own (`Bunker`), or "".
        battle_bunker: A building it can own that its infantry occupy
            (`CanBeOccupied`), or "".
    """

    id: str
    side: int
    units: Mapping[str, int]
    buildings: frozenset[str]
    factories: Mapping[Factory, str]
    gates: Mapping[int, str]
    construction_yard: str
    mcv: str
    docks: int
    casts: tuple[TeamCast, ...]
    chronosphere: bool
    airfields: tuple[str, ...]
    superweapon_buildings: tuple[str, ...]
    absorber: str
    tank_bunker: str
    battle_bunker: str

    @property
    def front_casts(self) -> tuple[int, ...]:
        """Groups cast where a team fights, in group order."""
        return tuple(sorted({c.group for c in self.casts if not c.home}))

    @property
    def base_casts(self) -> tuple[int, ...]:
        """Groups cast at home, in group order."""
        front = set(self.front_casts)
        return tuple(sorted({c.group for c in self.casts if c.home} - front))

    @property
    def curtain(self) -> int | None:
        """The Iron Curtain's group, if the country casts one."""
        return next((c.group for c in self.casts if c.curtain), None)


@dataclass(frozen=True, slots=True)
class Catalog:
    """Every combat-relevant unit, and every playable country.

    Attributes:
        units: Lower-case ID to unit.
        countries: Playable countries in `[Sides]` order.
    """

    units: Mapping[str, Unit]
    countries: tuple[Country, ...]

    def fielded(self, country: Country, tier: int) -> tuple[Unit, ...]:
        """The units a country can field by a tier, in registry order.

        Args:
            country: The country.
            tier: The highest tier allowed.

        Returns:
            Its units of that tier or lower.
        """
        return tuple(
            self.units[name]
            for name, unlock in country.units.items()
            if unlock <= tier and name in self.units
        )


def build_catalog(rules: IniData) -> Catalog:
    """Read the units and countries from rules data.

    Args:
        rules: The rendered rules INI.

    Returns:
        The catalog.
    """
    reader = _Reader(rules)
    names = [
        (name, kind)
        for kind in Kind
        for name in rules.type_list(kind.value)
        if rules.has(name)
    ]
    armors = sorted({(rules.get(name, "Armor") or "none").lower() for name, _ in names})
    units = {name.lower(): reader.unit(name, kind, armors) for name, kind in names}
    countries = tuple(
        reader.country(country, side)
        for side, side_key in enumerate(rules.keys("Sides"), start=1)
        for country in split_list(rules.get("Sides", side_key))
        if reader.is_playable(country)
    )
    return Catalog(units=units, countries=countries)


class _Superweapons(TypedDict):
    casts: tuple[TeamCast, ...]
    chronosphere: bool
    superweapon_buildings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Weapon:
    damage: float
    burst: float
    rate: float
    range: float
    minimum_range: float
    warhead: str
    anti_air: bool
    anti_ground: bool
    lobbed: bool


class _Reader:
    """Rules lookups shared by the unit and country readers."""

    def __init__(self, rules: IniData) -> None:
        self._rules = rules
        groups: dict[str, frozenset[str]] = {
            key.lower(): _lowered(split_list(rules.get("GenericPrerequisites", key)))
            for key in rules.keys("GenericPrerequisites")
        }
        for group, keys in _BUILT_IN_GROUPS:
            members = (
                name for key in keys for name in split_list(rules.get("General", key))
            )
            groups.setdefault(group, _lowered(members))
        self._groups = groups
        self._buildings = tuple(rules.type_list("BuildingTypes"))
        self._armors = tuple(
            sorted(
                {
                    (rules.get(name, "Armor") or "none").lower()
                    for kind in Kind
                    for name in rules.type_list(kind.value)
                }
            )
        )

    # --- Units -------------------------------------------------------

    def unit(self, name: str, kind: Kind, armors: Iterable[str]) -> Unit:
        rules = self._rules
        firepower = self._firepower(name, tuple(armors))
        roles = self._roles(name, kind, firepower)
        return Unit(
            id=rules.name(name),
            kind=kind,
            cost=int(_number(rules.get(name, "Cost"))),
            speed=_number(rules.get(name, "Speed")),
            strength=int(_number(rules.get(name, "Strength"))),
            factory=self._factory_kind(name, kind),
            firepower=firepower,
            roles=roles,
            passengers=int(_number(rules.get(name, "Passengers"))),
            armor=(rules.get(name, "Armor") or "none").lower(),
            size=int(_number(rules.get(name, "Size"), 1.0)),
            size_limit=int(_number(rules.get(name, "SizeLimit"))),
        )

    def _factory_kind(self, name: str, kind: Kind) -> Factory:
        match kind:
            case Kind.INFANTRY:
                return Factory.BARRACKS
            case Kind.AIRCRAFT:
                return Factory.AIRFIELD
            case Kind.VEHICLE:
                if self._is_naval(name):
                    return Factory.SHIPYARD
                return Factory.WAR_FACTORY

    def _is_naval(self, name: str) -> bool:
        rules = self._rules
        if _yes(rules.get(name, "Naval")):
            return True
        return (rules.get(name, "MovementZone") or "").lower() == "water"

    def _roles(self, name: str, kind: Kind, fire: Firepower) -> frozenset[Role]:
        rules = self._rules
        roles: set[Role] = set()
        locomotor = (rules.get(name, "Locomotor") or "").upper()
        airborne = (
            kind is Kind.AIRCRAFT
            or _yes(rules.get(name, "JumpJet"))
            or locomotor in {_JUMPJET_LOCOMOTOR, _FLY_LOCOMOTOR}
        )
        if airborne:
            roles.add(Role.AIRBORNE)
        if self._is_naval(name):
            roles.add(Role.NAVAL)
        roles |= _combat_roles(fire, kind=kind, airborne=airborne)
        if Role.ARTILLERY in roles and fire.building >= _SIEGE_SHARE_MIN * max(
            fire.infantry, fire.vehicle
        ):
            roles.add(Role.SIEGE)
        passengers = int(_number(rules.get(name, "Passengers")))
        if self._is_mbt(name, kind, roles, fire, passengers=passengers):
            roles.add(Role.MBT)
        flags = (
            (fire.heals, Role.HEALER),
            (fire.repairs, Role.REPAIRER),
            (_yes(rules.get(name, "Sensors")), Role.DETECTOR),
            (passengers > 0, Role.TRANSPORT),
            (_number(rules.get(name, "BuildLimit")) == 1, Role.HERO),
            (_yes(rules.get(name, "Engineer")), Role.ENGINEER),
            (
                _yes(rules.get(name, "Infiltrate")) and _yes(rules.get(name, "Agent")),
                Role.INFILTRATOR,
            ),
            (
                _yes(rules.get(name, "Harvester"))
                or _yes(rules.get(name, "ResourceGatherer")),
                Role.HARVESTER,
            ),
            (self._deploys_into_yard(name), Role.MCV),
            (_yes(rules.get(name, "AirportBound")), Role.DOCKED),
            (_yes(rules.get(name, "Occupier")), Role.OCCUPIER),
            (_yes(rules.get(name, "VehicleThief")), Role.HIJACKER),
            (_yes(rules.get(name, "Cloakable")), Role.STEALTH),
            (
                bool(rules.get(name, "DeploysInto"))
                and not self._deploys_into_yard(name),
                Role.DEPLOYER,
            ),
        )
        roles.update(role for present, role in flags if present)
        return frozenset(roles)

    def _is_mbt(
        self,
        name: str,
        kind: Kind,
        roles: set[Role],
        fire: Firepower,
        *,
        passengers: int,
    ) -> bool:
        rules = self._rules
        hull = (
            kind is Kind.VEHICLE
            and passengers == 0
            and not _yes(rules.get(name, "Gunner"))
            and self._base_armor(rules.get(name, "Armor") or "none") in _ARMOURED
            and int(_number(rules.get(name, "Strength"))) >= _MBT_STRENGTH_MIN
        )
        gun = (
            fire.vehicle >= _MBT_VEHICLE_DPS_MIN
            and bool(roles & {Role.ANTI_ARMOUR, Role.DUAL})
            and not roles & {Role.AIRBORNE, Role.NAVAL, Role.ARTILLERY}
        )
        return hull and gun

    def _deploys_into_yard(self, name: str) -> bool:
        target = self._rules.get(name, "DeploysInto")
        return bool(target) and _yes(self._rules.get(target or "", "ConstructionYard"))

    # --- Weapons -----------------------------------------------------

    def _firepower(self, name: str, armors: tuple[str, ...]) -> Firepower:
        weapons = [w for w in self._weapons(name) if w.damage != 0]
        ground = [w for w in weapons if w.anti_ground]
        # LandTargeting=1 keeps a unit off land targets; a ship still
        # hits ships, any other unit only aircraft.
        land = ground
        if self._rules.get(name, "LandTargeting") == "1":
            land = []
            if not self._is_naval(name):
                ground = []
        air = [w for w in weapons if w.anti_air]
        longest = max(ground, key=lambda w: w.range, default=None)
        return Firepower(
            infantry=self._best(land, _INFANTRY_ARMORS),
            vehicle=self._best(ground, _VEHICLE_ARMORS),
            building=self._best(land, _BUILDING_ARMORS),
            air=self._best(air, _VEHICLE_ARMORS),
            hit=max((self._hit(w) for w in ground), default=0.0),
            range=longest.range if longest else 0.0,
            minimum_range=longest.minimum_range if longest else 0.0,
            lobbed=any(w.lobbed and w.range >= _LOBBED_RANGE_MIN for w in ground),
            heals=any(self._mends(w, _INFANTRY_ARMORS) for w in weapons),
            repairs=any(self._mends(w, _VEHICLE_ARMORS) for w in weapons),
            against={
                a: self._best(self._hitting(a, land, ground), (a,)) for a in armors
            },
            air_against={a: self._best(air, (a,)) for a in armors},
        )

    def _hitting(
        self,
        armor: str,
        land: list[_Weapon],
        ground: list[_Weapon],
    ) -> list[_Weapon]:
        """The weapons that reach a unit of this armour on the ground.

        A ship's anti-ship weapons hit vehicle armours only.
        """
        return ground if self._base_armor(armor) in _VEHICLE_ARMORS else land

    def _weapons(self, name: str) -> list[_Weapon]:
        rules = self._rules
        count = int(_number(rules.get(name, "WeaponCount")))
        if count > 0:
            # A gunner IFV fires Weapon1 while its seat is empty.
            if _yes(rules.get(name, "Gunner")):
                count = 1
            keys = [f"Weapon{index}" for index in range(1, count + 1)]
        else:
            keys = ["Primary", "Secondary"]
        weapons: list[_Weapon] = []
        for key in keys:
            weapon = self._weapon(rules.get(name, key), owner=name)
            if weapon is not None:
                weapons.append(weapon)
        return weapons

    def _weapon(self, name: str | None, *, owner: str) -> _Weapon | None:
        rules = self._rules
        if name is None or not rules.has(name) or _yes(rules.get(name, "NeverUse")):
            return None
        projectile = rules.get(name, "Projectile") or ""
        weapon = _Weapon(
            damage=_number(rules.get(name, "Damage")),
            burst=max(_number(rules.get(name, "Burst"), 1.0), 1.0),
            rate=max(_number(rules.get(name, "ROF"), 1.0), 1.0),
            range=_number(rules.get(name, "Range")),
            minimum_range=_number(rules.get(name, "MinimumRange")),
            warhead=rules.get(name, "Warhead") or "",
            anti_air=_yes(rules.get(projectile, "AA")),
            anti_ground=_yes(rules.get(projectile, "AG"), default=True),
            lobbed=_yes(rules.get(projectile, "Arcing")),
        )
        if _yes(rules.get(name, "Spawner")):
            return self._spawned(weapon, owner)
        if weapon.damage <= 1:
            return self._delivered(weapon, projectile, depth=0)
        return weapon

    def _delivered(self, weapon: _Weapon, projectile: str, *, depth: int) -> _Weapon:
        """The damage a carrier projectile hands on.

        A projectile that splits in the air (`Airburst`) or bursts into
        shrapnel deals its sub-weapon's damage, once per fragment.
        """
        rules = self._rules
        if depth >= _ARMOR_DEPTH_MAX:
            return weapon
        if _yes(rules.get(projectile, "Airburst")):
            sub_name, count_key = rules.get(projectile, "AirburstWeapon"), "Cluster"
            counter = projectile
        else:
            sub_name = rules.get(projectile, "ShrapnelWeapon") or rules.get(
                weapon.warhead, "ShrapnelWeapon"
            )
            count_key = "ShrapnelCount"
            on_projectile = rules.get(projectile, count_key) is not None
            counter = projectile if on_projectile else weapon.warhead
        if sub_name is None or not rules.has(sub_name):
            return weapon
        sub_projectile = rules.get(sub_name, "Projectile") or ""
        sub = _Weapon(
            damage=_number(rules.get(sub_name, "Damage")),
            burst=max(_number(rules.get(sub_name, "Burst"), 1.0), 1.0),
            rate=weapon.rate,
            range=weapon.range,
            minimum_range=weapon.minimum_range,
            warhead=rules.get(sub_name, "Warhead") or "",
            anti_air=weapon.anti_air,
            anti_ground=weapon.anti_ground,
            lobbed=weapon.lobbed,
        )
        if sub.damage <= 1:
            sub = self._delivered(sub, sub_projectile, depth=depth + 1)
        count = max(_number(rules.get(counter, count_key), 1.0), 1.0)
        return _Weapon(
            damage=sub.damage * sub.burst * count,
            burst=weapon.burst,
            rate=weapon.rate,
            range=weapon.range,
            minimum_range=weapon.minimum_range,
            warhead=sub.warhead,
            anti_air=weapon.anti_air,
            anti_ground=weapon.anti_ground,
            lobbed=weapon.lobbed,
        )

    def _spawned(self, weapon: _Weapon, owner: str) -> _Weapon:
        """A spawner's damage: its craft's weapon, or the missile it is.

        A craft with no weapon is a missile: Ares's custom missile keys,
        or one of YR's three rockets configured in `[General]`.
        """
        rules = self._rules
        craft = rules.get(owner, "Spawns") or ""
        craft_weapon = self._weapon(rules.get(craft, "Primary"), owner=craft)
        if craft_weapon is not None:
            damage, warhead = (
                craft_weapon.damage * craft_weapon.burst,
                craft_weapon.warhead,
            )
        else:
            damage, warhead = self._missile(craft)
        count = max(_number(rules.get(owner, "SpawnsNumber"), 1.0), 1.0)
        ammo = max(_number(rules.get(craft, "Ammo"), 1.0), 1.0)
        return _Weapon(
            damage=damage * count * ammo,
            burst=1.0,
            rate=max(
                _number(rules.get(owner, "SpawnRegenRate"), weapon.rate), weapon.rate
            ),
            range=weapon.range,
            minimum_range=weapon.minimum_range,
            warhead=warhead,
            anti_air=weapon.anti_air,
            anti_ground=weapon.anti_ground,
            lobbed=True,
        )

    def _missile(self, craft: str) -> tuple[float, str]:
        rules = self._rules
        if _yes(rules.get(craft, "Missile.Custom")):
            return (
                _number(rules.get(craft, "Missile.Damage")),
                rules.get(craft, "Missile.Warhead") or "",
            )
        for prefix, warhead_key in _ROCKETS:
            if (rules.get("General", f"{prefix}Type") or "").lower() == craft.lower():
                warhead = rules.get("CombatDamage", warhead_key) or rules.get(
                    "General", warhead_key
                )
                return _number(rules.get("General", f"{prefix}Damage")), warhead or ""
        return 0.0, ""

    def _dps(self, weapon: _Weapon, armor: str) -> float:
        versus = self._versus(weapon.warhead, armor)
        return weapon.damage * weapon.burst * versus * _FRAMES_PER_SECOND / weapon.rate

    def _best(self, weapons: Iterable[_Weapon], armors: tuple[str, ...]) -> float:
        best = 0.0
        for weapon in weapons:
            if weapon.damage <= 0:
                continue
            mean = sum(self._dps(weapon, armor) for armor in armors) / len(armors)
            best = max(best, mean)
        return best

    def _hit(self, weapon: _Weapon) -> float:
        if weapon.damage <= 0:
            return 0.0
        armors = _INFANTRY_ARMORS + _VEHICLE_ARMORS + _BUILDING_ARMORS
        versus = max(self._versus(weapon.warhead, armor) for armor in armors)
        return weapon.damage * weapon.burst * versus

    def _mends(self, weapon: _Weapon, armors: tuple[str, ...]) -> bool:
        if weapon.damage >= 0:
            return False
        return any(self._versus(weapon.warhead, armor) > 0 for armor in armors)

    def _versus(self, warhead: str, armor: str) -> float:
        """Ares's damage multiplier of a warhead against an armour type.

        `Versus.<armor>` on the warhead wins; otherwise a custom armour
        takes its parent's value, or the percentage it names; a base
        armour reads its slot of `Verses=`.
        """
        rules = self._rules
        current = armor.lower()
        for _ in range(_ARMOR_DEPTH_MAX):
            override = rules.get(warhead, f"Versus.{current}")
            if override is not None:
                return _percent(override)
            if current in _BASE_ARMORS:
                verses = split_list(rules.get(warhead, "Verses"))
                index = _BASE_ARMORS.index(current)
                return _percent(verses[index]) if index < len(verses) else 1.0
            parent = rules.get("ArmorTypes", current)
            if parent is None:
                return 1.0
            if parent.endswith("%"):
                return _percent(parent)
            current = parent.lower()
        return 1.0

    def _base_armor(self, armor: str) -> str:
        current = armor.lower()
        for _ in range(_ARMOR_DEPTH_MAX):
            if current in _BASE_ARMORS:
                return current
            parent = self._rules.get("ArmorTypes", current)
            if parent is None or parent.endswith("%"):
                return current
            current = parent.lower()
        return current

    # --- Countries ---------------------------------------------------

    def is_playable(self, country: str) -> bool:
        return _yes(self._rules.get(country, "Multiplay"))

    def country(self, country: str, side: int) -> Country:
        rules = self._rules
        mcv = next(
            (
                unit
                for unit in split_list(rules.get("General", "BaseUnit"))
                if self._may_own(unit, country)
            ),
            "",
        )
        yard = rules.get(mcv, "DeploysInto") or ""
        owned = self._owned_buildings(country, yard)
        factories = self._factories(owned)
        airfield = factories.get(Factory.AIRFIELD, "")
        units = {
            name.lower(): tier
            for kind in Kind
            for name in rules.type_list(kind.value)
            if (tier := self._unit_tier(name, country, owned)) is not None
        }
        return Country(
            id=rules.name(country),
            side=side,
            units=units,
            buildings=owned,
            factories=factories,
            gates=self._gates(units, owned),
            construction_yard=rules.name(yard),
            mcv=rules.name(mcv),
            docks=int(_number(rules.get(airfield, "NumberOfDocks"))),
            airfields=self._producing(owned, Factory.AIRFIELD),
            absorber=self._flagged(owned, "InfantryAbsorb", powered=True),
            tank_bunker=self._flagged(owned, "Bunker", powered=False),
            battle_bunker=self._flagged(owned, "CanBeOccupied", powered=False),
            **self._superweapons(owned),
        )

    def _producing(self, owned: frozenset[str], kind: Factory) -> tuple[str, ...]:
        return tuple(
            self._rules.name(b)
            for b in self._buildings
            if b.lower() in owned and self._produces(b) is kind
        )

    def _flagged(self, owned: frozenset[str], key: str, *, powered: bool) -> str:
        """The first building the country can own with a flag set.

        With `powered`, only one that makes power counts: infantry
        entering such a building boost its output.
        """
        rules = self._rules
        return next(
            (
                rules.name(b)
                for b in self._buildings
                if b.lower() in owned
                and _yes(rules.get(b, key))
                and (not powered or _number(rules.get(b, "Power")) > 0)
            ),
            "",
        )

    def _superweapons(self, owned: frozenset[str]) -> _Superweapons:
        """What the superweapons a country can own let its teams do.

        A superweapon with `SW.AITargeting=IronCurtain` never fires on
        its own: it waits for a team to request its `SW.Group` (Ares
        script action 55), and fires on that team. One that delivers
        only harvesters is cast at home, any other where the team
        fights.
        """
        rules = self._rules
        casts: dict[tuple[int, str], TeamCast] = {}
        chronosphere = False
        buildings: list[str] = []
        for building, name in self._grants(owned):
            if rules.get(name, "SW.AllowAI") is not None and not _yes(
                rules.get(name, "SW.AllowAI")
            ):
                continue
            level = int(_number(rules.get(building, "TechLevel")))
            if level >= _TECH_LEVEL_MAX:
                buildings.append(building)
            kind = (rules.get(name, "Type") or "").lower()
            targeting = (rules.get(name, "SW.AITargeting") or "").lower()
            if kind == _CHRONOSPHERE and targeting != _TEAM_CAST:
                chronosphere = True
                continue
            if targeting != _TEAM_CAST:
                continue
            group = int(_number(rules.get(name, "SW.Group")))
            delivered = split_list(rules.get(name, "Deliver.Types"))
            casts.setdefault(
                (group, name.lower()),
                TeamCast(
                    group=group,
                    name=rules.name(name),
                    building=building,
                    home=bool(delivered)
                    and all(self._harvests(unit) for unit in delivered),
                    curtain=kind == _IRON_CURTAIN,
                    affects=self._affects(name) if kind == _WARHEAD_CAST else None,
                ),
            )
        return {
            "casts": tuple(sorted(casts.values(), key=lambda c: (c.group, c.name))),
            "chronosphere": chronosphere,
            "superweapon_buildings": tuple(dict.fromkeys(buildings)),
        }

    def _affects(self, superweapon: str) -> frozenset[str]:
        warhead = self._rules.get(superweapon, "SW.Warhead") or ""
        return frozenset(
            armor for armor in self._armors if self._versus(warhead, armor) != 0
        )

    def _grants(self, owned: frozenset[str]) -> tuple[tuple[str, str], ...]:
        rules = self._rules
        grants: list[tuple[str, str]] = []
        for building in self._buildings:
            if building.lower() not in owned:
                continue
            names = [rules.get(building, key) or "" for key in _GRANT_KEYS]
            names.extend(split_list(rules.get(building, "SuperWeapons")))
            grants.extend(
                (rules.name(building), name) for name in names if rules.has(name)
            )
        return tuple(grants)

    def _harvests(self, unit: str) -> bool:
        rules = self._rules
        return _yes(rules.get(unit, "Harvester")) or _yes(
            rules.get(unit, "ResourceGatherer")
        )

    def _may_own(self, name: str, country: str) -> bool:
        rules = self._rules
        level = int(_number(rules.get(name, "TechLevel"), -1.0))
        if not _TECH_LEVEL_MIN <= level <= _TECH_LEVEL_MAX:
            return False
        folded = country.lower()
        if folded not in _lowered(split_list(rules.get(name, "Owner"))):
            return False
        required = _lowered(split_list(rules.get(name, "RequiredHouses")))
        if required and folded not in required:
            return False
        return folded not in _lowered(split_list(rules.get(name, "ForbiddenHouses")))

    def _owned_buildings(self, country: str, yard: str) -> frozenset[str]:
        owned = {yard.lower()} if yard else set()
        changed = True
        while changed:
            changed = False
            for building in self._buildings:
                folded = building.lower()
                if folded in owned or not self._may_own(building, country):
                    continue
                needs = split_list(self._rules.get(building, "Prerequisite"))
                if all(self._satisfied(need, owned) for need in needs):
                    owned.add(folded)
                    changed = True
        return frozenset(owned)

    def _satisfied(self, need: str, owned: Iterable[str]) -> bool:
        members = self._members(need)
        return bool(members & set(owned))

    def _members(self, need: str) -> frozenset[str]:
        """The buildings a prerequisite names: a group's, or itself."""
        return self._groups.get(need.lower()) or frozenset({need.lower()})

    def _locked(self, need: str) -> bool:
        """A prerequisite no house can ever build, such as MO's AILOCK.

        The AI does not check unit prerequisites when it fills a team,
        so a unit behind such a lock is the AI's own.
        """
        members = self._members(need)
        return all(
            not _TECH_LEVEL_MIN
            <= int(_number(self._rules.get(member, "TechLevel"), -1.0))
            <= _TECH_LEVEL_MAX
            for member in members
        )

    def _unit_tier(self, name: str, country: str, owned: frozenset[str]) -> int | None:
        if not self._rules.has(name) or not self._may_own(name, country):
            return None
        tier = 1
        for need in split_list(self._rules.get(name, "Prerequisite")):
            if self._locked(need):
                continue
            levels = [
                int(_number(self._rules.get(member, "TechLevel")))
                for member in self._members(need)
                if member in owned
            ]
            if not levels:
                return None
            tier = max(tier, _tier_of(min(levels)))
        return tier

    def _factories(self, owned: frozenset[str]) -> dict[Factory, str]:
        found: dict[Factory, tuple[int, str]] = {}
        for building in self._buildings:
            if building.lower() not in owned:
                continue
            kind = self._produces(building)
            if kind is None:
                continue
            level = int(_number(self._rules.get(building, "TechLevel")))
            if kind not in found or level < found[kind][0]:
                found[kind] = (level, self._rules.name(building))
        return {kind: name for kind, (_, name) in found.items()}

    def _produces(self, building: str) -> Factory | None:
        rules = self._rules
        match (rules.get(building, "Factory") or "").lower():
            case "infantrytype":
                return Factory.BARRACKS
            case "aircrafttype":
                return Factory.AIRFIELD
            case "unittype":
                return (
                    Factory.SHIPYARD
                    if _yes(rules.get(building, "Naval"))
                    else (Factory.WAR_FACTORY)
                )
            case _:
                return None

    def _gates(
        self,
        units: Mapping[str, int],
        owned: frozenset[str],
    ) -> dict[int, str]:
        """For tiers 2 and 3, the building that unlocks most units."""
        gates: dict[int, str] = {}
        for tier in (2, 3):
            counts: dict[str, int] = {}
            for name, unlock in units.items():
                if unlock != tier:
                    continue
                for building in self._unlockers(name, owned):
                    level = int(_number(self._rules.get(building, "TechLevel")))
                    if _tier_of(level) == tier:
                        counts[building] = counts.get(building, 0) + 1
            if not counts:
                continue
            best = min(
                counts,
                key=lambda b: (
                    -counts[b],
                    int(_number(self._rules.get(b, "TechLevel"))),
                    b,
                ),
            )
            gates[tier] = self._rules.name(best)
        return gates

    def _unlockers(self, name: str, owned: frozenset[str]) -> tuple[str, ...]:
        found: list[str] = []
        for need in split_list(self._rules.get(name, "Prerequisite")):
            members = self._members(need)
            found.extend(sorted(member for member in members if member in owned))
        return tuple(found)


def _combat_roles(fire: Firepower, *, kind: Kind, airborne: bool) -> set[Role]:
    roles: set[Role] = set()
    if fire.air > 0:
        roles.add(Role.AA)
        if fire.infantry == fire.vehicle == fire.building == 0:
            roles.add(Role.AA_ONLY)
    if fire.hit < _GUN_HIT_MIN:
        return roles
    roles.add(Role.GUN)
    if fire.infantry >= _SPECIALISED_RATIO * fire.vehicle:
        roles.add(Role.ANTI_INFANTRY)
    elif fire.vehicle >= _SPECIALISED_RATIO * fire.infantry:
        roles.add(Role.ANTI_ARMOUR)
    else:
        roles.add(Role.DUAL)
    if airborne:
        return roles
    long_gun = kind is not Kind.INFANTRY and fire.range >= _ARTILLERY_RANGE_MIN
    lobbed = fire.lobbed or fire.minimum_range >= _MINIMUM_RANGE_MIN
    if long_gun or (lobbed and fire.range >= _LOBBED_RANGE_MIN):
        roles.add(Role.ARTILLERY)
    return roles


def _tier_of(tech_level: int) -> int:
    if tech_level >= _TIER_3_TECH_LEVEL:
        return 3
    if tech_level >= _TIER_2_TECH_LEVEL:
        return 2
    return 1


def _lowered(names: Iterable[str]) -> frozenset[str]:
    return frozenset(name.lower() for name in names)


def _yes(value: str | None, *, default: bool = False) -> bool:
    if value is None or not value:
        return default
    return value[0].lower() in {"y", "t", "1"}


def _number(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value.strip().rstrip("%"))
    except ValueError:
        return default


def _percent(value: str) -> float:
    text = value.strip()
    if text.endswith("%"):
        return _number(text) / 100
    return _number(text, 1.0)
