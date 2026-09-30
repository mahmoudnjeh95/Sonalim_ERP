"""Who may be named in the fiche de shift's four person fields.

The header's Conducteur ligne, Agent de fabrication, Machiniste and Aide machiniste were
free text. They become lists of the plant's own people: each role is mapped to one or
more HR positions in Production settings, and the field offers the employees holding
one of them. The mapping is configuration, never a guess at how a job title is spelled.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.shift_role_service import ShiftRoleService

TENANT = "shift-role-test"


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor = str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    positions = {}
    for code, title in (("CND", "Conducteur ligne"), ("AGF", "Agent de fabrication"), ("MAC", "Machiniste")):
        positions[code] = str(ULID())
        db.execute(
            "INSERT INTO hr.positions (id, tenant_id, code, title) VALUES (%s, %s, %s, %s)",
            (positions[code], TENANT, code, title),
        )

    def hire(first: str, last: str, position: str | None, status: str = "active") -> str:
        employee_id = str(ULID())
        db.execute(
            "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date, status, position_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (employee_id, TENANT, f"E-{employee_id[-6:]}", first, last, datetime.date(2020, 1, 1), status, position),
        )
        return employee_id

    return {"actor": actor, "positions": positions, "hire": hire}


def _service(db) -> ShiftRoleService:
    return ShiftRoleService(db)


def test_a_role_with_no_mapping_offers_nobody(db, env):
    env["hire"]("Alou", "Traoré", env["positions"]["CND"])

    assert _service(db).list_role_people(tenant_id=TENANT)["conducteur"] == []


def test_a_role_offers_the_people_holding_its_positions(db, env):
    env["hire"]("Alou", "Traoré", env["positions"]["CND"])
    env["hire"]("Bina", "Koné", env["positions"]["AGF"])
    _ok(_service(db).set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[env["positions"]["CND"]]))

    people = _service(db).list_role_people(tenant_id=TENANT)

    assert [p["name"] for p in people["conducteur"]] == ["Alou Traoré"]
    # The agent de fabrication was not mapped, so nobody is offered for it.
    assert people["agent_fabrication"] == []


def test_a_role_can_map_several_positions(db, env):
    env["hire"]("Alou", "Traoré", env["positions"]["CND"])
    env["hire"]("Bina", "Koné", env["positions"]["AGF"])
    _ok(_service(db).set_role_positions(
        tenant_id=TENANT, actor_id=env["actor"], role="conducteur",
        position_ids=[env["positions"]["CND"], env["positions"]["AGF"]],
    ))

    assert sorted(p["name"] for p in _service(db).list_role_people(tenant_id=TENANT)["conducteur"]) == ["Alou Traoré", "Bina Koné"]


def test_somebody_who_has_left_is_not_offered(db, env):
    env["hire"]("Alou", "Traoré", env["positions"]["CND"])
    env["hire"]("Gone", "Away", env["positions"]["CND"], status="inactive")
    _ok(_service(db).set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[env["positions"]["CND"]]))

    assert [p["name"] for p in _service(db).list_role_people(tenant_id=TENANT)["conducteur"]] == ["Alou Traoré"]


def test_saving_a_mapping_replaces_the_one_before_it(db, env):
    env["hire"]("Alou", "Traoré", env["positions"]["CND"])
    env["hire"]("Bina", "Koné", env["positions"]["AGF"])
    service = _service(db)
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[env["positions"]["CND"]]))
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[env["positions"]["AGF"]]))

    assert [p["name"] for p in service.list_role_people(tenant_id=TENANT)["conducteur"]] == ["Bina Koné"]


def test_a_mapping_can_be_cleared(db, env):
    env["hire"]("Alou", "Traoré", env["positions"]["CND"])
    service = _service(db)
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[env["positions"]["CND"]]))
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[]))

    assert service.list_role_people(tenant_id=TENANT)["conducteur"] == []


def test_an_unknown_role_is_refused(db, env):
    result = _service(db).set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="gardien", position_ids=[])

    assert isinstance(result, Err) and result.code == "INVALID_ROLE"


def test_a_position_hr_no_longer_has_is_simply_not_offered(db, env):
    """The mapping is not a foreign key -- production must not depend on hr's tables."""
    service = _service(db)
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[str(ULID())]))

    assert service.list_role_people(tenant_id=TENANT)["conducteur"] == []


def test_the_mapping_reads_back_for_the_settings_screen(db, env):
    service = _service(db)
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="machiniste", position_ids=[env["positions"]["MAC"]]))

    mapping = service.get_role_positions(tenant_id=TENANT)

    assert mapping["machiniste"] == [env["positions"]["MAC"]]
    assert mapping["conducteur"] == []


def test_each_role_keeps_its_own_list(db, env):
    env["hire"]("Alou", "Traoré", env["positions"]["CND"])
    env["hire"]("Moussa", "Diarra", env["positions"]["MAC"])
    service = _service(db)
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[env["positions"]["CND"]]))
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="machiniste", position_ids=[env["positions"]["MAC"]]))

    people = service.list_role_people(tenant_id=TENANT)

    assert [p["name"] for p in people["conducteur"]] == ["Alou Traoré"]
    assert [p["name"] for p in people["machiniste"]] == ["Moussa Diarra"]


def test_one_tenants_mapping_is_not_anothers(db, env):
    other = "shift-role-other"
    env["hire"]("Alou", "Traoré", env["positions"]["CND"])
    service = _service(db)
    _ok(service.set_role_positions(tenant_id=TENANT, actor_id=env["actor"], role="conducteur", position_ids=[env["positions"]["CND"]]))

    assert service.list_role_people(tenant_id=other)["conducteur"] == []
