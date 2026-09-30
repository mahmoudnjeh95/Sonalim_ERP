"""The reading queue: one page at a time, retried while the OCR is down, never stuck."""
from __future__ import annotations

import pytest
from ulid import ULID

from modules.scan.api.ocr_client import OcrUnavailable
from modules.scan.api.reader import read_next_page, requeue_stale_reads
from modules.scan.api.scan_world import fabrication_result, make_world

TENANT = "scan-reader-test"


class _Connection:
    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.fixture
def page(db):
    world = make_world(db, TENANT)
    session_id, page_id = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO scan.scan_sessions (id, tenant_id, kind, work_center_id, report_date, shift, created_by) "
        "VALUES (%s, %s, 'shift', %s, %s, 'Matin', %s)",
        (session_id, TENANT, world["work_center"], world["day"], world["actor"]),
    )
    # Oldest in the queue, so a page left queued in the development database is not picked first.
    db.execute(
        "INSERT INTO scan.scan_pages (id, tenant_id, session_id, image, content_type, uploaded_by, created_at, form_hint) "
        "VALUES (%s, %s, %s, %s, 'image/jpeg', %s, '2000-01-01', 'fabrication')",
        (page_id, TENANT, session_id, b"img", world["actor"]),
    )
    return page_id


def _state(db, page_id):
    return db.execute("SELECT status, attempts, form_type, error FROM scan.scan_pages WHERE id = %s", (page_id,)).fetchone()


def test_a_page_is_read_and_stored(db, page):
    seen = []

    def read(image, hint):
        seen.append((image, hint))
        return fabrication_result()

    assert read_next_page(_Connection(db), read) == (page, "read")
    assert seen == [(b"img", "fabrication")]
    assert _state(db, page) == ("read", 1, "fabrication", None)


def test_an_unrecognized_page_does_not_stop_the_queue(db, page):
    assert read_next_page(_Connection(db), lambda image, hint: {"form_type": None, "blocks": [], "header": {}}) == (page, "unrecognized")
    assert _state(db, page)[0] == "unrecognized"


def test_ocr_down_requeues_then_fails_after_three(db, page):
    def down(image, hint):
        raise OcrUnavailable("connection refused")

    outcomes = [read_next_page(_Connection(db), down)[1] for _ in range(3)]
    assert outcomes == ["retry", "retry", "failed"]
    assert _state(db, page) == ("failed", 3, None, "connection refused")


def test_requeue_stale_reads(db, page):
    db.execute("UPDATE scan.scan_pages SET status = 'reading' WHERE id = %s", (page,))
    assert requeue_stale_reads(_Connection(db)) >= 1
    assert _state(db, page)[0] == "queued"
