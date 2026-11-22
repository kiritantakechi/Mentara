"""Plan the Mental AI: every family, for every country, as INI objects.

The families decide what each country fields; this module gives every
squad, script and trigger its ID and name, and checks the engine's
limits.

IDs follow MO's form (`overlays/README.md`): the prefix `MNT`, the
object's kind (`TF` task force, `SC` script, `TT` team, `TR` trigger),
its number, the country's two-letter code, and `-G`. A script carries
the country's code only when it casts that country's superweapons;
every other script is shared.
"""

from dataclasses import dataclass, field
from typing import Final
lazy from collections.abc import Iterable, Mapping

from mentara.mentalai.families import FAMILIES, Context, leftovers
from mentara.mentalai.handling import stand_offs
from mentara.mentalai.model import (
    AIPlan,
    Call,
    ScriptType,
    Squad,
    TaskForce,
    TeamType,
    Trigger,
)
lazy from mentara.mentalai.catalog import Catalog, Country
lazy from mentara.mentalai.families import Order
lazy from mentara.mentalai.scripts import Script

__all__ = ["plan_ai"]

# The engine keeps 24 characters of an ID.
_ID_LENGTH_MAX: Final[int] = 24
# A ScriptType holds at most fifty lines.
_SCRIPT_LINES_MAX: Final[int] = 50


@dataclass(frozen=True, slots=True)
class _Naming:
    """How a country is spelled in IDs and in display names."""

    code: str
    label: str

    @classmethod
    def of(cls, country: Country) -> _Naming:
        """MO's spelling of a country, or one made from its ID."""
        known = _NAMINGS.get(country.id.lower())
        return known or cls(country.id[:2].upper(), country.id)


# Naming only: MO's two-letter country codes and labels (see README).
_NAMINGS: Final[frozendict[str, _Naming]] = frozendict(
    {
        "unitedstates": _Naming("US", "USA"),
        "europeans": _Naming("EU", "Euro"),
        "pacific": _Naming("PA", "Pacific"),
        "ussr": _Naming("RU", "Russia"),
        "latin": _Naming("LA", "Latin"),
        "chinese": _Naming("CH", "China"),
        "psicorps": _Naming("PC", "PsiCorps"),
        "scorpioncell": _Naming("SC", "Scorpion"),
        "headquaters": _Naming("HQ", "HQ"),
        "guild1": _Naming("HA", "Haihead"),
        "guild2": _Naming("CO", "Coronia"),
        "guild3": _Naming("LB", "Last Bastion"),
    }
)


def plan_ai(catalog: Catalog) -> AIPlan:
    """Build every TaskForce, ScriptType, TeamType and trigger.

    Args:
        catalog: Units and countries from the rules.

    Returns:
        The plan, in a stable order.

    Raises:
        ValueError: If an ID, a squad number or a script breaks an
            engine limit or repeats.
    """
    context = Context.build(catalog)
    builder = _Builder()
    for country in catalog.countries:
        orders = [order for family in FAMILIES for order in family(context, country)]
        used = frozenset(
            member.unit.id
            for order in orders
            if isinstance(order, Squad)
            for member in order.members
        )
        orders.extend(leftovers(context, country, used))
        builder.add_country(country, orders)
    return builder.plan(tuple(context.target_lists), stand_offs(catalog))


# A mutable accumulator: it collects every country's objects in turn.
@dataclass(slots=True)
class _Builder:
    task_forces: list[TaskForce] = field(default_factory=list)
    teams: list[TeamType] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    scripts: dict[str, ScriptType] = field(default_factory=dict)
    leadership: dict[str, int] = field(default_factory=dict)
    docked: set[str] = field(default_factory=set)

    def plan(
        self,
        target_lists: tuple[tuple[str, ...], ...],
        stand_offs: Mapping[str, float],
    ) -> AIPlan:
        return AIPlan(
            task_forces=tuple(self.task_forces),
            scripts=tuple(sorted(self.scripts.values(), key=lambda s: s.id)),
            teams=tuple(self.teams),
            triggers=tuple(self.triggers),
            leadership=frozendict(sorted(self.leadership.items())),
            docked=frozenset(self.docked),
            target_lists=target_lists,
            stand_offs=stand_offs,
        )

    def add_country(self, country: Country, orders: Iterable[Order]) -> None:
        """Add a country's squads and the triggers that can raise them.

        A call whose squad the country lacks is dropped, and so is a
        squad no call raises.
        """
        naming = _Naming.of(country)
        squads: dict[int, Squad] = {}
        calls: list[Call] = []
        for order in orders:
            if isinstance(order, Call):
                calls.append(order)
            elif order.number in squads:
                detail = f"{country.id} has two squads numbered {order.number}"
                raise ValueError(detail)
            else:
                squads[order.number] = order
        calls = [call for call in calls if _teams_of(call) <= squads.keys()]
        raised = sorted(frozenset[int]().union(*map(_teams_of, calls)))
        teams = {number: self._add_squad(naming, squads[number]) for number in raised}
        seen: set[int] = set()
        for call in calls:
            if call.number in seen:
                detail = f"{country.id} has two triggers numbered {call.number}"
                raise ValueError(detail)
            seen.add(call.number)
            lead = teams[call.squad]
            if call.support is not None:
                if call.number in squads:
                    detail = f"{country.id}: call {call.number} leads as a squad's ID"
                    raise ValueError(detail)
                lead = self._add_lead(naming, call, lead)
            self.triggers.append(
                Trigger(
                    id=_identifier("TR", call.number, naming.code),
                    name=f"{naming.label} - Mental {call.label}",
                    team=lead.id,
                    support=None if call.support is None else teams[call.support].id,
                    country=country.id,
                    side=country.side,
                    gate=call.gate,
                    weight=call.weight,
                    base_defense=lead.conduct.base_defense,
                    steady=not squads[call.squad].script.measured,
                )
            )

    def _add_squad(self, naming: _Naming, squad: Squad) -> TeamType:
        members = tuple((member.count, member.unit.id) for member in squad.members)
        task_force = TaskForce(
            id=_identifier("TF", squad.number, naming.code),
            name=", ".join(f"{count} {unit}" for count, unit in members),
            members=members,
        )
        team = TeamType(
            id=_identifier("TT", squad.number, naming.code),
            name=f"{naming.label} - Mental {squad.label}",
            task_force=task_force.id,
            script=self._add_script(naming, squad.script),
            max_teams=squad.max_teams,
            conduct=squad.conduct,
        )
        self.task_forces.append(task_force)
        self.teams.append(team)
        for member in squad.members:
            rating = self.leadership.get(member.unit.id, 0)
            self.leadership[member.unit.id] = max(rating, member.rank)
        self.docked |= squad.docked
        return team

    def _add_lead(self, naming: _Naming, call: Call, squad_team: TeamType) -> TeamType:
        """A two-team call's own Team1: its squad under the call's name.

        Weights are settled per Team1 type, so a call that shared its
        squad's TeamType would rise and fall with every other call of
        that squad.
        """
        team = TeamType(
            id=_identifier("TT", call.number, naming.code),
            name=f"{naming.label} - Mental {call.label}",
            task_force=squad_team.task_force,
            script=squad_team.script,
            max_teams=squad_team.max_teams,
            conduct=squad_team.conduct,
        )
        self.teams.append(team)
        return team

    def _add_script(self, naming: _Naming, script: Script) -> str:
        """Register a script, a country's own when it casts."""
        if len(script.lines) > _SCRIPT_LINES_MAX:
            detail = f"script {script.code} has more than {_SCRIPT_LINES_MAX} lines"
            raise ValueError(detail)
        own = script.casts
        entry = ScriptType(
            id=_checked(f"MNTSC{script.code}{naming.code if own else ''}-G"),
            name=f"Mental {script.name}" + (f" ({naming.code})" if own else ""),
            lines=script.lines,
        )
        known = self.scripts.setdefault(entry.id, entry)
        if known.lines != entry.lines:
            detail = f"script {entry.id} is built two ways"
            raise ValueError(detail)
        return entry.id


def _teams_of(call: Call) -> frozenset[int]:
    """The squads a call raises: its own, and its support's if any."""
    return frozenset(
        {call.squad} if call.support is None else {call.squad, call.support}
    )


def _identifier(kind: str, number: int, code: str) -> str:
    return _checked(f"MNT{kind}{number:04d}{code}-G")


def _checked(identifier: str) -> str:
    if len(identifier) > _ID_LENGTH_MAX:
        detail = f"AI ID {identifier!r} is longer than {_ID_LENGTH_MAX} characters"
        raise ValueError(detail)
    return identifier
