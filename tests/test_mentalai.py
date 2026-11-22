"""The Mental AI generator, on a small rules file shaped like MO's."""

import struct
from dataclasses import dataclass
from pathlib import Path
lazy from collections.abc import Mapping

import pytest

from mentara.mentalai import AIPlan, Catalog, IniData, build_catalog, plan_ai
from mentara.mentalai.catalog import Factory, Role
from mentara.mentalai.emit import (
    render_ai_fragment,
    render_option_fragment,
    render_rules_fragment,
)
from mentara.mentalai.generate import AI_FRAGMENT, OPTION_FRAGMENT
from mentara.mentalai.handling import stand_offs
from mentara.mentalai.ini import split_list
from mentara.mentalai.model import (
    Comparison,
    Condition,
    Gate,
    MindControl,
    ScriptType,
    TeamType,
    Trigger,
)
lazy from mentara.mentalai.scripts import Lines

# One side with one country. Its yard unlocks a barracks and a war
# factory (tier 1), a radar (tech level 5, tier 2) and labs (tech level
# 8, tier 3), which unlock a silo and its strategic superweapon. LOCK
# is the AI-only lock: no house builds it. DERRICK and HUT belong to
# the map.
RULES = """
[General]
BaseUnit=MCV
PrerequisitePower=POWR
PrerequisiteFactory=WEAP
PrerequisiteBarracks=PILE

[Sides]
GDI=Alpha

[Countries]
0=Alpha

[Alpha]
Multiplay=yes

[GenericPrerequisites]
ANYWEAP=WEAP

[BuildingTypes]
0=YARD
1=POWR
2=PILE
3=WEAP
4=RADR
5=LABS
6=LOCK
7=AIRF
8=DERRICK
9=HUT
10=DOCK
11=SILO

; At the top tech level: its superweapon is a strategic one.
[SILO]
TechLevel=10
Owner=Alpha
Prerequisite=LABS
SuperWeapon=StormSW

[DOCK]
TechLevel=2
Owner=Alpha
Prerequisite=POWR
Factory=UnitType
Naval=yes

; Tech no country builds: an engineer takes it.
[DERRICK]
TechLevel=-1
Capturable=yes
NeedsEngineer=yes

; An engineer enters it to mend its bridge.
[HUT]
TechLevel=-1
BridgeRepairHut=yes

[YARD]
TechLevel=1
Owner=Alpha
ConstructionYard=yes
Factory=BuildingType

[POWR]
TechLevel=1
Owner=Alpha
Prerequisite=YARD

[PILE]
TechLevel=1
Owner=Alpha
Prerequisite=POWR
Factory=InfantryType

[WEAP]
TechLevel=2
Owner=Alpha
Prerequisite=PILE
Factory=UnitType

[RADR]
TechLevel=5
Owner=Alpha
Prerequisite=WEAP
SuperWeapon=MinerSW

[LABS]
TechLevel=8
Owner=Alpha
Prerequisite=RADR
SuperWeapon=CurtainSW
SuperWeapon2=SphereSW
SuperWeapons=LiftSW

[LOCK]
TechLevel=11
Owner=Alpha

[AIRF]
TechLevel=6
Owner=Alpha
Prerequisite=RADR
Factory=AircraftType
NumberOfDocks=4

[InfantryTypes]
0=GI
1=MEDIC
2=HERO
3=PSI
4=ENG
5=SAPPER
6=SPY
7=BAZ

[VehicleTypes]
0=TANK
1=FLAK
2=ARTY
3=MCV
4=TWIN
5=HARV
6=PROTO
7=PROTOAI
8=WRECKER
9=CARRIER
10=OUTPOST
11=BOMB
12=BOAT
13=SUB
14=IFV
15=APC

[SuperWeaponTypes]
0=CurtainSW
1=SphereSW
2=LiftSW
3=MinerSW
4=StormSW

; Fires on its own, at the enemy.
[StormSW]
Type=LightningStorm

; Team-cast (Ares: fired only by script action 55 on its SW.Group).
[CurtainSW]
Type=IronCurtain
SW.AITargeting=IronCurtain
SW.Group=0

; The AI's Chronosphere, used by the chrono assault.
[SphereSW]
Type=ChronoSphere

; Team-cast but barred to the AI.
[LiftSW]
Type=ChronoSphere
SW.AITargeting=IronCurtain
SW.Group=14
SW.AllowAI=no

; Delivers only harvesters, so it is cast at home.
[MinerSW]
Type=UnitDelivery
SW.AITargeting=IronCurtain
SW.Group=17
Deliver.Types=HARV

[AircraftTypes]
0=JET

[JET]
TechLevel=5
Owner=Alpha
Prerequisite=AIRF
AirportBound=yes
Cost=1200
Strength=200
Armor=jet
Primary=Cannon

; A player's unit; Ares hands the AI its twin instead.
[PROTO]
TechLevel=5
Owner=Alpha
Prerequisite=ANYWEAP,RADR
Convert.HumanToComputer=PROTOAI
Cost=3000
Strength=200
Armor=light
Primary=Howitzer

[PROTOAI]
TechLevel=5
Owner=Alpha
Prerequisite=ANYWEAP,RADR,LOCK
Cost=3000
Strength=200
Armor=light
Primary=Howitzer

; A hero that wrecks buildings.
[WRECKER]
TechLevel=8
Owner=Alpha
Prerequisite=ANYWEAP,LABS
BuildLimit=1
Cost=3000
Strength=2000
Armor=heavy
Primary=Demolish

; An armed, open-topped carrier.
[CARRIER]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP
Passengers=4
SizeLimit=1
OpenTopped=yes
Cost=700
Strength=300
Armor=light
Primary=Cannon

; Unfolds into a building.
[OUTPOST]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP
DeploysInto=POWR
Cost=1500
Strength=400
Armor=medium
Primary=Rifle

; A gunboat hurts the shore; a submarine only other hulls.
[BOAT]
TechLevel=2
Owner=Alpha
Prerequisite=DOCK
Naval=yes
Cost=1000
Strength=600
Armor=heavy
Primary=Cannon

[SUB]
TechLevel=2
Owner=Alpha
Prerequisite=DOCK
Naval=yes
Cost=900
Strength=400
Armor=heavy
Primary=Torpedo

; Blows itself up on its target.
[BOMB]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP
Cost=1000
Strength=200
Armor=light
Primary=Blast

[GI]
TechLevel=1
Owner=Alpha
Prerequisite=PILE
Cost=200
Strength=125
Occupier=yes
Primary=Rifle

; Anti-armour infantry: in an IFV's seat it fits the cannon.
[BAZ]
TechLevel=1
Owner=Alpha
Prerequisite=PILE
Cost=300
Strength=100
Primary=Bazooka
IFVMode=1

; Takes its weapon from its passenger: the rifle, or the cannon.
[IFV]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP
Passengers=1
SizeLimit=1
Gunner=yes
WeaponCount=2
Weapon1=Rifle
Weapon2=Cannon
Cost=600
Strength=200
Armor=light

; A closed carrier: its passengers fight on foot.
[APC]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP
Passengers=3
SizeLimit=1
Cost=500
Strength=300
Armor=light
Primary=Rifle

; Plants a bomb that sticks to buildings only.
[SAPPER]
TechLevel=1
Owner=Alpha
Prerequisite=PILE
Cost=400
Strength=100
Primary=Plant

[ENG]
TechLevel=1
Owner=Alpha
Prerequisite=PILE
Engineer=yes
Cost=500
Strength=75

; Enters enemy buildings.
[SPY]
TechLevel=5
Owner=Alpha
Prerequisite=PILE,RADR
Infiltrate=yes
Agent=yes
Cost=1000
Strength=75

[PSI]
TechLevel=5
Owner=Alpha
Prerequisite=PILE,RADR
Cost=1000
Strength=150
Primary=Control

[MEDIC]
TechLevel=1
Owner=Alpha
Prerequisite=PILE
Cost=300
Strength=100
Primary=Heal

[HERO]
TechLevel=8
Owner=Alpha
Prerequisite=PILE,LABS
BuildLimit=1
Cost=2000
Strength=250
Primary=HeroGun

[TANK]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP
Cost=900
Strength=500
Armor=heavy
Primary=Cannon

[FLAK]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP
Cost=600
Strength=200
Armor=light
Primary=FlakGun

[ARTY]
TechLevel=5
Owner=Alpha
Prerequisite=ANYWEAP,RADR
Cost=1000
Strength=200
Armor=light
Primary=Howitzer

[MCV]
TechLevel=5
Owner=Alpha
Prerequisite=ANYWEAP
Cost=3000
Strength=1000
Armor=heavy
DeploysInto=YARD

[TWIN]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP,LOCK
Cost=800
Strength=450
Armor=medium
Primary=Cannon

[HARV]
TechLevel=2
Owner=Alpha
Prerequisite=ANYWEAP
Harvester=yes
Cost=1400
Strength=600
Armor=heavy

[Rifle]
Damage=15
ROF=20
Range=5
Projectile=Bullet
Warhead=SA

[Control]
Damage=1
ROF=60
Range=6
Projectile=Bullet
Warhead=Psi

[Psi]
MindControl=yes
Verses=100%,100%,100%,100%,100%,100%,0%,0%,0%,0%,0%

[Heal]
Damage=-50
ROF=60
Range=2
Projectile=Bullet
Warhead=Mend

[HeroGun]
Damage=100
ROF=30
Range=6
Projectile=Bullet
Warhead=SA

[Bazooka]
Damage=40
ROF=50
Range=5
Projectile=Bullet
Warhead=AP

[Cannon]
Damage=90
ROF=50
Range=5.75
Projectile=Bullet
Warhead=AP

[FlakGun]
Damage=40
ROF=20
Range=6
Projectile=FlakShell
Warhead=Flak

[Howitzer]
Damage=150
ROF=100
Range=12
MinimumRange=3
Projectile=Lob
Warhead=HE

[Bullet]
AG=yes

[FlakShell]
AA=yes
AG=no

[Lob]
Arcing=yes

[SA]
Verses=100%,80%,50%,10%,10%,10%,5%,5%,5%,100%,100%

[Mend]
Verses=100%,100%,100%,0%,0%,0%,0%,0%,0%,0%,0%

[AP]
Verses=10%,10%,10%,100%,100%,100%,50%,50%,50%,100%,100%

; Anti-air names the aircraft armour; vehicles take nothing.
[Flak]
Verses=50%,50%,50%,0%,0%,0%,0%,0%,0%,0%,0%
Versus.jet=100%

[Demolish]
Damage=300
ROF=90
Range=4
Projectile=Bullet
Warhead=Wreck

[Wreck]
Verses=10%,10%,10%,30%,30%,30%,200%,200%,200%,0%,0%

[Torpedo]
Damage=100
ROF=60
Range=7
Projectile=Bullet
Warhead=Hull

[Hull]
Verses=0%,0%,0%,100%,100%,100%,0%,0%,0%,0%,0%

[Plant]
Damage=1
ROF=120
Range=1.5
Projectile=Bullet
Warhead=Stick

[Stick]
IvanBomb=yes
Verses=0%,0%,0%,0%,0%,0%,1%,1%,1%,0%,0%

[Blast]
Damage=400
ROF=100
Range=1.5
Projectile=Bullet
Warhead=Wreck
Suicide=yes

[HE]
Verses=80%,80%,80%,80%,80%,80%,100%,100%,100%,100%,100%
"""


# The tier each of the country's buildings belongs to.
TIERS = {
    "YARD": 1,
    "POWR": 1,
    "PILE": 1,
    "WEAP": 1,
    "DOCK": 1,
    "RADR": 2,
    "AIRF": 2,
    "LABS": 3,
    "SILO": 3,
}
PREFIX = "Alpha - Mental "
ENHANCE = Path(__file__).resolve().parents[1] / "overlays" / "enhance"


@dataclass(frozen=True, slots=True)
class Fielded:
    """The fixture's plan, with its objects at hand by ID and label."""

    plan: AIPlan
    teams: Mapping[str, TeamType]
    named: Mapping[str, TeamType]
    scripts: Mapping[str, ScriptType]
    triggers: Mapping[str, Trigger]
    crews: Mapping[str, tuple[tuple[int, str], ...]]

    @classmethod
    def of(cls, plan: AIPlan) -> Fielded:
        """Index a plan's objects."""
        return cls(
            plan=plan,
            teams={team.id: team for team in plan.teams},
            named={team.name.removeprefix(PREFIX): team for team in plan.teams},
            scripts={script.id: script for script in plan.scripts},
            triggers={trigger.id: trigger for trigger in plan.triggers},
            crews={force.id: force.members for force in plan.task_forces},
        )

    def crew(self, team: TeamType) -> tuple[tuple[int, str], ...]:
        """A team's members, as its task force lists them."""
        return self.crews[team.task_force]

    def units(self, team: TeamType) -> set[str]:
        """The unit types in a team."""
        return {unit for _, unit in self.crew(team)}

    def lines(self, team: TeamType) -> Lines:
        """A team's script."""
        return self.scripts[team.script].lines

    def calls(self, team: TeamType) -> list[Trigger]:
        """The triggers that lead with a team."""
        return [t for t in self.plan.triggers if t.team == team.id]


@pytest.fixture(scope="module")
def rules() -> IniData:
    return IniData.parse(RULES)


@pytest.fixture(scope="module")
def catalog(rules: IniData) -> Catalog:
    return build_catalog(rules)


@pytest.fixture(scope="module")
def plan(catalog: Catalog) -> AIPlan:
    return plan_ai(catalog)


@pytest.fixture(scope="module")
def fielded(plan: AIPlan) -> Fielded:
    return Fielded.of(plan)


@pytest.fixture(scope="module")
def option(plan: AIPlan) -> IniData:
    return IniData.parse(render_option_fragment(plan))


def attacks_by_phobos(lines: Lines) -> bool:
    """Whether a script has a Phobos attack line (10000 to 10049)."""
    return any(10000 <= action < 10050 for action, _ in lines)


# --- Reading the rules ------------------------------------------------


def test_repeated_names_follow_the_engine() -> None:
    # Ares makes the last copy of a key win; sections merge.
    data = IniData.parse("[A]\nkey=1\n[a]\nKEY=2 ; note\nother=x\n")
    assert data.get("a", "Key") == "2"
    assert data.get("A", "other") == "x"
    assert data.keys("A") == ("key", "other")


def test_a_registry_keeps_each_type_once() -> None:
    data = IniData.parse("[VehicleTypes]\n0=TANK\n1=FLAK\n2=tank\n")
    assert data.type_list("VehicleTypes") == ("TANK", "FLAK")
    assert split_list(" a, ,b ") == ("a", "b")


def test_values_read_as_the_engine_reads_them() -> None:
    data = IniData.parse(
        "[U]\nNaval=yes\nCloak=FALSE\nEmpty=\nCost=1200\nSpeed=7.5\n"
        "Share=40%\nArmor=Heavy\nOwner=A, B ,\n"
    )
    assert data.flag("U", "Naval")
    assert not data.flag("U", "Cloak")
    # An absent or empty flag takes the default.
    assert data.flag("U", "Empty", default=True)
    assert data.flag("U", "Missing", default=True)
    assert data.integer("U", "Cost") == 1200
    assert data.integer("U", "Speed") == 7
    assert data.number("U", "Share") == 40
    assert data.number("U", "Missing", 1.5) == 1.5
    assert data.token("U", "Armor") == "heavy"
    assert data.token("U", "Missing", "none") == "none"
    assert data.listed("U", "Owner") == ("A", "B")
    assert data.listed("U", "Missing") == ()


def test_roles_come_from_weapons_and_hulls(catalog: Catalog) -> None:
    units = catalog.units
    assert units["tank"].has(Role.MBT, Role.ANTI_ARMOUR)
    assert units["gi"].has(Role.ANTI_INFANTRY)
    assert units["flak"].has(Role.AA, Role.AA_ONLY)
    assert units["arty"].has(Role.ARTILLERY, Role.SIEGE)
    assert units["medic"].has(Role.HEALER)
    assert units["hero"].has(Role.HERO)
    assert units["mcv"].has(Role.MCV)
    assert units["bomb"].has(Role.CHARGER)


def test_anti_air_is_judged_against_aircraft_armour(catalog: Catalog) -> None:
    # Flak does nothing to vehicles; it hits the jet's own armour.
    assert catalog.units["flak"].has(Role.AA)


def test_a_country_fields_units_by_tier(catalog: Catalog) -> None:
    (country,) = catalog.countries
    assert country.side == 1
    assert country.mcv == "MCV"
    assert country.construction_yard == "YARD"
    assert country.units["tank"] == 1
    assert country.units["arty"] == 2
    assert country.units["hero"] == 3
    assert country.gates == {2: "RADR", 3: "LABS"}
    assert country.factories[Factory.WAR_FACTORY] == "WEAP"


def test_the_ai_fields_units_behind_a_lock_no_house_builds(catalog: Catalog) -> None:
    # The AI skips unit prerequisites, so an AI-only twin is its own.
    (country,) = catalog.countries
    assert country.units["twin"] == 1


def test_superweapons_sort_into_team_casts(catalog: Catalog) -> None:
    (country,) = catalog.countries
    assert country.front_casts == (0,)
    assert country.base_casts == (17,)
    assert country.chronosphere


def test_the_map_has_tech_and_bridge_huts(catalog: Catalog) -> None:
    assert catalog.tech_buildings == ("DERRICK",)
    assert catalog.bridge_huts == ("HUT",)


# --- Gates ------------------------------------------------------------


def test_a_gate_reads_as_the_engine_compares() -> None:
    assert Gate.house_owns("LABS") == Gate(
        Condition.HOUSE_OWNS, "LABS", 1, Comparison.AT_LEAST
    )
    assert Gate.house_lacks("LABS").comparison is Comparison.LESS
    assert Gate.enemy_owns("ARTY", 2).amount == 2
    assert Gate.neutral_owns("HUT").condition is Condition.NEUTRAL_OWNS
    # A gate that counts nothing names no subject.
    assert Gate.enemy_credits_under(500).subject is None


def test_triggers_hold_each_tier_back(fielded: Fielded) -> None:
    triggers = fielded.triggers
    assert triggers["MNTTR0101AL-G"].gate == Gate.house_lacks("RADR")
    assert triggers["MNTTR0103AL-G"].gate == Gate.house_owns("LABS")
    assert triggers["MNTTR9900AL-G"].gate == Gate.house_lacks("YARD")


def test_a_tier_gate_fields_nothing_above_its_tier(
    catalog: Catalog, fielded: Fielded
) -> None:
    # The AI skips unit prerequisites: the building a trigger waits for
    # is all that keeps a unit back until its tech stands.
    (country,) = catalog.countries
    for trigger in fielded.plan.triggers:
        gate = trigger.gate
        if gate.condition is not Condition.HOUSE_OWNS or gate.subject is None:
            continue
        # A building of the map (tech) unlocks nothing: tier 1.
        own = gate.comparison is Comparison.AT_LEAST
        cap = TIERS.get(gate.subject, 1) if own else 1
        for team in filter(None, (trigger.team, trigger.support)):
            for unit in fielded.units(fielded.teams[team]):
                assert country.units[unit.lower()] <= cap, (trigger.name, unit)


# --- Squads -----------------------------------------------------------


def test_a_line_mixes_roles_and_its_front_leads(fielded: Fielded) -> None:
    tier_1 = fielded.crew(fielded.teams["MNTTT0101AL-G"])
    assert tier_1[0] == (4, "TANK")
    assert {unit for _, unit in tier_1} >= {"TANK", "GI", "FLAK"}
    tier_3 = fielded.units(fielded.teams["MNTTT0103AL-G"])
    assert {"ARTY", "HERO", "MEDIC"} <= tier_3
    leadership = fielded.plan.leadership
    assert leadership["TANK"] > leadership["HERO"] > leadership["GI"]


def test_variants_field_second_choices(fielded: Fielded) -> None:
    best = fielded.crew(fielded.teams["MNTTT0102AL-G"])
    second = fielded.crew(fielded.teams["MNTTT0112AL-G"])
    assert best != second


def test_a_grand_line_is_two_lines_as_one_team(fielded: Fielded) -> None:
    # Teams leave as they fill, and a base's defences take them one at
    # a time; a grand line doubles every seat of its tier's line and
    # goes in as one team, one at a time.
    line = fielded.crew(fielded.named["Line T2"])
    grand = fielded.named["Grand Line T2"]
    assert fielded.crew(grand) == tuple((2 * count, unit) for count, unit in line)
    assert grand.max_teams == 1
    assert grand.script == fielded.named["Line T2"].script
    assert "Grand Line T1" not in fielded.named


def test_task_forces_stay_within_engine_limits(plan: AIPlan) -> None:
    assert all(len(force.members) <= 6 for force in plan.task_forces)
    ids = [force.id for force in plan.task_forces] + [team.id for team in plan.teams]
    assert all(len(identifier) <= 24 for identifier in ids)
    assert len(set(ids)) == len(ids)


def test_player_versions_give_way_to_ai_twins(plan: AIPlan) -> None:
    used = {unit for force in plan.task_forces for _, unit in force.members}
    assert "PROTO" not in used
    assert "PROTOAI" in used


def test_every_combat_unit_takes_the_field(catalog: Catalog, plan: AIPlan) -> None:
    used = {unit.lower() for force in plan.task_forces for _, unit in force.members}
    (country,) = catalog.countries
    jobs = {Role.HARVESTER, Role.MCV, Role.PLAYER_VERSION}
    for name in country.units:
        unit = catalog.units[name]
        if unit.roles & {Role.GUN, Role.EFFECT} and not unit.roles & jobs:
            assert name in used, name


def test_airfield_bound_strikes_fit_the_pads(fielded: Fielded, option: IniData) -> None:
    # An aircraft with no free pad is never built: the tier-2 and tier-3
    # strikes, one team each, share one airfield's four pads.
    strike = fielded.teams["MNTTT1302AL-G"]
    assert fielded.crew(strike) == ((2, "JET"),)
    assert strike.max_teams == 1
    # Mental AI clones every unit per extra factory; a clone has no pad.
    assert option.get("JET", "ForbidParallelAIQueues") == "true"
    assert option.get("TANK", "ForbidParallelAIQueues") is None


def test_occupiers_garrison_buildings(fielded: Fielded) -> None:
    assert fielded.crew(fielded.named["Garrison"]) == ((5, "GI"),)


def test_a_counter_squad_is_all_hunters(fielded: Fielded) -> None:
    # The highest-rated member picks a Phobos line's targets: an escort
    # that outranked the hunters would pick with the wrong weapon.
    hunts = [
        fielded.teams[trigger.team]
        for trigger in fielded.plan.triggers
        if trigger.gate.condition is Condition.ENEMY_OWNS
        and any(
            action == 10013 for action, _ in fielded.lines(fielded.teams[trigger.team])
        )
    ]
    assert hunts
    assert all(len(fielded.crew(team)) == 1 for team in hunts)


def test_a_walking_bomb_charges_on_vanilla_quarries(fielded: Fielded) -> None:
    # It joins no line: its one shot is not a tank's firepower.
    assert "BOMB" not in fielded.units(fielded.teams["MNTTT0101AL-G"])
    charge = fielded.named["Charge BOMB"]
    assert fielded.crew(charge) == ((2, "BOMB"),)
    # Phobos gives a leader with no undeployed weapon no target.
    assert not attacks_by_phobos(fielded.lines(charge))
    assert (0, 6) in fielded.lines(charge)
    assert charge.conduct.suicide
    curtain = fielded.named["Curtain BOMB"]
    assert (55, 0) in fielded.lines(curtain)
    (call,) = fielded.calls(curtain)
    assert call.gate.condition is Condition.IRON_CURTAIN_CHARGED


def test_a_bomb_planter_goes_for_what_its_bomb_sticks_to(fielded: Fielded) -> None:
    # The planting does next to no damage; the warhead's Verses still
    # say which classes it touches. Phobos would judge the weapon and
    # find the planter no target, so it takes vanilla quarries.
    lines = fielded.lines(fielded.named["Bombers SAPPER"])
    assert {(0, 9), (0, 6)} <= set(lines)
    assert not attacks_by_phobos(lines)


def test_a_wrecker_hero_goes_for_the_yards(fielded: Fielded) -> None:
    assert (10001, 26) in fielded.lines(fielded.named["Hero WRECKER"])


def test_a_carrier_rides_out_with_each_kind_of_rider(fielded: Fielded) -> None:
    # MO's own AI seated a dozen kinds of infantry in an IFV. A carrier
    # takes the rider that hurts each class of target most aboard: the
    # bazooka against vehicles, the rifle against infantry. Then both
    # side by side where a carrier seats two, and a hero with the main
    # crew in the other carriers.
    mounted = [name for name in fielded.named if name.startswith("Mounted CARRIER")]
    assert mounted == [
        "Mounted CARRIER BAZ",
        "Mounted CARRIER GI",
        "Mounted CARRIER BAZ+GI",
        "Mounted CARRIER HERO+BAZ",
    ]
    # As many carriers as a line has front tanks, two riders in each.
    crews = {name: fielded.crew(fielded.named[name]) for name in mounted}
    assert crews["Mounted CARRIER BAZ"] == ((4, "CARRIER"), (8, "BAZ"))
    assert crews["Mounted CARRIER BAZ+GI"] == ((4, "CARRIER"), (4, "BAZ"), (4, "GI"))
    assert crews["Mounted CARRIER HERO+BAZ"] == (
        (4, "CARRIER"),
        (1, "HERO"),
        (7, "BAZ"),
    )
    assert fielded.named["Mounted CARRIER HERO+BAZ"].max_teams == 1


def test_a_gunner_vehicle_is_judged_by_the_weapon_its_rider_gives(
    fielded: Fielded, catalog: Catalog
) -> None:
    # The infantry in an IFV's seat picks its weapon (`IFVMode` n fires
    # `Weapon` n + 1): the bazooka fits the cannon, the rifleman leaves
    # the rifle. An IFV seats one, so it has no mixed crew.
    ifv, baz, gi = (catalog.units[name] for name in ("ifv", "baz", "gi"))
    assert ifv.has(Role.GUNNER)
    assert ifv.mounts[baz.seat_mode].vehicle > ifv.mounts[gi.seat_mode].vehicle
    assert ifv.mounts[gi.seat_mode].infantry > ifv.mounts[baz.seat_mode].infantry
    mounted = [name for name in fielded.named if name.startswith("Mounted IFV")]
    assert mounted == ["Mounted IFV BAZ", "Mounted IFV GI", "Mounted IFV HERO+BAZ"]
    assert fielded.crew(fielded.named["Mounted IFV BAZ"]) == ((4, "IFV"), (4, "BAZ"))


def test_riders_that_cannot_fire_from_inside_get_out_at_the_gate(
    fielded: Fielded,
) -> None:
    # An IFV fights with its rider's weapon and an open-topped carrier
    # lets its riders fire, so they stay aboard; in a closed carrier
    # they would ride to their deaths unused. Vanilla 8,0 sets them
    # down at the nearer gathering point and keeps both in the team.
    aboard = fielded.lines(fielded.named["Mounted CARRIER BAZ"])
    assert aboard == fielded.lines(fielded.named["Mounted IFV BAZ"])
    assert (10103, 0) in aboard
    assert (8, 0) not in aboard
    on_foot = fielded.lines(fielded.named["Mounted APC BAZ"])
    board, gate, out, attack = (
        on_foot.index(line) for line in ((10103, 0), (53, -10), (8, 0), (0, 7))
    )
    assert board < gate < out < attack
    # Every team gets out at the nearer point: no roll decides it.
    assert (16003, 50) not in on_foot


def test_deployers_unfold_at_the_enemy_gate(fielded: Fielded) -> None:
    assert (9, 0) in fielded.lines(fielded.named["Forward OUTPOST"])


def test_a_fleet_goes_for_the_shore_and_hunters_wait_for_prey(fielded: Fielded) -> None:
    # A ship that cannot hurt a building leads no fleet at the shore.
    navy = fielded.named["Navy T1"]
    assert fielded.units(navy) == {"BOAT"}
    # Vanilla quarries: the engine gives each ship a target it can hit.
    assert (0, 1) in fielded.lines(navy)
    assert not attacks_by_phobos(fielded.lines(navy))
    # Hunters form only while the enemy owns a shipyard: with nothing
    # to hunt they would mark success unfought and gain weight for it.
    (call,) = fielded.calls(fielded.named["Flotilla SUB"])
    assert call.gate == Gate.enemy_owns("DOCK")


# --- Conduct ----------------------------------------------------------


def test_each_kind_of_team_behaves_to_its_job(fielded: Fielded) -> None:
    direct = fielded.teams["MNTTT0102AL-G"].conduct
    flank = fielded.teams["MNTTT0202AL-G"].conduct
    # The direct line drives in; the flank routes round the defences.
    assert direct.aggressive
    assert not direct.avoid_threats
    assert flank.avoid_threats
    assert flank.enemy_only
    assert fielded.named["Capture"].conduct.suicide
    watch = fielded.named["Base Watch T1"].conduct
    assert watch.base_defense
    assert watch.reinforce
    assert watch.annoyance


def test_a_mind_controller_keeps_what_it_takes(fielded: Fielded) -> None:
    line = fielded.teams["MNTTT0102AL-G"]
    assert (2, "PSI") in fielded.crew(line)
    assert line.conduct.mind_control is MindControl.JOIN_TEAM
    # A squad without one decides nothing.
    raid = fielded.teams["MNTTT0901AL-G"]
    assert raid.conduct.mind_control is MindControl.DONT_CARE


def test_only_aircraft_of_one_type_take_another_teams_members(
    fielded: Fielded, catalog: Catalog
) -> None:
    # A team of higher priority recruits out of teams of lower
    # priority, marching and fighting ones included: in play, lines
    # stripped every raid before it set out, and a probe team emptied a
    # team at the enemy's gate while the same units stood at home. So
    # teams have one priority, but for a squadron of one aircraft type
    # that answers a superweapon: it retasks the craft that fly now.
    data = IniData.parse(render_ai_fragment(fielded.plan))
    urgent = [t for t in fielded.plan.teams if data.get(t.id, "Priority") != "5"]
    assert [team.name.removeprefix(PREFIX) for team in urgent] == ["Air Snipe SILO"]
    (snipe,) = urgent
    assert data.get(snipe.id, "Priority") == "6"
    assert fielded.crew(snipe) == ((2, "JET"),)
    assert catalog.units["jet"].has(Role.AIRBORNE)
    assert [call.gate for call in fielded.calls(snipe)] == [Gate.enemy_owns("SILO")]
    # Vanilla 46 on the silo, the nearest of the enemy's, as MO's own.
    lines = fielded.lines(snipe)
    assert lines.index((46, (2 << 16) | 11)) < lines.index((49, 0))
    assert not attacks_by_phobos(lines)


# --- Scripts ----------------------------------------------------------


def test_lines_cast_at_the_front_and_the_watch_at_home(fielded: Fielded) -> None:
    line_team = fielded.teams["MNTTT0103AL-G"]
    assert line_team.script == "MNTSC1000AL-G"
    line = fielded.lines(line_team)
    assert line.index((55, 0)) < line.index((0, 7))
    watch = fielded.lines(fielded.named["Base Watch T3"])
    assert (55, 17) in watch
    assert (55, 14) not in line + watch


def test_random_branches_jump_past_their_blocks(plan: AIPlan) -> None:
    # Phobos 16003 skips the vanilla jump after it with a chance, so the
    # block between runs with that chance; the jump must land past it.
    for script in plan.scripts:
        lines = script.lines
        for index, (action, _chance) in enumerate(lines):
            if action != 16003:
                continue
            jump, target = lines[index + 1]
            if jump == 6:
                assert index + 2 < target <= len(lines)


def test_a_branch_skips_exactly_its_block(fielded: Fielded) -> None:
    # The mounted line boards before it gathers: its optional second
    # gathering sits one line later than a plain line's, and the jump
    # over it must count that line.
    lines = fielded.lines(fielded.named["Mounted CARRIER BAZ"])
    chance = lines.index((16003, 50))
    assert lines[chance + 1] == (6, chance + 6)
    assert lines[chance + 2 : chance + 5] == ((16001, 60), (53, -10), (16002, 0))


def test_success_is_marked_when_the_first_objective_ends(fielded: Fielded) -> None:
    # A team that is wiped out breaking in never runs 49, and its
    # trigger loses weight; one still alive after the break-in gains.
    line = fielded.lines(fielded.teams["MNTTT0101AL-G"])
    defences, success, raze = (line.index(x) for x in ((0, 7), (49, 0), (0, 2)))
    assert defences < success < raze
    assert line[defences + 1] == (16002, 0)
    assert line[defences - 1][0] == 16001
    strike = fielded.lines(fielded.teams["MNTTT1302AL-G"])
    assert strike.index((49, 0)) < len(strike) - 3


def test_the_chrono_assault_waits_for_the_sphere(fielded: Fielded) -> None:
    assault = fielded.teams["MNTTT3501AL-G"]
    (call,) = fielded.calls(assault)
    assert call.gate == Gate(Condition.CHRONOSPHERE_CHARGED)
    assert fielded.units(assault) == {"TANK", "ARTY", "FLAK"}


# --- Triggers ---------------------------------------------------------


def test_notable_enemy_units_raise_counters(plan: AIPlan) -> None:
    # The house waits until its enemy owns some of a costly unit, then
    # hunts every unit of that armour through a Phobos target list.
    amounts = {
        trigger.gate.subject: trigger.gate.amount
        for trigger in plan.triggers
        if trigger.gate.condition is Condition.ENEMY_OWNS
    }
    assert amounts["ARTY"] == 2
    assert amounts["HERO"] == 1
    assert "GI" not in amounts
    rules_fragment = IniData.parse(render_rules_fragment(plan))
    lists = [
        rules_fragment.get("AITargetTypes", str(index)) or ""
        for index in range(len(plan.target_lists))
    ]
    assert any("ARTY" in units for units in lists)


def test_enemy_airfields_raise_the_sky_guard(fielded: Fielded) -> None:
    guards = fielded.calls(fielded.named["Sky Guard"])
    assert [call.gate for call in guards] == [Gate.enemy_owns("AIRF")]


def test_engineers_wait_for_untaken_tech_and_broken_bridges(fielded: Fielded) -> None:
    neutral = {
        trigger.gate.subject: trigger
        for trigger in fielded.plan.triggers
        if trigger.gate.condition is Condition.NEUTRAL_OWNS
    }
    assert set(neutral) == {"DERRICK", "HUT"}
    assert (10001, 11) in fielded.lines(fielded.teams[neutral["DERRICK"].team])
    assert (10001, 37) in fielded.lines(fielded.teams[neutral["HUT"].team])
    assert all(trigger.steady for trigger in neutral.values())
    # What they took gets a guard, raised once the house owns some.
    (guard,) = fielded.calls(fielded.named["Tech Guard"])
    assert guard.gate == Gate.house_owns("DERRICK")


def test_an_agent_tries_under_a_clock_and_gives_up(fielded: Fielded) -> None:
    # An engineer or a spy that cannot reach its building must not hold
    # its team, and its place under the team cap, for good: each try
    # runs under a Phobos timer, and after a few the team ends.
    for name, strike in (
        ("Capture", (10001, 11)),
        ("Bridge Repair", (10001, 37)),
        ("Spy vs Power", (10001, 9)),
    ):
        lines = fielded.lines(fielded.named[name])
        tries = [index for index, line in enumerate(lines) if line == strike]
        assert len(tries) == 3
        assert all(lines[index + 1] == (16002, 0) for index in tries)
        assert not any(action == 6 for action, _ in lines)
    # A spy rolls whether to go at all, inside the clock: the timer
    # line must not be the one the roll skips.
    spy = fielded.lines(fielded.named["Spy vs Power"])
    assert spy[:3] == ((16001, 120), (16003, 30), (10001, 9))


def test_a_guard_the_enemy_calls_out_stands_down(fielded: Fielded) -> None:
    # The sky guard answers an enemy airfield. It holds the base for a
    # spell and ends, so its members and its place under the team cap
    # come back and its trigger decides again; the base watch is the
    # standing guard, and loops.
    sky = fielded.lines(fielded.named["Sky Guard"])
    assert sky == ((54, 0), (10100, 600))
    watch = fielded.lines(fielded.named["Base Watch T1"])
    assert watch[-1] == (6, 2)


def test_a_hero_is_set_down_by_an_enemy_superweapon(fielded: Fielded) -> None:
    # MO's own Mental AI flies Tanya at a nuclear silo. The hero rides
    # the side's transport, leads once on the ground, and the first
    # superweapon it wrecks is the success.
    drop = fielded.named["Hero Drop vs SILO"]
    assert fielded.units(drop) == {"IFV", "HERO"}
    assert drop.conduct.transports_return
    assert [call.gate for call in fielded.calls(drop)] == [Gate.enemy_owns("SILO")]
    # Vanilla lines name the silo by its index among the building
    # types (11 in the fixture), the nearest of the enemy's (2 << 16).
    # Phobos would keep the transport as leader after it has gone home,
    # and it outranks the hero: no Phobos line may pick the targets.
    silo = (2 << 16) | 11
    lines = fielded.lines(drop)
    load, ride, unload, wreck, success = (
        lines.index(line) for line in ((14, 0), (47, silo), (8, 2), (46, silo), (49, 0))
    )
    assert load < ride < unload < wreck < success
    assert fielded.plan.leadership["IFV"] > fielded.plan.leadership["HERO"]
    assert not attacks_by_phobos(lines)


def test_a_transport_sets_fighters_down_in_the_enemy_base(fielded: Fielded) -> None:
    # MO's Borillo rushes: a transport full of the infantry that wreck
    # buildings rides in beside a class of building and they get out.
    # On the ground they take vanilla quarries: Phobos would pick their
    # targets with the weapon of the transport that has left.
    rush = fielded.named["Rush vs Factory"]
    assert fielded.crew(rush) == ((4, "BAZ"), (1, "CARRIER"))
    assert rush.conduct.transports_return
    lines = fielded.lines(rush)
    ride, out, wreck, success = (
        lines.index(line) for line in ((10050, 6), (8, 2), (0, 6), (49, 0))
    )
    assert ride < out < wreck < success
    assert not attacks_by_phobos(lines)
    # A construction yard is a factory to the engine's quarries.
    assert (0, 6) in fielded.lines(fielded.named["Rush vs Yard"])
    # Saboteurs ride the same way: MO's Ivans by Borillo, SEALs by air.
    sabotage = fielded.named["Sabotage vs Power"]
    assert fielded.units(sabotage) == {"IFV", "SAPPER"}
    assert sabotage.script == fielded.named["Rush vs Power"].script
    # Engineers enter what they are set down beside, as before.
    drop = fielded.named["Engineer Drop vs Power"]
    assert fielded.crew(drop) == ((1, "CARRIER"), (2, "ENG"))
    assert (10001, 9) in fielded.lines(drop)


def test_defenders_are_posted_at_the_houses_own_buildings(fielded: Fielded) -> None:
    # MO's own AI kept its defenders beside its turrets (167 teams). A
    # post is the watch's crew standing by the nearest own building of
    # a class; it is a base-defence team, so posts and watches share
    # the engine's cap on those and add no standing team.
    watch = fielded.named["Base Watch T2"]
    for name, target in (("Defence", 7), ("Factory", 6), ("Power", 9)):
        post = fielded.named[f"{name} Post T2"]
        assert fielded.crew(post) == fielded.crew(watch)
        assert post.conduct.base_defense
        assert fielded.lines(post) == ((10053, target), (10100, 60), (6, 1))
        assert [call.gate for call in fielded.calls(post)] == [
            call.gate for call in fielded.calls(watch)
        ]
    # The tech guard is a post at what the engineers took.
    assert fielded.lines(fielded.named["Tech Guard"])[0] == (10053, 11)


def test_a_deployer_also_digs_in_at_home(fielded: Fielded) -> None:
    emplace = fielded.named["Emplace OUTPOST"]
    assert fielded.crew(emplace) == ((2, "OUTPOST"),)
    assert fielded.lines(emplace) == ((10053, 7), (9, 0), (49, 0))


def test_two_team_calls_pair_their_teams(fielded: Fielded) -> None:
    # Weights are settled per Team1 type: the call leads with a copy of
    # its squad's team, so it learns apart from the line's own trigger.
    pincer = fielded.triggers["MNTTR1202AL-G"]
    assert (pincer.team, pincer.support) == ("MNTTT1202AL-G", "MNTTT0202AL-G")
    lead, line = fielded.named["Pincer T2"], fielded.teams["MNTTT0102AL-G"]
    assert lead.id == pincer.team
    assert (lead.task_force, lead.script) == (line.task_force, line.script)
    blackout = fielded.triggers["MNTTR3802AL-G"]
    assert blackout.gate == Gate(Condition.ENEMY_POWER_SHORT)
    assert blackout.support == "MNTTT0702AL-G"


def test_the_team_cap_keeps_the_wait_for_production_short(option: IniData) -> None:
    # A house always stands at the cap, and a new team waits while
    # every older one fills: the cap is that wait, in teams. A squad of
    # vehicles alone is empty all that while, and must not be dissolved
    # before its turn.
    assert option.get("General", "TotalAITeamCap") == "40,30,20"
    assert option.integer("General", "DissolveUnfilledTeamDelay") == 30000


def test_a_long_gun_keeps_its_distance(catalog: Catalog, option: IniData) -> None:
    # Phobos KeepRange makes an AI firer back away from a target that
    # comes nearer while its weapon reloads. The howitzer reaches 12
    # cells and keeps 11, a cell to fire from, which is beyond the
    # tank cannon's 5.75; guns no tank is outranged by keep none.
    assert stand_offs(catalog) == {"Howitzer": 11.0}
    assert option.number("Howitzer", "KeepRange") == 11.0
    assert option.flag("General", "KeepRange.AllowAI")
    assert option.get("Cannon", "KeepRange") is None


def test_an_idle_ai_unit_looks_for_targets_twice_as_often(option: IniData) -> None:
    # A player's units keep the rules' delays: Phobos reads these keys
    # for AI houses only.
    assert option.integer("General", "AINormalTargetingDelay") == 14
    assert option.integer("General", "AIGuardAreaTargetingDelay") == 18
    assert option.integer("General", "AIAttackMoveTargetingDelay") == 14


def test_a_trigger_learns_only_what_its_script_reports(option: IniData) -> None:
    def weights(trigger: str) -> tuple[float, float, float]:
        fields = (option.get("AITriggerTypes", trigger) or "").split(",")
        return float(fields[7]), float(fields[8]), float(fields[9])

    # A line marks success: its weight moves between half and double.
    weight, low, high = weights("MNTTR0101AL-G")
    assert (low, high) == (weight / 2, weight * 2)
    # A garrison is spent in its building either way: the weight stays.
    weight, low, high = weights("MNTTR2100AL-G")
    assert low == high == weight


# --- The fragments ----------------------------------------------------


def test_the_option_fragment_gates_and_enables_every_trigger(
    plan: AIPlan, option: IniData
) -> None:
    assert option.get("Basic", "IgnoreGlobalAITriggers") == "yes"
    for trigger in plan.triggers:
        assert option.get("AITriggerTypesEnable", trigger.id) == "yes"
        fields = (option.get("AITriggerTypes", trigger.id) or "").split(",")
        assert len(fields) == 18
        amount, operator = struct.unpack("<II", bytes.fromhex(fields[6][:16]))
        gate = trigger.gate
        assert (amount, operator) == (gate.amount, int(gate.comparison))
        # "No object" and "no second team" are spelled out for the
        # engine.
        assert fields[5] == (gate.subject or "<none>")
        assert fields[14] == (trigger.support or "<none>")
    rating = plan.leadership["TANK"]
    assert option.get("TANK", "LeadershipRating") == str(rating)


def test_the_ai_fragment_defines_what_it_registers(plan: AIPlan) -> None:
    text = render_ai_fragment(plan)
    data = IniData.parse(text)
    for team in plan.teams:
        assert f"+={team.id}" in text
        assert data.get(team.id, "TaskForce") == team.task_force
        assert data.has(team.task_force)
        assert data.has(data.get(team.id, "Script") or "")


def test_the_shipped_triggers_reach_defined_teams() -> None:
    # A map trigger runs only when enabled, and a team naming a missing
    # task force or script would never form.
    ai = IniData.parse((ENHANCE / AI_FRAGMENT).read_text(encoding="utf-8"))
    option = IniData.parse((ENHANCE / OPTION_FRAGMENT).read_text(encoding="utf-8"))
    assert option.get("Basic", "IgnoreGlobalAITriggers") == "yes"
    triggers = option.keys("AITriggerTypes")
    assert triggers
    for trigger in triggers:
        assert option.get("AITriggerTypesEnable", trigger) == "yes"
        team = (option.get("AITriggerTypes", trigger) or "").split(",")[1]
        assert ai.has(team)
        assert ai.has(ai.get(team, "TaskForce") or "")
        assert ai.has(ai.get(team, "Script") or "")
