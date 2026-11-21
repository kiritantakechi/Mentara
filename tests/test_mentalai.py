"""The Mental AI generator, on a small rules file shaped like MO's."""

import struct
from pathlib import Path

import pytest

from mentara.mentalai import IniData, build_catalog, plan_ai
from mentara.mentalai.catalog import Factory, Role
from mentara.mentalai.emit import render_ai_fragment, render_option_fragment
from mentara.mentalai.generate import AI_FRAGMENT, OPTION_FRAGMENT
from mentara.mentalai.ini import split_list
from mentara.mentalai.teams import Comparison

# One side with one country. Its yard unlocks a barracks and a war
# factory (tier 1), a radar (tech level 5, tier 2) and labs (tech level
# 8, tier 3). AILOCK is the AI-only lock: no house builds it.
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

[VehicleTypes]
0=TANK
1=FLAK
2=ARTY
3=MCV
4=TWIN
5=HARV

[SuperWeaponTypes]
0=CurtainSW
1=SphereSW
2=LiftSW
3=MinerSW

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
Armor=light
Primary=Cannon

[GI]
TechLevel=1
Owner=Alpha
Prerequisite=PILE
Cost=200
Strength=125
Primary=Rifle

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

[Flak]
Verses=50%,50%,50%,100%,100%,100%,0%,0%,0%,100%,100%

[HE]
Verses=80%,80%,80%,80%,80%,80%,100%,100%,100%,100%,100%
"""


@pytest.fixture(scope="module")
def rules() -> IniData:
    return IniData.parse(RULES)


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


def test_roles_come_from_weapons_and_hulls(rules: IniData) -> None:
    units = build_catalog(rules).units
    assert units["tank"].has(Role.MBT, Role.ANTI_ARMOUR)
    assert units["gi"].has(Role.ANTI_INFANTRY)
    assert units["flak"].has(Role.AA, Role.AA_ONLY)
    assert units["arty"].has(Role.ARTILLERY, Role.SIEGE)
    assert units["medic"].has(Role.HEALER)
    assert units["hero"].has(Role.HERO)
    assert units["mcv"].has(Role.MCV)


def test_a_country_fields_units_by_tier(rules: IniData) -> None:
    (country,) = build_catalog(rules).countries
    assert country.side == 1
    assert country.mcv == "MCV"
    assert country.construction_yard == "YARD"
    assert country.units["tank"] == 1
    assert country.units["arty"] == 2
    assert country.units["hero"] == 3
    assert country.gates == {2: "RADR", 3: "LABS"}
    assert country.factories[Factory.WAR_FACTORY] == "WEAP"


def test_the_ai_fields_units_behind_a_lock_no_house_builds(rules: IniData) -> None:
    # The AI skips unit prerequisites, so an AI-only twin is its own.
    (country,) = build_catalog(rules).countries
    assert country.units["twin"] == 1


def test_a_line_mixes_roles_and_its_front_leads(rules: IniData) -> None:
    plan = plan_ai(build_catalog(rules))
    lines = {tf.id: tf for tf in plan.task_forces}
    tier_1 = lines["MNTTF101AL-G"].members
    assert tier_1[0] == (4, "TANK")
    assert {unit for _, unit in tier_1} >= {"TANK", "GI", "FLAK"}
    tier_3 = {unit for _, unit in lines["MNTTF103AL-G"].members}
    assert {"ARTY", "HERO", "MEDIC"} <= tier_3
    assert plan.leadership["TANK"] > plan.leadership["HERO"]
    assert plan.leadership["HERO"] > plan.leadership["GI"]


def test_triggers_hold_each_tier_back(rules: IniData) -> None:
    triggers = {t.id: t for t in plan_ai(build_catalog(rules)).triggers}
    first = triggers["MNTTR101AL-G"]
    assert (first.condition_object, first.comparison) == ("RADR", Comparison.LESS)
    third = triggers["MNTTR103AL-G"]
    assert (third.condition_object, third.comparison) == ("LABS", Comparison.AT_LEAST)
    mcv = triggers["MNTTR800AL-G"]
    assert (mcv.condition_object, mcv.comparison) == ("YARD", Comparison.LESS)


def test_task_forces_stay_within_engine_limits(rules: IniData) -> None:
    plan = plan_ai(build_catalog(rules))
    assert all(len(tf.members) <= 6 for tf in plan.task_forces)
    ids = [tf.id for tf in plan.task_forces] + [t.id for t in plan.teams]
    assert all(len(identifier) <= 24 for identifier in ids)
    assert len(set(ids)) == len(ids)


def test_the_option_fragment_gates_and_enables_every_trigger(rules: IniData) -> None:
    plan = plan_ai(build_catalog(rules))
    option = IniData.parse(render_option_fragment(plan))
    assert option.get("Basic", "IgnoreGlobalAITriggers") == "yes"
    for trigger in plan.triggers:
        assert option.get("AITriggerTypesEnable", trigger.id) == "yes"
        fields = (option.get("AITriggerTypes", trigger.id) or "").split(",")
        assert len(fields) == 18
        amount, operator = struct.unpack("<II", bytes.fromhex(fields[6][:16]))
        assert (amount, operator) == (trigger.amount, int(trigger.comparison))
    assert option.get("TANK", "LeadershipRating") == str(plan.leadership["TANK"])


def test_the_ai_fragment_defines_what_it_registers(rules: IniData) -> None:
    plan = plan_ai(build_catalog(rules))
    text = render_ai_fragment(plan)
    data = IniData.parse(text)
    for team in plan.teams:
        assert f"+={team.id}" in text
        assert data.get(team.id, "TaskForce") == team.task_force
        assert data.has(team.task_force)
        assert data.has(data.get(team.id, "Script") or "")


def test_airfield_bound_strikes_fit_the_pads(rules: IniData) -> None:
    # An aircraft with no free pad is never built: the tier-2 and tier-3
    # strikes, one team each, share one airfield's four pads.
    plan = plan_ai(build_catalog(rules))
    strike = {tf.id: tf for tf in plan.task_forces}["MNTTF402AL-G"]
    assert strike.members == ((2, "JET"),)
    team = {t.id: t for t in plan.teams}["MNTTT402AL-G"]
    assert team.max_teams == 1
    # Mental AI clones every unit per extra factory; a clone has no pad.
    option = IniData.parse(render_option_fragment(plan))
    assert option.get("JET", "ForbidParallelAIQueues") == "true"
    assert option.get("TANK", "ForbidParallelAIQueues") is None


def test_superweapons_sort_into_team_casts(rules: IniData) -> None:
    (country,) = build_catalog(rules).countries
    assert country.front_casts == (0,)
    assert country.base_casts == (17,)
    assert country.chronosphere


def test_lines_cast_at_the_front_and_the_watch_at_home(rules: IniData) -> None:
    plan = plan_ai(build_catalog(rules))
    teams = {t.id: t for t in plan.teams}
    scripts = {s.id: s for s in plan.scripts}
    line = scripts[teams["MNTTT103AL-G"].script]
    assert line.id == "MNTSC100AL-G"
    assert (55, 0) in line.lines
    assert line.lines.index((55, 0)) < line.lines.index((0, 7))
    watch = scripts[teams["MNTTT503AL-G"].script]
    assert (55, 17) in watch.lines
    assert (55, 14) not in line.lines + watch.lines


def test_the_chrono_assault_waits_for_the_sphere(rules: IniData) -> None:
    plan = plan_ai(build_catalog(rules))
    trigger = {t.id: t for t in plan.triggers}["MNTTR803AL-G"]
    assert (int(trigger.condition), trigger.condition_object) == (6, "<none>")
    members = {tf.id: tf for tf in plan.task_forces}["MNTTF803AL-G"].members
    assert {unit for _, unit in members} == {"TANK", "ARTY", "FLAK"}


ENHANCE = Path(__file__).resolve().parents[1] / "overlays" / "enhance"


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
