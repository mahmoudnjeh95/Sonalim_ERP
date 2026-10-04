from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.maintenance.api.people import employee_names, user_names

__all__ = ["TeamService"]


class TeamService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_teams(self, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT id, name, chef_user_id, archived_at FROM maintenance.teams WHERE tenant_id = %s ORDER BY created_at",
            (tenant_id,),
        ).fetchall()
        return [self._team_dict(tenant_id, row) for row in rows]

    def get_team(self, *, tenant_id: str, team_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT id, name, chef_user_id, archived_at FROM maintenance.teams WHERE id = %s AND tenant_id = %s",
            (team_id, tenant_id),
        ).fetchone()
        return None if row is None else self._team_dict(tenant_id, row)

    def create_team(self, *, tenant_id: str, actor_id: str, name: str, chef_user_id: str | None) -> Result[dict]:
        if not name or not name.strip():
            return Err("INVALID_NAME", "team name is required", "le nom de l'équipe est requis")
        team_id = str(ULID())
        self._connection.execute(
            "INSERT INTO maintenance.teams (id, tenant_id, name, chef_user_id) VALUES (%s, %s, %s, %s)",
            (team_id, tenant_id, name.strip(), chef_user_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="team.created",
            entity_type="team",
            entity_id=team_id,
            payload={"name": name.strip(), "chef_user_id": chef_user_id},
        )
        return Ok(self.get_team(tenant_id=tenant_id, team_id=team_id))

    def update_team(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        team_id: str,
        name: str | None = None,
        chef_user_id: str | None = None,
        chef_user_id_set: bool = False,
        archived: bool | None = None,
    ) -> Result[dict]:
        """`chef_user_id_set` distinguishes "not mentioned" from "clear it" (sent as null),
        the same `UNSET` convention as `EquipmentService.update_equipment` but via a flag
        since this service returns plain dicts rather than a dataclass with `replace`."""
        row = self._connection.execute(
            "SELECT id, name, chef_user_id, archived_at FROM maintenance.teams WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (team_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"team {team_id} not found", f"équipe {team_id} introuvable")

        current_name, current_chef, current_archived = row[1], row[2], row[3]
        updated_name = current_name if name is None else name.strip()
        if not updated_name:
            return Err("INVALID_NAME", "team name is required", "le nom de l'équipe est requis")
        updated_chef = chef_user_id if chef_user_id_set else current_chef

        self._connection.execute(
            "UPDATE maintenance.teams SET name = %s, chef_user_id = %s WHERE id = %s",
            (updated_name, updated_chef, team_id),
        )

        updated_archived = current_archived
        if archived is True and current_archived is None:
            updated_archived = self._connection.execute(
                "UPDATE maintenance.teams SET archived_at = NOW() WHERE id = %s RETURNING archived_at", (team_id,)
            ).fetchone()[0]
        elif archived is False and current_archived is not None:
            self._connection.execute("UPDATE maintenance.teams SET archived_at = NULL WHERE id = %s", (team_id,))
            updated_archived = None

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="team.updated",
            entity_type="team",
            entity_id=team_id,
            payload={
                "name": updated_name,
                "chef_user_id": updated_chef,
                "archived_at": updated_archived.isoformat() if updated_archived is not None else None,
            },
        )
        return Ok(self.get_team(tenant_id=tenant_id, team_id=team_id))

    def set_members(self, *, tenant_id: str, actor_id: str, team_id: str, employee_ids: list[str]) -> Result[dict]:
        row = self._connection.execute(
            "SELECT id FROM maintenance.teams WHERE id = %s AND tenant_id = %s FOR UPDATE", (team_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"team {team_id} not found", f"équipe {team_id} introuvable")

        distinct_ids = list(dict.fromkeys(employee_ids))
        self._connection.execute("DELETE FROM maintenance.team_members WHERE team_id = %s", (team_id,))
        for employee_id in distinct_ids:
            self._connection.execute(
                "INSERT INTO maintenance.team_members (team_id, tenant_id, employee_id) VALUES (%s, %s, %s)",
                (team_id, tenant_id, employee_id),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="team.members_set",
            entity_type="team",
            entity_id=team_id,
            payload={"employee_ids": distinct_ids},
        )
        return Ok(self.get_team(tenant_id=tenant_id, team_id=team_id))

    def _team_dict(self, tenant_id: str, row: tuple) -> dict:
        team_id, name, chef_user_id, archived_at = row
        member_ids = [
            r[0]
            for r in self._connection.execute(
                "SELECT employee_id FROM maintenance.team_members WHERE team_id = %s ORDER BY employee_id", (team_id,)
            ).fetchall()
        ]
        names = employee_names(self._connection, tenant_id, member_ids)
        chef_names = user_names(self._connection, tenant_id, [chef_user_id] if chef_user_id else [])
        return {
            "id": team_id,
            "name": name,
            "chef_user_id": chef_user_id,
            "chef_name": chef_names.get(chef_user_id) if chef_user_id else None,
            "archived_at": archived_at.isoformat() if archived_at is not None else None,
            "members": [{"employee_id": eid, "name": names.get(eid)} for eid in member_ids],
        }
