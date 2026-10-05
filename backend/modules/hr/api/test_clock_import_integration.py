"""Clock imports against a real database: staging, commit into presence days, manual wins."""
from __future__ import annotations

import datetime

import pytest

from core.domain.result import Err, Ok
from modules.hr.api.clock_import_service import ClockImportService, ClockProfileService
from modules.hr.api.presence_service import PresenceService
from modules.hr.api.presence_testkit import AUG_3, TENANT, close_month_directly, insert_presence_row, presence_env, presence_row  # noqa: F401
from modules.hr.domain.presence import ManualEntry

AUG_4 = datetime.date(2026, 8, 4)
HEADER = "Badge;DateHeure;Etat\n"


@pytest.fixture
def profile_id(db, presence_env) -> str:
    created = ClockProfileService(db).create_profile(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ZK", name="Pointeuse entrée", delimiter=";", has_header=True,
        badge_column="Badge", timestamp_column="DateHeure", timestamp_format="%d/%m/%Y %H:%M",
        direction_column="Etat", in_values=["IN"], out_values=["OUT"],
    )
    assert isinstance(created, Ok), created
    return created.value["id"]


def _stage(db, env, profile_id, lines, *, date_from=AUG_3, date_to=AUG_4, file_name="aout.csv"):
    return ClockImportService(db).stage(
        tenant_id=TENANT, actor_id=env.actor, profile_id=profile_id, file_name=file_name,
        content=HEADER + "\n".join(lines) + "\n", date_from=date_from, date_to=date_to,
    )


def _commit(db, env, import_id):
    return ClockImportService(db).commit(tenant_id=TENANT, actor_id=env.actor, import_id=import_id)


def _punches(db) -> int:
    return db.execute("SELECT count(*) FROM hr.clock_punches WHERE tenant_id = %s", (TENANT,)).fetchone()[0]


def test_staging_flags_unknown_badges_and_bad_times_and_writes_nothing_yet(db, presence_env, profile_id):
    staged = _stage(db, presence_env, profile_id, ["B001;03/08/2026 06:58;IN", "B001;03/08/2026 15:02;OUT", "B999;03/08/2026 07:00;IN", "B002;xx;IN"])
    assert isinstance(staged, Ok)
    detail = staged.value
    assert (detail["status"], detail["total_rows"], detail["valid_rows"], detail["error_rows"]) == ("staged", 4, 2, 2)
    assert [row["error_code"] for row in detail["rows"]] == [None, None, "UNKNOWN_BADGE", "BAD_TIMESTAMP"]
    assert detail["rows"][0]["employee_no"] == "P-001"
    assert _punches(db) == 0 and presence_row(db, presence_env.day_worker, AUG_3) is None


def test_commit_turns_punches_into_days_and_a_night_stays_on_its_start_day(db, presence_env, profile_id):
    staged = _stage(db, presence_env, profile_id, [
        "B001;03/08/2026 06:58;IN", "B001;03/08/2026 15:02;OUT", "B002;03/08/2026 22:57;IN", "B002;04/08/2026 07:03;OUT",
    ])
    committed = _commit(db, presence_env, staged.value["id"])
    assert isinstance(committed, Ok) and committed.value["days_written"] == 4
    day = presence_row(db, presence_env.day_worker, AUG_3)
    assert (day["status"], day["worked_minutes"], day["source"]) == ("present", 484, "clock")
    assert presence_row(db, presence_env.day_worker, AUG_4)["status"] == "absent"
    night = presence_row(db, presence_env.night_worker, AUG_3)
    assert (night["worked_minutes"], night["night_minutes"]) == (486, 363)
    assert presence_row(db, presence_env.night_worker, AUG_4)["status"] == "absent"
    assert ClockImportService(db).get_import(tenant_id=TENANT, import_id=staged.value["id"]).value["status"] == "committed"


def test_a_manual_day_and_a_leave_day_win_over_the_clock_and_are_listed(db, presence_env, profile_id):
    saved = PresenceService(db).save_days(tenant_id=TENANT, actor_id=presence_env.actor, entries=[
        ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="mission"),
    ])
    assert isinstance(saved, Ok)
    insert_presence_row(db, employee_id=presence_env.day_worker, work_date=AUG_4, status="leave", source="leave")
    staged = _stage(db, presence_env, profile_id, ["B001;03/08/2026 07:30;IN", "B001;03/08/2026 15:00;OUT"])
    committed = _commit(db, presence_env, staged.value["id"])
    assert isinstance(committed, Ok)
    conflicts = {(c["work_date"], c["kept_status"], c["clock_status"]) for c in committed.value["conflicts"]}
    assert conflicts == {("2026-08-03", "mission", "late"), ("2026-08-04", "leave", "absent")}
    assert presence_row(db, presence_env.day_worker, AUG_3)["status"] == "mission"
    assert presence_row(db, presence_env.day_worker, AUG_4)["status"] == "leave"


def test_a_missing_out_punch_is_reported_for_review(db, presence_env, profile_id):
    staged = _stage(db, presence_env, profile_id, ["B001;03/08/2026 07:00;IN"], date_to=AUG_3)
    committed = _commit(db, presence_env, staged.value["id"])
    assert committed.value["anomalies"] == [{
        "employee_id": presence_env.day_worker, "employee_no": "P-001", "full_name": "Test P-001",
        "work_date": "2026-08-03", "codes": ["MISSING_OUT"],
    }]
    row = presence_row(db, presence_env.day_worker, AUG_3)
    assert (row["status"], row["worked_minutes"]) == ("present", 0)


def test_a_second_file_completes_the_days_of_the_first(db, presence_env, profile_id):
    morning = _stage(db, presence_env, profile_id, ["B001;03/08/2026 06:58;IN"], date_to=AUG_3, file_name="matin.csv")
    assert isinstance(_commit(db, presence_env, morning.value["id"]), Ok)
    evening = _stage(db, presence_env, profile_id, ["B001;03/08/2026 06:58;IN", "B001;03/08/2026 15:02;OUT"], date_to=AUG_3, file_name="soir.csv")
    assert [row["error_code"] for row in evening.value["rows"]] == ["DUPLICATE_PUNCH", None]
    committed = _commit(db, presence_env, evening.value["id"])
    assert committed.value["anomalies"] == []
    assert presence_row(db, presence_env.day_worker, AUG_3)["worked_minutes"] == 484
    assert _punches(db) == 2


def test_a_file_touching_a_closed_month_is_refused_whole(db, presence_env, profile_id):
    close_month_directly(db, datetime.date(2026, 7, 1))
    staged = _stage(db, presence_env, profile_id, ["B001;31/07/2026 07:00;IN", "B001;03/08/2026 07:00;IN"], date_from=datetime.date(2026, 7, 31), date_to=AUG_3)
    committed = _commit(db, presence_env, staged.value["id"])
    assert isinstance(committed, Err) and committed.code == "PRESENCE_MONTH_CLOSED" and "2026-07" in committed.message
    assert _punches(db) == 0 and presence_row(db, presence_env.day_worker, AUG_3) is None
    assert ClockImportService(db).get_import(tenant_id=TENANT, import_id=staged.value["id"]).value["status"] == "staged"


def test_committing_needs_the_pairing_settings(db, presence_env, profile_id):
    db.execute("UPDATE hr.presence_settings SET punch_attach_minutes = NULL WHERE tenant_id = %s", (TENANT,))
    staged = _stage(db, presence_env, profile_id, ["B001;03/08/2026 07:00;IN"])
    result = _commit(db, presence_env, staged.value["id"])
    assert isinstance(result, Err) and result.code == "PRESENCE_SETTINGS_MISSING" and result.message_fr


def test_a_decided_import_cannot_be_committed_or_discarded_again(db, presence_env, profile_id):
    service = ClockImportService(db)
    committed_one = _stage(db, presence_env, profile_id, ["B001;03/08/2026 07:00;IN"])
    assert isinstance(_commit(db, presence_env, committed_one.value["id"]), Ok)
    discarded_one = _stage(db, presence_env, profile_id, ["B001;04/08/2026 07:00;IN"])
    discarded = service.discard(tenant_id=TENANT, actor_id=presence_env.actor, import_id=discarded_one.value["id"])
    assert isinstance(discarded, Ok) and discarded.value["status"] == "discarded"
    for import_id in (committed_one.value["id"], discarded_one.value["id"]):
        assert _commit(db, presence_env, import_id).code == "IMPORT_NOT_STAGED"
        assert service.discard(tenant_id=TENANT, actor_id=presence_env.actor, import_id=import_id).code == "IMPORT_NOT_STAGED"


def test_a_profile_code_is_unique_and_a_profile_can_be_edited(db, presence_env, profile_id):
    profiles = ClockProfileService(db)
    duplicate = profiles.create_profile(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ZK", name="Autre", delimiter=",", has_header=True,
        badge_column="Badge", timestamp_column="Heure", timestamp_format="%H:%M",
    )
    assert isinstance(duplicate, Err) and duplicate.code == "DUPLICATE_CODE"
    edited = profiles.update_profile(tenant_id=TENANT, actor_id=presence_env.actor, profile_id=profile_id, delimiter=",", direction_column="")
    assert isinstance(edited, Ok) and (edited.value["delimiter"], edited.value["direction_column"]) == (",", None)
