"""Plan the Mental AI: every family, for every country, as INI objects.

The families decide what each country fields; this module gives every
squad and trigger its ID and checks the engine's limits.
"""

from typing import Final

from mentara.mentalai.families import (
    FAMILIES,
    Context,
    country_code,
    country_label,
    leftovers,
)
from mentara.mentalai.model import (
    AIPlan,
    Call,
    Squad,
    TaskForce,
    TeamType,
    Trigger,
)
lazy from mentara.mentalai.catalog import Catalog, Country
lazy from mentara.mentalai.scripts import Script

__all__ = ["plan_ai"]

# The engine keeps 24 characters of an ID.
_ID_LENGTH_MAX: Final[int] = 24
# A ScriptType holds at most fifty lines.
_SCRIPT_LINES_MAX: Final[int] = 50
_NO_TEAM: Final[str] = "<none>"


def plan_ai(catalog: Catalog) -> AIPlan:
    """Build every TaskForce, TeamType and trigger of the Mental AI.

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
            unit
            for order in orders
            if isinstance(order, Squad)
            for _, unit in order.members
        )
        orders.extend(leftovers(context, country, used))
        builder.add_country(country, orders)
    return builder.plan(tuple(context.target_lists))


class _Builder:
    def __init__(self) -> None:
        self._task_forces: list[TaskForce] = []
        self._teams: list[TeamType] = []
        self._triggers: list[Trigger] = []
        self._scripts: dict[str, Script] = {}
        self._leadership: dict[str, int] = {}
        self._unique: set[str] = set()

    def plan(self, target_lists: tuple[tuple[str, ...], ...]) -> AIPlan:
        return AIPlan(
            task_forces=tuple(self._task_forces),
            scripts=tuple(sorted(self._scripts.values(), key=lambda s: s.id)),
            teams=tuple(self._teams),
            triggers=tuple(self._triggers),
            leadership=dict(sorted(self._leadership.items())),
            unique=frozenset(self._unique),
            target_lists=target_lists,
        )

    def add_country(self, country: Country, orders: list[Squad | Call]) -> None:
        squads: dict[int, Squad] = {}
        for order in orders:
            if not isinstance(order, Squad):
                continue
            if order.number in squads:
                detail = f"{country.id} has two squads numbered {order.number}"
                raise ValueError(detail)
            squads[order.number] = order
        calls = [
            order
            for order in orders
            if isinstance(order, Call)
            and order.squad in squads
            and (order.support is None or order.support in squads)
        ]
        used = {call.squad for call in calls} | {
            call.support for call in calls if call.support is not None
        }
        teams = {
            number: self._add_squad(country, squads[number]) for number in sorted(used)
        }
        seen: set[int] = set()
        for call in calls:
            if call.number in seen:
                detail = f"{country.id} has two triggers numbered {call.number}"
                raise ValueError(detail)
            seen.add(call.number)
            self._add_call(country, call, teams)

    def _add_squad(self, country: Country, squad: Squad) -> TeamType:
        suffix = f"{squad.number:04d}{country_code(country)}-G"
        task_force = TaskForce(
            id=_checked_id(f"MNTTF{suffix}"),
            name=", ".join(f"{count} {unit}" for count, unit in squad.members),
            members=squad.members,
        )
        team = TeamType(
            id=_checked_id(f"MNTTT{suffix}"),
            name=f"{country_label(country)} - Mental {squad.label}",
            task_force=task_force.id,
            script=self._add_script(squad.script),
            max_teams=squad.max_teams,
            conduct=squad.conduct,
        )
        self._task_forces.append(task_force)
        self._teams.append(team)
        for unit, rank in squad.ranks.items():
            self._leadership[unit] = max(self._leadership.get(unit, 0), rank)
        self._unique |= squad.unique
        return team

    def _add_script(self, script: Script) -> str:
        if len(script.lines) > _SCRIPT_LINES_MAX:
            detail = f"script {script.id} has more than {_SCRIPT_LINES_MAX} lines"
            raise ValueError(detail)
        known = self._scripts.setdefault(_checked_id(script.id), script)
        if known.lines != script.lines:
            detail = f"script {script.id} is built two ways"
            raise ValueError(detail)
        return script.id

    def _add_call(
        self,
        country: Country,
        call: Call,
        teams: dict[int, TeamType],
    ) -> None:
        team = teams[call.squad]
        support = teams[call.support].id if call.support is not None else _NO_TEAM
        suffix = f"{call.number:04d}{country_code(country)}-G"
        self._triggers.append(
            Trigger(
                id=_checked_id(f"MNTTR{suffix}"),
                name=f"{country_label(country)} - Mental {call.label}",
                team=team.id,
                support=support,
                country=country.id,
                side=country.side,
                gate=call.gate,
                weight=call.weight,
                base_defense=team.conduct.base_defense,
            )
        )


def _checked_id(identifier: str) -> str:
    if len(identifier) > _ID_LENGTH_MAX:
        detail = f"AI ID {identifier!r} is longer than {_ID_LENGTH_MAX} characters"
        raise ValueError(detail)
    return identifier
