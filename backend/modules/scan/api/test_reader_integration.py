"""The reading queue: one page at a time, retried while the OCR is down, never stuck."""
from __future__ import annotations

import pytest
from ulid import ULID

from modules.scan.api.ocr_client import OcrReadError, OcrUnavailable
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


def test_ocr_down_requeues_forever_without_spending_attempts(db, page):
    def down(image, hint):
        raise OcrUnavailable("connection refused")

    outcomes = [read_next_page(_Connection(db), down)[1] for _ in range(5)]
    assert outcomes == ["retry", "retry", "retry", "retry", "retry"]
    status, attempts, form_type, error = _state(db, page)
    assert (status, attempts, form_type) == ("queued", 0, None)
    assert error == "connection refused"


def test_a_non_ocr_error_still_fails_after_three_attempts(db, page):
    def broken(image, hint):
        raise ValueError("bad image")

    outcomes = [read_next_page(_Connection(db), broken)[1] for _ in range(3)]
    assert outcomes == ["retry", "retry", "failed"]
    assert _state(db, page) == ("failed", 3, None, "bad image")


def test_requeue_stale_reads(db, page):
    db.execute("UPDATE scan.scan_pages SET status = 'reading' WHERE id = %s", (page,))
    assert requeue_stale_reads(_Connection(db)) >= 1
    assert _state(db, page)[0] == "queued"


def test_an_ocr_read_error_spends_attempts_like_any_other_failure(db, page):
    def bad_request(image, hint):
        raise OcrReadError("500 Internal Server Error: boom")

    outcomes = [read_next_page(_Connection(db), bad_request)[1] for _ in range(3)]
    assert outcomes == ["retry", "retry", "failed"]
    status, attempts, form_type, error = _state(db, page)
    assert (status, attempts, form_type) == ("failed", 3, None)
    assert "500 Internal Server Error" in error


def test_a_page_of_a_discarded_session_is_not_picked(db, page):
    other_tenant = f"{TENANT}-2"
    world = make_world(db, other_tenant)
    other_session_id, other_page_id = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO scan.scan_sessions (id, tenant_id, kind, work_center_id, report_date, shift, created_by, status) "
        "VALUES (%s, %s, 'shift', %s, %s, 'Matin', %s, 'discarded')",
        (other_session_id, other_tenant, world["work_center"], world["day"], world["actor"]),
    )
    db.execute(
        "INSERT INTO scan.scan_pages (id, tenant_id, session_id, image, content_type, uploaded_by, created_at, form_hint) "
        "VALUES (%s, %s, %s, %s, 'image/jpeg', %s, '1999-01-01', 'fabrication')",
        (other_page_id, other_tenant, other_session_id, b"discarded-img", world["actor"]),
    )
    # The discarded session's page is older and would sort first, but only the open session's page may be picked.
    seen = []

    def read(image, hint):
        seen.append(image)
        return fabrication_result()

    assert read_next_page(_Connection(db), read) == (page, "read")
    assert seen == [b"img"]
    assert _state(db, other_page_id)[0] == "queued"


def test_each_page_is_read_by_its_scans_reader(db, page):
    db.execute("UPDATE scan.scan_sessions SET reader = 'claude' WHERE id = (SELECT session_id FROM scan.scan_pages WHERE id = %s)", (page,))
    seen = []

    def by(name):
        def read(image, hint):
            seen.append(name)
            return fabrication_result()
        return read

    assert read_next_page(_Connection(db), {"ocr": by("ocr"), "claude": by("claude")}) == (page, "read")
    assert seen == ["claude"]
    assert db.execute("SELECT read_by FROM scan.scan_pages WHERE id = %s", (page,)).fetchone()[0] == "claude"


def test_a_page_waits_when_its_reader_is_not_running_here(db, page):
    db.execute("UPDATE scan.scan_sessions SET reader = 'claude' WHERE id = (SELECT session_id FROM scan.scan_pages WHERE id = %s)", (page,))

    def ocr(image, hint):
        raise AssertionError("the OCR must not read a page its scan sent to Claude")

    # Other queued pages in the dev database may be picked; this one never is.
    for _ in range(5):
        step = read_next_page(_Connection(db), {"ocr": ocr})
        if step is None:
            break
        assert step[0] != page
    assert _state(db, page)[0] == "queued"
