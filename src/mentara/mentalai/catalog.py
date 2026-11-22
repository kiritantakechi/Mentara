"""What each country can field, and the role each unit plays.

Every rule here reads the rules data; no unit is named. A unit's roles
come from its weapons against each class of armour, its hull and its
flags, so the same rules hold for every side and survive balance
changes.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final
lazy from collections.abc import Iterable, Iterator, Mapping

from mentara.mentalai.ini import parse_number
lazy from mentara.mentalai.ini import IniData

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
    MIND_CONTROL = "mind-control"
    # A weapon that disables, slows, freezes, marks or buffs rather than
    # (or as well as) damaging.
    EFFECT = "effect"
    # Plants a timed bomb (Ivan bombs).
    BOMBER = "bomber"
    # A player's version: Ares converts it to an AI twin for the AI.
    PLAYER_VERSION = "player-version"
    # Fights by closing in: its weapon destroys it (`Suicide`), or it
    # must deploy to fire the only weapon it has.
    CHARGER = "charger"
    # Digs in or unfolds where it stands (`IsSimpleDeployer`, infantry
    # `Deployer`): it cannot give ground while it fights.
    DIGS_IN = "digs-in"
    # Takes its weapon from the infantry in its seat (`Gunner`).
    GUNNER = "gunner"
    # Its passengers fire from inside (`OpenTopped`).
    OPEN_TOPPED = "open-topped"
    # Crosses water and land alike (an amphibious `MovementZone`).
    AMPHIBIOUS = "amphibious"


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
# A weapon that reaches this many cells is fired from a distance.
_REACH_MIN: Final[float] = 3.0
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
# Warhead keys of effects: EMP, erasing, parasites, berserk, paralysis
# and the Ares and Phobos attached effects (marks, slows, freezes).
_EFFECT_KEYS: Final[tuple[str, ...]] = (
    "EMEffect",
    "EMP.Duration",
    "Temporal",
    "Parasite",
    "Psychedelic",
    "Paralyzes",
    "AttachEffect.Duration",
    "AttachEffect.AttachTypes",
)
# A warhead key set to one of these carries no effect.
_OFF: Final[frozenset[str]] = frozenset({"no", "false", "0", ""})
_NO_ARMOR: Final[str] = "none"
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
# `MovementZone` values that cross water and land begin with this.
_AMPHIBIOUS_ZONE: Final[str] = "amphibious"
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
class Gun:
    """One of a unit's ground weapons, as its rules spell it.

    Attributes:
        types: Its weapon type and, where the unit has one, the type an
            elite unit fires in its place.
        range: Its range, in cells.
        minimum_range: Its minimum range, in cells.
        reload: Frames between its firings.
    """

    types: tuple[str, ...]
    range: float
    minimum_range: float
    reload: float


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
        guns: Its ground weapons, in the order its rules list them.
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
    guns: tuple[Gun, ...]
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
        ranged: Its damage profile with the weapons that reach past
            arm's length: what it does from inside an open-topped
            carrier, where a blade or a planted charge reaches nothing.
        roles: Every role tag it carries.
        passengers: Transport capacity.
        armor: Its armour, lower-case.
        size: The room it takes in a transport.
        size_limit: The largest passenger a transport takes.
        seat_mode: Which weapon an infantry gives a gunner vehicle it
            rides (`IFVMode`).
        mounts: For a gunner vehicle, its firepower by seat mode.
    """

    id: str
    kind: Kind
    cost: int
    speed: float
    strength: int
    factory: Factory
    firepower: Firepower
    ranged: Firepower
    roles: frozenset[Role]
    passengers: int
    armor: str
    size: int
    size_limit: int
    seat_mode: int
    mounts: Mapping[int, Firepower]

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
        tier: The tier that building belongs to.
        home: Whether it belongs at home: it delivers only harvesters.
        curtain: Whether it is an Iron Curtain (`Type=IronCurtain`).
        affects: For a warhead cast, the armours it changes (any
            `Versus` other than 0); None for other kinds.
    """

    group: int
    name: str
    building: str
    tier: int
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
        construction_yard: The yard its MCV deploys into, if it has
            an MCV.
        mcv: Its MCV, if any.
        docks: Pads of its first airfield, which bound how many
            airfield-bound aircraft it can keep.
        casts: The team-cast superweapons it can own, by group.
        chronosphere: Whether it can own a Chronosphere the AI may use.
        airfields: The aircraft factories it can own.
        superweapon_buildings: The buildings at the top tech level it
            can own that grant a superweapon the AI uses: its strategic
            superweapons.
        absorber: A power plant it can own that infantry enter to boost
            (`InfantryAbsorb`), if any.
        tank_bunker: A tank bunker it can own (`Bunker`), if any.
        battle_bunker: A building it can own that its infantry occupy
            (`CanBeOccupied`), if any.
    """

    id: str
    side: int
    units: Mapping[str, int]
    buildings: frozenset[str]
    factories: Mapping[Factory, str]
    gates: Mapping[int, str]
    construction_yard: str | None
    mcv: str | None
    docks: int
    casts: tuple[TeamCast, ...]
    chronosphere: bool
    airfields: tuple[str, ...]
    superweapon_buildings: tuple[str, ...]
    absorber: str | None
    tank_bunker: str | None
    battle_bunker: str | None

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
        tech_buildings: Buildings no country builds that an engineer
            takes (`Capturable`, `NeedsEngineer`): the map's tech.
        bridge_huts: Buildings an engineer enters to mend a bridge.
        building_types: Every building type, lower-case, in the
            engine's registry order.
    """

    units: Mapping[str, Unit]
    countries: tuple[Country, ...]
    tech_buildings: tuple[str, ...]
    bridge_huts: tuple[str, ...]
    building_types: tuple[str, ...]

    def building_index(self, building: str) -> int:
        """A building type's index in the engine's registry.

        A vanilla script line names a building type by it (MO's own
        scripts decode to the buildings their names say).

        Args:
            building: The building's ID.

        Returns:
            Its index.
        """
        return self.building_types.index(building.lower())

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
    units = frozendict(
        (name.lower(), reader.unit(name, kind))
        for kind in Kind
        for name in rules.type_list(kind.value)
        if rules.has(name)
    )
    countries = tuple(
        reader.country(country, side)
        for side, side_key in enumerate(rules.keys("Sides"), start=1)
        for country in rules.listed("Sides", side_key)
        if rules.flag(country, "Multiplay")
    )
    owned = frozenset(b for country in countries for b in country.buildings)
    registry = rules.type_list("BuildingTypes")
    buildings = [b for b in registry if rules.has(b)]
    return Catalog(
        units=units,
        countries=countries,
        tech_buildings=tuple(
            rules.name(b)
            for b in buildings
            if b.lower() not in owned
            and rules.flag(b, "Capturable")
            and rules.flag(b, "NeedsEngineer")
        ),
        bridge_huts=tuple(
            rules.name(b) for b in buildings if rules.flag(b, "BridgeRepairHut")
        ),
        building_types=tuple(b.lower() for b in registry),
    )


@dataclass(frozen=True, slots=True)
class _Arsenal:
    """What the superweapons a country can own let its teams do."""

    casts: tuple[TeamCast, ...]
    chronosphere: bool
    buildings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Weapon:
    id: str
    damage: float
    burst: float
    rate: float
    range: float
    minimum_range: float
    warhead: str
    anti_air: bool
    anti_ground: bool
    lobbed: bool
    extra_warheads: tuple[str, ...] = ()

    @property
    def salvo(self) -> float:
        """The damage of one firing, before the warhead's verses."""
        return self.damage * self.burst


class _Reader:
    """Rules lookups shared by the unit and country readers."""

    def __init__(self, rules: IniData) -> None:
        self._rules = rules
        groups: dict[str, frozenset[str]] = {
            key.lower(): _lowered(rules.listed("GenericPrerequisites", key))
            for key in rules.keys("GenericPrerequisites")
        }
        for group, keys in _BUILT_IN_GROUPS:
            members = (name for key in keys for name in rules.listed("General", key))
            groups.setdefault(group, _lowered(members))
        self._groups = groups
        self._buildings = rules.type_list("BuildingTypes")
        units = [(name, kind) for kind in Kind for name in rules.type_list(kind.value)]
        self._armors = self._worn(units)
        # Aircraft wear armours of their own, which anti-air warheads
        # name in `Versus.<armor>`: anti-air is judged against them.
        self._air_armors = self._worn(pair for pair in units if self._flies(*pair))

    def _worn(self, units: Iterable[tuple[str, Kind]]) -> tuple[str, ...]:
        """The armours a set of units wears, sorted."""
        return tuple(sorted({self._armor(name) for name, _ in units}))

    def _armor(self, name: str) -> str:
        return self._rules.token(name, "Armor", _NO_ARMOR)

    def _flies(self, name: str, kind: Kind) -> bool:
        locomotor = self._rules.token(name, "Locomotor").upper()
        return (
            kind is Kind.AIRCRAFT
            or self._rules.flag(name, "JumpJet")
            or locomotor in {_JUMPJET_LOCOMOTOR, _FLY_LOCOMOTOR}
        )

    # --- Units -------------------------------------------------------

    def unit(self, name: str, kind: Kind) -> Unit:
        rules = self._rules
        firepower = self._firepower(name)
        return Unit(
            id=rules.name(name),
            kind=kind,
            cost=rules.integer(name, "Cost"),
            speed=rules.number(name, "Speed"),
            strength=rules.integer(name, "Strength"),
            factory=self._factory_kind(name, kind),
            firepower=firepower,
            ranged=self._profile(
                name, [w for w in self._weapons(name) if w.range >= _REACH_MIN]
            ),
            roles=self._roles(name, kind, firepower),
            passengers=rules.integer(name, "Passengers"),
            armor=self._armor(name),
            size=rules.integer(name, "Size", 1),
            size_limit=rules.integer(name, "SizeLimit"),
            seat_mode=rules.integer(name, "IFVMode"),
            mounts=self._mounts(name),
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
        return rules.flag(name, "Naval") or rules.token(name, "MovementZone") == "water"

    def _is_amphibious(self, name: str) -> bool:
        zone = self._rules.token(name, "MovementZone")
        return zone.startswith(_AMPHIBIOUS_ZONE)

    def _roles(self, name: str, kind: Kind, fire: Firepower) -> frozenset[Role]:
        rules = self._rules
        airborne = self._flies(name, kind)
        roles = _combat_roles(fire, kind=kind, airborne=airborne)
        if Role.ARTILLERY in roles and fire.building >= _SIEGE_SHARE_MIN * max(
            fire.infantry, fire.vehicle
        ):
            roles.add(Role.SIEGE)
        yard = self._deploys_into_yard(name)
        flags = (
            (airborne, Role.AIRBORNE),
            (self._is_naval(name), Role.NAVAL),
            (fire.heals, Role.HEALER),
            (fire.repairs, Role.REPAIRER),
            (rules.flag(name, "Sensors"), Role.DETECTOR),
            (rules.integer(name, "Passengers") > 0, Role.TRANSPORT),
            (rules.number(name, "BuildLimit") == 1, Role.HERO),
            (rules.flag(name, "Engineer"), Role.ENGINEER),
            (
                rules.flag(name, "Infiltrate") and rules.flag(name, "Agent"),
                Role.INFILTRATOR,
            ),
            (self._harvests(name), Role.HARVESTER),
            (yard, Role.MCV),
            (rules.flag(name, "AirportBound"), Role.DOCKED),
            (rules.flag(name, "Occupier"), Role.OCCUPIER),
            (rules.flag(name, "VehicleThief"), Role.HIJACKER),
            (rules.flag(name, "Cloakable"), Role.STEALTH),
            (self._warheads_have(name, ("MindControl",)), Role.MIND_CONTROL),
            (self._warheads_have(name, _EFFECT_KEYS), Role.EFFECT),
            (self._warheads_have(name, ("IvanBomb",)), Role.BOMBER),
            (bool(rules.get(name, "Convert.HumanToComputer")), Role.PLAYER_VERSION),
            (self._charges(name), Role.CHARGER),
            (
                rules.flag(name, "IsSimpleDeployer") or rules.flag(name, "Deployer"),
                Role.DIGS_IN,
            ),
            (rules.flag(name, "Gunner"), Role.GUNNER),
            (rules.flag(name, "OpenTopped"), Role.OPEN_TOPPED),
            (self._is_amphibious(name), Role.AMPHIBIOUS),
            (bool(rules.get(name, "DeploysInto")) and not yard, Role.DEPLOYER),
        )
        roles.update(role for present, role in flags if present)
        if self._is_mbt(name, kind, roles, fire):
            roles.add(Role.MBT)
        return frozenset(roles)

    def _charges(self, name: str) -> bool:
        """Whether a unit fights by closing in on one target.

        Its primary weapon destroys it (`Suicide`), or it is its only
        weapon and fires deployed (`DeployFireWeapon=0`): Phobos reads
        the undeployed slot, finds no weapon and gives such a leader no
        target, so these units take vanilla quarries.
        """
        rules = self._rules
        primary = rules.get(name, "Primary")
        if primary is None or not rules.has(primary):
            return False
        if rules.flag(primary, "Suicide"):
            return True
        deployed = (
            rules.flag(name, "DeployFire")
            and rules.number(name, "DeployFireWeapon", 1.0) == 0
        )
        secondary = rules.get(name, "Secondary")
        return deployed and (secondary is None or not rules.has(secondary))

    def _warheads_have(self, name: str, keys: tuple[str, ...]) -> bool:
        """Whether any of the unit's weapons carries a warhead flag."""
        return any(
            self._rules.token(warhead, key, "no") not in _OFF
            for weapon in self._weapons(name)
            for warhead in (weapon.warhead, *weapon.extra_warheads)
            for key in keys
        )

    def _is_mbt(self, name: str, kind: Kind, roles: set[Role], fire: Firepower) -> bool:
        rules = self._rules
        hull = (
            kind is Kind.VEHICLE
            and Role.TRANSPORT not in roles
            and not rules.flag(name, "Gunner")
            and self._base_armor(self._armor(name)) in _ARMOURED
            and rules.integer(name, "Strength") >= _MBT_STRENGTH_MIN
        )
        gun = (
            fire.vehicle >= _MBT_VEHICLE_DPS_MIN
            and bool(roles & {Role.ANTI_ARMOUR, Role.DUAL})
            and not roles & {Role.AIRBORNE, Role.NAVAL, Role.ARTILLERY}
        )
        return hull and gun

    def _deploys_into_yard(self, name: str) -> bool:
        target = self._rules.get(name, "DeploysInto")
        return bool(target) and self._rules.flag(target or "", "ConstructionYard")

    def _harvests(self, name: str) -> bool:
        rules = self._rules
        return rules.flag(name, "Harvester") or rules.flag(name, "ResourceGatherer")

    # --- Weapons -----------------------------------------------------

    def _firepower(self, name: str) -> Firepower:
        return self._profile(name, self._weapons(name))

    def _mounts(self, name: str) -> Mapping[int, Firepower]:
        """A gunner vehicle's firepower with each of its weapons.

        The infantry in its seat picks the weapon: `IFVMode` n fires
        `Weapon` n + 1.
        """
        rules = self._rules
        count = rules.integer(name, "WeaponCount") if rules.flag(name, "Gunner") else 0
        found = (
            (mode, self._weapon(rules.get(name, f"Weapon{mode + 1}"), owner=name))
            for mode in range(count)
        )
        return frozendict(
            (mode, self._profile(name, [weapon]))
            for mode, weapon in found
            if weapon is not None
        )

    def _profile(self, name: str, fitted: list[_Weapon]) -> Firepower:
        """A unit's firepower with a set of weapons fitted."""
        weapons = [w for w in fitted if w.damage != 0]
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
            air=self._best(air, self._air_armors or _VEHICLE_ARMORS),
            hit=max((self._hit(w) for w in ground), default=0.0),
            range=longest.range if longest else 0.0,
            minimum_range=longest.minimum_range if longest else 0.0,
            guns=tuple(
                Gun(self._with_elite(name, w.id), w.range, w.minimum_range, w.rate)
                for w in ground
            ),
            lobbed=any(w.lobbed and w.range >= _LOBBED_RANGE_MIN for w in ground),
            heals=any(self._mends(w, _INFANTRY_ARMORS) for w in weapons),
            repairs=any(self._mends(w, _VEHICLE_ARMORS) for w in weapons),
            # A ship's anti-ship weapons hit vehicle armours only.
            against=frozendict(
                (
                    armor,
                    self._best(
                        ground if self._base_armor(armor) in _VEHICLE_ARMORS else land,
                        (armor,),
                    ),
                )
                for armor in self._armors
            ),
            air_against=frozendict(
                (armor, self._best(air, (armor,))) for armor in self._armors
            ),
        )

    def _weapon_keys(self, name: str) -> tuple[str, ...]:
        """The keys a unit's weapons sit under."""
        rules = self._rules
        count = rules.integer(name, "WeaponCount")
        if count <= 0:
            return ("Primary", "Secondary")
        # A gunner IFV fires Weapon1 while its seat is empty.
        if rules.flag(name, "Gunner"):
            count = 1
        return tuple(f"Weapon{index}" for index in range(1, count + 1))

    def _weapons(self, name: str) -> list[_Weapon]:
        rules = self._rules
        keys = self._weapon_keys(name)
        found = (self._weapon(rules.get(name, key), owner=name) for key in keys)
        return [weapon for weapon in found if weapon is not None]

    def _with_elite(self, name: str, weapon: str) -> tuple[str, ...]:
        """A unit's weapon, and the one it fires instead when elite."""
        rules = self._rules
        elite = (
            rules.get(name, f"Elite{key}")
            for key in self._weapon_keys(name)
            if (rules.get(name, key) or "").lower() == weapon.lower()
        )
        twins = (rules.name(e) for e in elite if e is not None and rules.has(e))
        return tuple(dict.fromkeys((weapon, *twins)))

    def _weapon(self, name: str | None, *, owner: str) -> _Weapon | None:
        rules = self._rules
        if name is None or not rules.has(name) or rules.flag(name, "NeverUse"):
            return None
        projectile = rules.get(name, "Projectile") or ""
        weapon = _Weapon(
            id=rules.name(name),
            damage=rules.number(name, "Damage"),
            burst=_at_least_one(rules.number(name, "Burst", 1.0)),
            rate=_at_least_one(rules.number(name, "ROF", 1.0)),
            range=rules.number(name, "Range"),
            minimum_range=rules.number(name, "MinimumRange"),
            warhead=rules.get(name, "Warhead") or "",
            anti_air=rules.flag(projectile, "AA"),
            anti_ground=rules.flag(projectile, "AG", default=True),
            lobbed=rules.flag(projectile, "Arcing"),
            extra_warheads=rules.listed(name, "ExtraWarheads"),
        )
        if rules.flag(name, "Spawner"):
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
        if rules.flag(projectile, "Airburst"):
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
        sub = replace(
            weapon,
            damage=rules.number(sub_name, "Damage"),
            burst=_at_least_one(rules.number(sub_name, "Burst", 1.0)),
            warhead=rules.get(sub_name, "Warhead") or "",
            extra_warheads=(),
        )
        if sub.damage <= 1:
            sub_projectile = rules.get(sub_name, "Projectile") or ""
            sub = self._delivered(sub, sub_projectile, depth=depth + 1)
        count = _at_least_one(rules.number(counter, count_key, 1.0))
        return replace(
            weapon, damage=sub.salvo * count, warhead=sub.warhead, extra_warheads=()
        )

    def _spawned(self, weapon: _Weapon, owner: str) -> _Weapon:
        """A spawner's damage: its craft's weapon, or the missile it is.

        A craft with no weapon is a missile: Ares's custom missile keys,
        or one of YR's three rockets configured in `[General]`.
        """
        rules = self._rules
        craft = rules.get(owner, "Spawns") or ""
        craft_weapon = self._weapon(rules.get(craft, "Primary"), owner=craft)
        if craft_weapon is None:
            damage, warhead = self._missile(craft)
        else:
            damage, warhead = craft_weapon.salvo, craft_weapon.warhead
        count = _at_least_one(rules.number(owner, "SpawnsNumber", 1.0))
        ammo = _at_least_one(rules.number(craft, "Ammo", 1.0))
        return replace(
            weapon,
            damage=damage * count * ammo,
            burst=1.0,
            rate=max(rules.number(owner, "SpawnRegenRate", weapon.rate), weapon.rate),
            warhead=warhead,
            lobbed=True,
            extra_warheads=(),
        )

    def _missile(self, craft: str) -> tuple[float, str]:
        rules = self._rules
        if rules.flag(craft, "Missile.Custom"):
            return (
                rules.number(craft, "Missile.Damage"),
                rules.get(craft, "Missile.Warhead") or "",
            )
        for prefix, warhead_key in _ROCKETS:
            if rules.token("General", f"{prefix}Type") == craft.lower():
                warhead = rules.get("CombatDamage", warhead_key) or rules.get(
                    "General", warhead_key
                )
                return rules.number("General", f"{prefix}Damage"), warhead or ""
        return 0.0, ""

    def _dps(self, weapon: _Weapon, armor: str) -> float:
        versus = self._versus(weapon.warhead, armor)
        return weapon.salvo * versus * _FRAMES_PER_SECOND / weapon.rate

    def _best(self, weapons: Iterable[_Weapon], armors: tuple[str, ...]) -> float:
        """The best mean damage per second over some armours."""
        means = (
            sum(self._dps(weapon, armor) for armor in armors) / len(armors)
            for weapon in weapons
            if weapon.damage > 0
        )
        return max((0.0, *means))

    def _hit(self, weapon: _Weapon) -> float:
        if weapon.damage <= 0:
            return 0.0
        armors = _INFANTRY_ARMORS + _VEHICLE_ARMORS + _BUILDING_ARMORS
        versus = max(self._versus(weapon.warhead, armor) for armor in armors)
        return weapon.salvo * versus

    def _mends(self, weapon: _Weapon, armors: tuple[str, ...]) -> bool:
        if weapon.damage >= 0:
            return False
        return any(self._versus(weapon.warhead, armor) > 0 for armor in armors)

    def _lineage(self, armor: str) -> Iterator[tuple[str, str | None]]:
        """An armour and its ancestors, with their `[ArmorTypes]` entry.

        A custom armour names its parent, or a percentage that ends the
        line; a base armour has no entry.
        """
        current = armor.lower()
        for _ in range(_ARMOR_DEPTH_MAX):
            value = None
            if current not in _BASE_ARMORS:
                value = self._rules.get("ArmorTypes", current)
            yield current, value
            if value is None or value.endswith("%"):
                return
            current = value.lower()

    def _versus(self, warhead: str, armor: str) -> float:
        """Ares's damage multiplier of a warhead against an armour type.

        `Versus.<armor>` on the warhead wins; otherwise a custom armour
        takes its parent's value, or the percentage it names; a base
        armour reads its slot of `Verses=`.
        """
        rules = self._rules
        for current, value in self._lineage(armor):
            override = rules.get(warhead, f"Versus.{current}")
            if override is not None:
                return _percent(override)
            if current in _BASE_ARMORS:
                verses = rules.listed(warhead, "Verses")
                index = _BASE_ARMORS.index(current)
                return _percent(verses[index]) if index < len(verses) else 1.0
            if value is not None and value.endswith("%"):
                return _percent(value)
        return 1.0

    def _base_armor(self, armor: str) -> str:
        """The base armour a type descends from, or its line's end."""
        *_, (last, _) = self._lineage(armor)
        return last

    # --- Countries ---------------------------------------------------

    def country(self, country: str, side: int) -> Country:
        rules = self._rules
        mcv = next(
            (
                rules.name(unit)
                for unit in rules.listed("General", "BaseUnit")
                if self._may_own(unit, country)
            ),
            None,
        )
        target = "" if mcv is None else rules.get(mcv, "DeploysInto") or ""
        yard = rules.name(target) if target else None
        owned = self._owned_buildings(country, yard)
        factories = self._factories(owned)
        airfield = factories.get(Factory.AIRFIELD, "")
        units = frozendict(
            (name.lower(), tier)
            for kind in Kind
            for name in rules.type_list(kind.value)
            if (tier := self._unit_tier(name, country, owned)) is not None
        )
        arsenal = self._arsenal(owned)
        return Country(
            id=rules.name(country),
            side=side,
            units=units,
            buildings=owned,
            factories=factories,
            gates=self._gates(units, owned),
            construction_yard=yard,
            mcv=mcv,
            docks=rules.integer(airfield, "NumberOfDocks"),
            casts=arsenal.casts,
            chronosphere=arsenal.chronosphere,
            airfields=tuple(
                rules.name(b)
                for b in self._owned(owned)
                if self._produces(b) is Factory.AIRFIELD
            ),
            superweapon_buildings=arsenal.buildings,
            absorber=self._flagged(owned, "InfantryAbsorb", powered=True),
            tank_bunker=self._flagged(owned, "Bunker", powered=False),
            battle_bunker=self._flagged(owned, "CanBeOccupied", powered=False),
        )

    def _owned(self, owned: frozenset[str]) -> Iterator[str]:
        """The buildings a country can own, in registry order."""
        return (b for b in self._buildings if b.lower() in owned)

    def _flagged(self, owned: frozenset[str], key: str, *, powered: bool) -> str | None:
        """The first building the country can own with a flag set.

        With `powered`, only one that makes power counts: infantry
        entering such a building boost its output.
        """
        rules = self._rules
        return next(
            (
                rules.name(b)
                for b in self._owned(owned)
                if rules.flag(b, key) and (not powered or rules.number(b, "Power") > 0)
            ),
            None,
        )

    def _arsenal(self, owned: frozenset[str]) -> _Arsenal:
        """Sort the superweapons a country can own by who fires them.

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
            allowed = rules.get(name, "SW.AllowAI")
            if allowed is not None and not rules.flag(name, "SW.AllowAI"):
                continue
            level = rules.integer(building, "TechLevel")
            if level >= _TECH_LEVEL_MAX:
                buildings.append(building)
            kind = rules.token(name, "Type")
            team_cast = rules.token(name, "SW.AITargeting") == _TEAM_CAST
            if kind == _CHRONOSPHERE and not team_cast:
                chronosphere = True
            if not team_cast:
                continue
            group = rules.integer(name, "SW.Group")
            delivered = rules.listed(name, "Deliver.Types")
            casts.setdefault(
                (group, name.lower()),
                TeamCast(
                    group=group,
                    name=rules.name(name),
                    building=building,
                    tier=_tier_of(level),
                    home=bool(delivered) and all(map(self._harvests, delivered)),
                    curtain=kind == _IRON_CURTAIN,
                    affects=self._affects(name) if kind == _WARHEAD_CAST else None,
                ),
            )
        return _Arsenal(
            casts=tuple(sorted(casts.values(), key=lambda c: (c.group, c.name))),
            chronosphere=chronosphere,
            buildings=tuple(dict.fromkeys(buildings)),
        )

    def _affects(self, superweapon: str) -> frozenset[str]:
        warhead = self._rules.get(superweapon, "SW.Warhead") or ""
        return frozenset(
            armor for armor in self._armors if self._versus(warhead, armor) != 0
        )

    def _grants(self, owned: frozenset[str]) -> Iterator[tuple[str, str]]:
        """Each building a country can own, with a superweapon of it."""
        rules = self._rules
        for building in self._owned(owned):
            names = [rules.get(building, key) or "" for key in _GRANT_KEYS]
            names.extend(rules.listed(building, "SuperWeapons"))
            for name in names:
                if rules.has(name):
                    yield rules.name(building), name

    def _buildable(self, name: str) -> bool:
        """Whether a type's tech level lets any house build it."""
        level = self._rules.integer(name, "TechLevel", -1)
        return _TECH_LEVEL_MIN <= level <= _TECH_LEVEL_MAX

    def _may_own(self, name: str, country: str) -> bool:
        rules = self._rules
        if not self._buildable(name):
            return False
        folded = country.lower()
        if folded not in _lowered(rules.listed(name, "Owner")):
            return False
        required = _lowered(rules.listed(name, "RequiredHouses"))
        if required and folded not in required:
            return False
        return folded not in _lowered(rules.listed(name, "ForbiddenHouses"))

    def _owned_buildings(self, country: str, yard: str | None) -> frozenset[str]:
        owned = set() if yard is None else {yard.lower()}
        changed = True
        while changed:
            changed = False
            for building in self._buildings:
                folded = building.lower()
                if folded in owned or not self._may_own(building, country):
                    continue
                needs = self._rules.listed(building, "Prerequisite")
                if all(self._members(need) & owned for need in needs):
                    owned.add(folded)
                    changed = True
        return frozenset(owned)

    def _members(self, need: str) -> frozenset[str]:
        """The buildings a prerequisite names: a group's, or itself."""
        return self._groups.get(need.lower()) or frozenset({need.lower()})

    def _locked(self, need: str) -> bool:
        """A prerequisite no house can ever build, such as MO's AILOCK.

        The AI does not check unit prerequisites when it fills a team,
        so a unit behind such a lock is the AI's own.
        """
        return not any(map(self._buildable, self._members(need)))

    def _unit_tier(self, name: str, country: str, owned: frozenset[str]) -> int | None:
        if not self._rules.has(name) or not self._may_own(name, country):
            return None
        tier = 1
        for need in self._rules.listed(name, "Prerequisite"):
            if self._locked(need):
                continue
            levels = [
                self._rules.integer(member, "TechLevel")
                for member in self._members(need)
                if member in owned
            ]
            if not levels:
                return None
            tier = max(tier, _tier_of(min(levels)))
        return tier

    def _factories(self, owned: frozenset[str]) -> Mapping[Factory, str]:
        """The lowest-tech building of each factory kind."""
        found: dict[Factory, tuple[int, str]] = {}
        for building in self._owned(owned):
            kind = self._produces(building)
            if kind is None:
                continue
            level = self._rules.integer(building, "TechLevel")
            if kind not in found or level < found[kind][0]:
                found[kind] = (level, self._rules.name(building))
        return frozendict((kind, name) for kind, (_, name) in found.items())

    def _produces(self, building: str) -> Factory | None:
        rules = self._rules
        match rules.token(building, "Factory"):
            case "infantrytype":
                return Factory.BARRACKS
            case "aircrafttype":
                return Factory.AIRFIELD
            case "unittype" if rules.flag(building, "Naval"):
                return Factory.SHIPYARD
            case "unittype":
                return Factory.WAR_FACTORY
            case _:
                return None

    def _gates(
        self, units: Mapping[str, int], owned: frozenset[str]
    ) -> Mapping[int, str]:
        """For tiers 2 and 3, the building that unlocks most units."""
        rules = self._rules
        gates: dict[int, str] = {}
        for tier in (2, 3):
            counts: dict[str, int] = {}
            for name, unlock in units.items():
                if unlock != tier:
                    continue
                for building in self._unlockers(name, owned):
                    if _tier_of(rules.integer(building, "TechLevel")) == tier:
                        counts[building] = counts.get(building, 0) + 1
            if not counts:
                continue
            best = min(
                counts,
                key=lambda b: (-counts[b], rules.integer(b, "TechLevel"), b),
            )
            gates[tier] = rules.name(best)
        return frozendict(gates)

    def _unlockers(self, name: str, owned: frozenset[str]) -> Iterator[str]:
        for need in self._rules.listed(name, "Prerequisite"):
            yield from sorted(self._members(need) & owned)


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


def _at_least_one(value: float) -> float:
    return max(value, 1.0)


def _percent(value: str) -> float:
    """A `Verses` entry: a percentage, or a plain multiplier."""
    text = value.strip()
    if text.endswith("%"):
        return parse_number(text) / 100
    return parse_number(text, 1.0)
