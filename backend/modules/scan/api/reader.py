"""One step of the reading queue, run by the worker.

A page is taken with FOR UPDATE SKIP LOCKED and marked `reading` in its own committed
transaction before the (slow) OCR call, so two workers never read the same photo and
a crash mid-read leaves a page the next start puts back in the queue. The OCR service
itself being unreachable (`OcrUnavailable`) does not spend an attempt: the page is put
back to `queued` and the attempt counter is refunded, so an outage of any length is
retried forever instead of failing the page. Any other error puts the page back and
counts it; its third failed pickup marks it `failed` for the user to retry.
These are system transitions, not a user's action, so they are not audited.
"""
from __future__ import annotations

from typing import Callable

import psycopg
from psycopg.types.json import Jsonb

from modules.scan.api.ocr_client import OcrUnavailable

MAX_ATTEMPTS = 3


def requeue_stale_reads(connection: psycopg.Connection) -> int:
    count = connection.execute("UPDATE scan.scan_pages SET status = 'queued' WHERE status = 'reading'").rowcount
    connection.commit()
    return count


def read_next_page(connection: psycopg.Connection, read: Callable[[bytes, str | None], dict]) -> tuple[str, str] | None:
    row = connection.execute(
        "SELECT p.id, p.image, p.form_hint FROM scan.scan_pages p "
        "JOIN scan.scan_sessions s ON s.id = p.session_id "
        "WHERE p.status = 'queued' AND s.status = 'open' "
        "ORDER BY p.attempts, p.created_at, p.id LIMIT 1 FOR UPDATE OF p SKIP LOCKED"
    ).fetchone()
    if row is None:
        connection.rollback()
        return None
    page_id, image, form_hint = row
    connection.execute("UPDATE scan.scan_pages SET status = 'reading', attempts = attempts + 1 WHERE id = %s", (page_id,))
    connection.commit()
    try:
        result = read(bytes(image), form_hint)
    except OcrUnavailable as error:  # the service itself is down: wait for it, don't spend an attempt
        connection.execute(
            "UPDATE scan.scan_pages SET status = 'queued', attempts = attempts - 1, error = %s WHERE id = %s",
            (str(error)[:500], page_id),
        )
        connection.commit()
        return page_id, "retry"
    except Exception as error:  # any other failure is the page's retry, never the loop's end
        attempts = connection.execute("SELECT attempts FROM scan.scan_pages WHERE id = %s", (page_id,)).fetchone()[0]
        outcome = "failed" if attempts >= MAX_ATTEMPTS else "retry"
        connection.execute(
            "UPDATE scan.scan_pages SET status = %s, error = %s WHERE id = %s",
            ("failed" if outcome == "failed" else "queued", str(error)[:500], page_id),
        )
        connection.commit()
        return page_id, outcome
    form_type = result.get("form_type")
    outcome = "read" if form_type else "unrecognized"
    connection.execute(
        "UPDATE scan.scan_pages SET status = %s, form_type = %s, rotation = %s, ocr_result = %s, error = NULL, read_at = NOW() "
        "WHERE id = %s",
        (outcome, form_type, int(result.get("rotation") or 0), Jsonb(result), page_id),
    )
    connection.commit()
    return page_id, outcome
