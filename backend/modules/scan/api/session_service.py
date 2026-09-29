"""Scanning a shift's paper fiches: sessions, their photos, the proposal and applying it.

A session is one user's scan of one line, date and shift. Photos wait in
scan.scan_pages until the worker's reader has the OCR container read them; the
proposal is rebuilt from the read pages on every request, so it never goes stale.
Applying writes the reviewed sections through production's ShiftReportService --
exactly what a team typing them would do -- and learns the codes the user corrected.
"""
from __future__ import annotations

import base64
import binascii
import datetime
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.work_center_service import WorkCenterService
from modules.scan.domain.attribution import Selection, attribute, header_of_page, line_label_of
from modules.scan.domain.ocr_result import page_read_from_json
from modules.scan.domain.review import count_rows, fingerprint

MAX_PAGES = 20
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
FORM_HINTS = frozenset({"fabrication", "conditionnement", "bobines"})

_SESSION_NAMES = (
    "id", "kind", "work_center_id", "report_date", "shift", "default_of_id", "shift_report_id", "status",
    "review_state", "created_by", "created_at", "applied_at",
)
_PAGE_NAMES = (
    "id", "status", "form_type", "form_hint", "rotation", "width", "height", "attempts", "error", "created_at", "read_at", "ocr_result",
)
_SESSION_NOT_FOUND = Err("NOT_FOUND", "scan session not found", "session de scan introuvable")
_PAGE_NOT_FOUND = Err("NOT_FOUND", "photo not found", "photo introuvable")
_SESSION_CLOSED = Err("SESSION_CLOSED", "this scan is already applied or discarded", "ce scan est déjà enregistré ou abandonné")


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime.date, datetime.datetime)) else value


class ScanSessionService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reading -----------------------------------------------------------

    def _session_row(self, tenant_id: str, session_id: str) -> dict | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_SESSION_NAMES)} FROM scan.scan_sessions WHERE id = %s AND tenant_id = %s",
            (session_id, tenant_id),
        ).fetchone()
        return {name: _iso(value) for name, value in zip(_SESSION_NAMES, row)} if row else None

    def _open_session(self, tenant_id: str, session_id: str) -> Result[dict]:
        session = self._session_row(tenant_id, session_id)
        if session is None:
            return _SESSION_NOT_FOUND
        if session["status"] != "open":
            return _SESSION_CLOSED
        return Ok(session)

    def _window(self, tenant_id: str, shift: str):
        wanted = shift.strip().lower()
        windows = DashboardSettingsService(self._connection).list_shift_windows(tenant_id=tenant_id)
        return next((w for w in windows if w.shift.strip().lower() == wanted), None)

    def _selection(self, tenant_id: str, session: dict) -> Selection | None:
        window = self._window(tenant_id, session["shift"])
        if window is None:
            return None
        lines = WorkCenterService(self._connection).list_work_centers(tenant_id=tenant_id)
        line = next((w for w in lines if w.id == session["work_center_id"]), None)
        return Selection(
            report_date=datetime.date.fromisoformat(session["report_date"]),
            shift_start=window.start,
            line_label=line_label_of(line.code, line.name) if line else None,
        )

    def _shift_state(self, tenant_id: str, session: dict) -> dict | None:
        """The shift report this scan fills, if it exists: its status and every section's rows."""
        reports = ShiftReportService(self._connection)
        wanted = session["shift"].strip().lower()
        shifts = reports.list_shifts(
            tenant_id=tenant_id,
            report_date=datetime.date.fromisoformat(session["report_date"]),
            work_center_id=session["work_center_id"],
        )
        match = next((s for s in shifts if s["shift"].strip().lower() == wanted), None)
        if match is None:
            return None
        shift = reports.get_shift(tenant_id=tenant_id, shift_report_id=match["id"]).value
        keys = ("id", "status", "team", "conducteur", "agent_fabrication", "machiniste", "aide_machiniste", "default_lot_number")
        return {
            **{key: shift[key] for key in keys},
            "sections": {
                s["key"]: {
                    "status": s["status"], "revision": s["revision"], "rows": count_rows(s["payload"]),
                    "fingerprint": fingerprint(s["payload"]), "payload": s["payload"],
                }
                for s in shift["sections"]
            },
        }

    def _pages(self, tenant_id: str, session_id: str) -> list[dict]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_PAGE_NAMES)} FROM scan.scan_pages WHERE tenant_id = %s AND session_id = %s ORDER BY created_at, id",
            (tenant_id, session_id),
        ).fetchall()
        return [dict(zip(_PAGE_NAMES, row)) for row in rows]

    def _page_summary(self, page: dict, selection: Selection | None) -> dict:
        summary = {name: _iso(page[name]) for name in _PAGE_NAMES if name != "ocr_result"}
        summary["attribution"] = None
        if page["ocr_result"] and selection is not None:
            result = attribute(header_of_page(page_read_from_json(page["id"], page["ocr_result"])), selection)
            summary["attribution"] = {"verdict": result.verdict, "reasons": list(result.reasons), "read": result.read}
        return summary

    def _page(self, tenant_id: str, session_id: str, page_id: str) -> dict | None:
        return next((p for p in self._pages(tenant_id, session_id) if p["id"] == page_id), None)

    def get_session(self, *, tenant_id: str, session_id: str) -> Result[dict]:
        session = self._session_row(tenant_id, session_id)
        if session is None:
            return _SESSION_NOT_FOUND
        selection = self._selection(tenant_id, session)
        window = self._window(tenant_id, session["shift"])
        return Ok({
            **session,
            "pages": [self._page_summary(p, selection) for p in self._pages(tenant_id, session_id)],
            "shift": self._shift_state(tenant_id, session),
            "window": {"start": window.start.strftime("%H:%M"), "end": window.end.strftime("%H:%M")} if window else None,
        })

    def list_sessions(self, *, tenant_id: str, status: str | None = None) -> list[dict]:
        names = [n for n in _SESSION_NAMES if n != "review_state"]
        clause, params = ("s.tenant_id = %s", [tenant_id]) if status is None else ("s.tenant_id = %s AND s.status = %s", [tenant_id, status])
        rows = self._connection.execute(
            f"SELECT {', '.join('s.' + n for n in names)}, "
            f"(SELECT count(*) FROM scan.scan_pages p WHERE p.session_id = s.id) "
            f"FROM scan.scan_sessions s WHERE {clause} ORDER BY s.created_at DESC LIMIT 200",
            params,
        ).fetchall()
        return [{**{n: _iso(v) for n, v in zip(names, row)}, "page_count": row[-1]} for row in rows]

    def page_image(self, *, tenant_id: str, page_id: str) -> Result[tuple[bytes, str]]:
        row = self._connection.execute(
            "SELECT image, content_type FROM scan.scan_pages WHERE id = %s AND tenant_id = %s", (page_id, tenant_id)
        ).fetchone()
        if row is None:
            return _PAGE_NOT_FOUND
        return Ok((bytes(row[0]), row[1]))

    def shift_pages(self, *, tenant_id: str, shift_report_id: str) -> list[dict]:
        """The photos behind a shift report: pages of the scans applied to it."""
        rows = self._connection.execute(
            """
            SELECT p.id, p.session_id, p.form_type, p.rotation, p.width, p.height, p.created_at
            FROM scan.scan_pages p JOIN scan.scan_sessions s ON s.id = p.session_id
            WHERE p.tenant_id = %s AND s.shift_report_id = %s AND s.status = 'applied'
            ORDER BY p.created_at, p.id
            """,
            (tenant_id, shift_report_id),
        ).fetchall()
        names = ("id", "session_id", "form_type", "rotation", "width", "height", "created_at")
        return [{n: _iso(v) for n, v in zip(names, row)} for row in rows]

    # ---- changing ----------------------------------------------------------

    def _audit(self, tenant_id: str, actor_id: str, action: str, session_id: str, payload: dict) -> None:
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action=action,
            entity_type="scan_session", entity_id=session_id, payload=payload,
        )

    def create_session(
        self, *, tenant_id: str, actor_id: str, kind: str, work_center_id: str, report_date: datetime.date,
        shift: str, default_of_id: str | None,
    ) -> Result[dict]:
        if kind != "shift":
            return Err("NOT_SUPPORTED_YET", "only shift fiches can be scanned for now", "seules les fiches de shift peuvent être scannées pour l'instant")
        if self._window(tenant_id, shift or "") is None:
            return Err("UNKNOWN_SHIFT", f"{shift!r} is not one of the plant's shifts", f"{shift!r} ne fait pas partie des shifts de l'usine")
        session_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO scan.scan_sessions (id, tenant_id, kind, work_center_id, report_date, shift, default_of_id, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (session_id, tenant_id, kind, work_center_id, report_date, shift.strip(), default_of_id, actor_id),
        )
        self._audit(tenant_id, actor_id, "scan_session.created", session_id,
                    {"work_center_id": work_center_id, "report_date": report_date.isoformat(), "shift": shift.strip()})
        return Ok(self._session_row(tenant_id, session_id))

    def add_pages(self, *, tenant_id: str, actor_id: str, session_id: str, files: list[dict]) -> Result[list[dict]]:
        found = self._open_session(tenant_id, session_id)
        if isinstance(found, Err):
            return found
        held = self._connection.execute(
            "SELECT count(*) FROM scan.scan_pages WHERE tenant_id = %s AND session_id = %s", (tenant_id, session_id)
        ).fetchone()[0]
        if held + len(files) > MAX_PAGES:
            return Err("TOO_MANY_PAGES", f"a scan holds at most {MAX_PAGES} photos", f"un scan contient au plus {MAX_PAGES} photos")
        decoded: list[tuple[dict, bytes]] = []
        for upload in files:
            if upload.get("content_type") not in IMAGE_TYPES:
                return Err("UNSUPPORTED_IMAGE", "photos must be JPEG, PNG or WebP", "les photos doivent être en JPEG, PNG ou WebP")
            try:
                data = base64.b64decode(upload.get("data_base64") or "", validate=True)
            except (binascii.Error, ValueError):
                return Err("UNSUPPORTED_IMAGE", "a photo could not be decoded", "une photo n'a pas pu être décodée")
            if not data:
                return Err("UNSUPPORTED_IMAGE", "a photo is empty", "une photo est vide")
            if len(data) > MAX_IMAGE_BYTES:
                return Err("IMAGE_TOO_LARGE", "a photo is larger than 8 MB", "une photo dépasse 8 Mo")
            decoded.append((upload, data))
        ids = []
        for upload, data in decoded:
            page_id = str(ULID())
            ids.append(page_id)
            self._connection.execute(
                """
                INSERT INTO scan.scan_pages (id, tenant_id, session_id, image, content_type, filename, width, height, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (page_id, tenant_id, session_id, data, upload["content_type"], upload.get("filename"),
                 upload.get("width"), upload.get("height"), actor_id),
            )
        self._connection.execute("UPDATE scan.scan_sessions SET updated_at = NOW() WHERE id = %s", (session_id,))
        self._audit(tenant_id, actor_id, "scan_session.pages_added", session_id, {"pages": ids})
        return Ok([self._page_summary(self._page(tenant_id, session_id, page_id), None) for page_id in ids])

    def delete_page(self, *, tenant_id: str, actor_id: str, session_id: str, page_id: str) -> Result[None]:
        found = self._open_session(tenant_id, session_id)
        if isinstance(found, Err):
            return found
        page = self._page(tenant_id, session_id, page_id)
        if page is None:
            return _PAGE_NOT_FOUND
        self._connection.execute("DELETE FROM scan.scan_pages WHERE id = %s AND tenant_id = %s", (page_id, tenant_id))
        self._audit(tenant_id, actor_id, "scan_session.page_removed", session_id, {"page_id": page_id, "form_type": page["form_type"]})
        return Ok(None)

    def reread_page(
        self, *, tenant_id: str, actor_id: str, session_id: str, page_id: str, form_hint: str | None
    ) -> Result[dict]:
        found = self._open_session(tenant_id, session_id)
        if isinstance(found, Err):
            return found
        if form_hint is not None and form_hint not in FORM_HINTS:
            return Err("INVALID_VALUE", f"unknown fiche type {form_hint!r}", f"type de fiche inconnu {form_hint!r}")
        if self._page(tenant_id, session_id, page_id) is None:
            return _PAGE_NOT_FOUND
        self._connection.execute(
            "UPDATE scan.scan_pages SET status = 'queued', attempts = 0, error = NULL, form_hint = %s WHERE id = %s AND tenant_id = %s",
            (form_hint, page_id, tenant_id),
        )
        self._audit(tenant_id, actor_id, "scan_session.page_reread", session_id, {"page_id": page_id, "form_hint": form_hint})
        return Ok(self._page_summary(self._page(tenant_id, session_id, page_id), None))

    def discard_session(self, *, tenant_id: str, actor_id: str, session_id: str) -> Result[dict]:
        found = self._open_session(tenant_id, session_id)
        if isinstance(found, Err):
            return found
        self._connection.execute(
            "UPDATE scan.scan_sessions SET status = 'discarded', updated_at = NOW() WHERE id = %s AND tenant_id = %s",
            (session_id, tenant_id),
        )
        self._audit(tenant_id, actor_id, "scan_session.discarded", session_id, {})
        return Ok(self._session_row(tenant_id, session_id))
