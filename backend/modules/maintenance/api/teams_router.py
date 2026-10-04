from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.notifications import users_with_permission
from core.tenancy import TenantContext, require_permission
from modules.maintenance.api.people import active_employees, user_names
from modules.maintenance.api.team_service import TeamService

# No prefix: included into modules/maintenance/api/router.py, which carries /maintenance.
router = APIRouter(tags=["maintenance.teams"])

_STATUS_BY_CODE = {"NOT_FOUND": status.HTTP_404_NOT_FOUND}


class CreateTeamRequest(BaseModel):
    name: str
    chef_user_id: str | None = None


class UpdateTeamRequest(BaseModel):
    name: str | None = None
    chef_user_id: str | None = None
    archived: bool | None = None


class SetMembersRequest(BaseModel):
    employee_ids: list[str]


def _result(connection, result):
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    connection.commit()
    return result.value


@router.get("/teams")
def list_teams(tenant: TenantContext = Depends(require_permission("maintenance.view_jobs"))) -> list[dict]:
    with get_connection() as connection:
        return TeamService(connection).list_teams(tenant_id=tenant.tenant_id)


@router.post("/teams", status_code=status.HTTP_201_CREATED)
def create_team(
    body: CreateTeamRequest, tenant: TenantContext = Depends(require_permission("maintenance.manage_teams"))
) -> dict:
    with get_connection() as connection:
        return _result(
            connection,
            TeamService(connection).create_team(
                tenant_id=tenant.tenant_id, actor_id=tenant.user_id, name=body.name, chef_user_id=body.chef_user_id
            ),
        )


@router.patch("/teams/{team_id}")
def update_team(
    team_id: str, body: UpdateTeamRequest, tenant: TenantContext = Depends(require_permission("maintenance.manage_teams"))
) -> dict:
    fields_set = body.model_fields_set
    with get_connection() as connection:
        return _result(
            connection,
            TeamService(connection).update_team(
                tenant_id=tenant.tenant_id,
                actor_id=tenant.user_id,
                team_id=team_id,
                name=body.name,
                chef_user_id=body.chef_user_id,
                chef_user_id_set="chef_user_id" in fields_set,
                archived=body.archived,
            ),
        )


@router.put("/teams/{team_id}/members")
def set_team_members(
    team_id: str, body: SetMembersRequest, tenant: TenantContext = Depends(require_permission("maintenance.manage_teams"))
) -> dict:
    with get_connection() as connection:
        return _result(
            connection,
            TeamService(connection).set_members(
                tenant_id=tenant.tenant_id, actor_id=tenant.user_id, team_id=team_id, employee_ids=body.employee_ids
            ),
        )


@router.get("/team-candidates")
def team_candidates(tenant: TenantContext = Depends(require_permission("maintenance.view_jobs"))) -> list[dict]:
    with get_connection() as connection:
        return active_employees(connection, tenant.tenant_id)


@router.get("/chef-candidates")
def chef_candidates(tenant: TenantContext = Depends(require_permission("maintenance.view_jobs"))) -> list[dict]:
    with get_connection() as connection:
        user_ids = users_with_permission(connection, tenant.tenant_id, "maintenance.execute_jobs")
        names = user_names(connection, tenant.tenant_id, user_ids)
        return [{"id": uid, "name": names[uid]} for uid in user_ids if uid in names]
