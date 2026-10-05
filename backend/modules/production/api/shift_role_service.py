"""Who may be named in the fiche de shift's four person fields.

The header's Conducteur ligne, Agent de fabrication, Machiniste and Aide machiniste were
free text: the same person arrived spelled three ways, and nothing could be counted by who
ran the line. They become lists of the plant's own people.

Which people belong in which field is configuration, not a guess: each role maps to one or
more HR positions, set in Production settings. Matching on a job title's spelling would
empty a list the first time somebody wrote "Conducteur de ligne", so the mapping is by
position id and the plant maintains it.

Production reads HR through its service, never its tables, and stores no foreign key to
them -- a position HR deletes simply stops offering anybody.
"""
from __future__ import annotations

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.employee_service import EmployeeService

# The header's person fields, named as the shift report's own columns are.
SHIFT_ROLES = ("conducteur", "agent_fabrication", "machiniste", "aide_machiniste")


class ShiftRoleService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def get_role_positions(self, *, tenant_id: str) -> dict[str, list[str]]:
        """The HR positions mapped to each role, for the settings screen."""
        mapping: dict[str, list[str]] = {role: [] for role in SHIFT_ROLES}
        rows = self._connection.execute(
            "SELECT role, position_id FROM production.shift_role_positions WHERE tenant_id = %s ORDER BY role, position_id",
            (tenant_id,),
        ).fetchall()
        for role, position_id in rows:
            if role in mapping:
                mapping[role].append(position_id)
        return mapping

    def set_role_positions(self, *, tenant_id: str, actor_id: str, role: str, position_ids: list[str]) -> Result[list[str]]:
        """Replace one role's positions with exactly this list, as the other settings lists do."""
        if role not in SHIFT_ROLES:
            return Err(
                "INVALID_ROLE",
                f"role must be one of {SHIFT_ROLES}",
                f"le rôle doit être l'un de {SHIFT_ROLES}",
            )
        wanted = list(dict.fromkeys(pid for pid in position_ids if pid))
        self._connection.execute(
            "DELETE FROM production.shift_role_positions WHERE tenant_id = %s AND role = %s", (tenant_id, role)
        )
        for position_id in wanted:
            self._connection.execute(
                "INSERT INTO production.shift_role_positions (tenant_id, role, position_id) VALUES (%s, %s, %s)",
                (tenant_id, role, position_id),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_role_positions.replaced",
            entity_type="shift_role_positions",
            entity_id=role,
            payload={"role": role, "position_ids": wanted},
        )
        return Ok(wanted)

    def list_role_people(self, *, tenant_id: str) -> dict[str, list[dict]]:
        """The people each role may name: those on the job today, holding one of its positions.

        Somebody who has left is not offered -- a shift filed tomorrow should not be able to
        name them -- but a report that already carries their name keeps it, the way it keeps
        the team's name: the screen adds the value it is showing to the list it was given.
        """
        mapping = self.get_role_positions(tenant_id=tenant_id)
        if not any(mapping.values()):
            return {role: [] for role in SHIFT_ROLES}

        employees = EmployeeService(self._connection).list_employees(tenant_id, status="active")
        by_position: dict[str, list[dict]] = {}
        for employee in employees:
            position_id = employee.get("position_id")
            if position_id:
                by_position.setdefault(position_id, []).append(
                    {"id": employee["id"], "name": employee["full_name"], "position_id": position_id}
                )

        people: dict[str, list[dict]] = {}
        for role, position_ids in mapping.items():
            seen: dict[str, dict] = {}
            for position_id in position_ids:
                for person in by_position.get(position_id, []):
                    seen.setdefault(person["id"], person)
            people[role] = sorted(seen.values(), key=lambda person: person["name"])
        return people
