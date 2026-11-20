"""Refused postings tell the tenant's ledger readers in-app, once per opening (WP-0.6)."""
from __future__ import annotations

from ulid import ULID

from core.domain.result import Err
from modules.finance.api.posting_failure_service import NOTIFICATION_KIND, PostingFailureService

TENANT = "integration-test-posting-failure-alerts"


def _user(db, permission: str | None) -> str:
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, TENANT, f"{user_id}@test.local"),
    )
    if permission:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user_id, permission))
    return user_id


def _envelope() -> dict:
    return {"event_id": str(ULID()), "event_type": "finance.invoice.issued", "payload": {}}


def _refuse(service: PostingFailureService, source_id: str) -> str:
    return service.record(
        tenant_id=TENANT, source_module="finance", source_id=source_id, source_kind="invoice_issued",
        envelope=_envelope(), err=Err("PERIOD_CLOSED", "The period is closed", "La période est clôturée"),
    )


def _notifications(db, user_id: str) -> list[tuple]:
    return db.execute(
        "SELECT kind, title, title_fr, body, body_fr, link FROM core.notifications WHERE tenant_id = %s AND user_id = %s",
        (TENANT, user_id),
    ).fetchall()


def test_a_new_failure_notifies_ledger_readers_only(db):
    reader, other = _user(db, "finance.view_ledger"), _user(db, None)
    _refuse(PostingFailureService(db), "inv-1")
    assert _notifications(db, reader) == [(
        NOTIFICATION_KIND,
        "Automatic posting refused: finance invoice_issued",
        "Écriture automatique refusée : finance invoice_issued",
        "The period is closed",
        "La période est clôturée",
        "/finance/entries",
    )]
    assert _notifications(db, other) == []


def test_a_failure_already_open_is_not_announced_again_but_a_reopened_one_is(db):
    reader = _user(db, "finance.view_ledger")
    service = PostingFailureService(db)
    _refuse(service, "inv-2")
    _refuse(service, "inv-2")  # a retry refused again: still the same open failure
    assert len(_notifications(db, reader)) == 1
    service.resolve(tenant_id=TENANT, source_module="finance", source_id="inv-2", source_kind="invoice_issued")
    _refuse(service, "inv-2")
    assert len(_notifications(db, reader)) == 2


def test_open_counts_by_tenant_counts_open_failures_only(db):
    service = PostingFailureService(db)
    _refuse(service, "inv-3")
    _refuse(service, "inv-4")
    service.resolve(tenant_id=TENANT, source_module="finance", source_id="inv-4", source_kind="invoice_issued")
    assert service.open_counts_by_tenant()[TENANT] == 1
