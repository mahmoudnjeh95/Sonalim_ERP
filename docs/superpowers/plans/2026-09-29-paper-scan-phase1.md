# Paper Scan — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user photographs the *Fiche fabrication* and *Fiche conditionnement* of a shift, the server reads them locally, the user reviews every value (yellow = doubt, red = required) against the photo, and the reviewed values are saved into the shift report as drafts.

**Architecture:** A new `scan` module (backend) owns sessions, photos (bytea), a learning dictionary and accuracy outcomes; it reads and writes production only through `ShiftReportService` and other `api/` services. A new stateless `ocr` container (RapidOCR on ONNX Runtime + OpenCV) turns one photo into raw cells by locating the fiche's printed anchors; all interpretation (parsing, dictionary, cross-checks, the proposal) is pure domain code in `scan/domain`. The worker reads queued photos one at a time in its own thread. The frontend adds a *Scanner* tab in Production that reuses the shift form's grids with a per-cell `decorate` hook.

**Tech Stack:** FastAPI, psycopg 3 (raw SQL), pytest; RapidOCR (`rapidocr` + `onnxruntime`), `opencv-python-headless`, numpy; React 18 + TS, TanStack Query, Tailwind, vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-paper-scan-design.md` (phase 1 only; phases 2 and 3 are out of this plan).

## Global Constraints

- Local OCR only; no image leaves the server. The OCR container has no DB access, no secrets, no published port; `mem_limit: 1536m`, `cpus: 2`, one request at a time.
- The scan **saves drafts only** (`ShiftReportService.save_section`); it never submits, never writes a validated shift (`SHIFT_VALIDATED`).
- Overwrite is chosen per section: *Remplacer* / *Garder l'existant*, default **Garder l'existant**; a section with no existing data shows no choice.
- One default OF, changeable per row.
- Dictionary kinds: `raw_material`, `regrind_item`, `finished_product`, `film_item`, `waste_production`, `waste_packing`, `equipment`, `mold`, `downtime_motif`, `line_state`, `check_state`, `team`, `person`.
- No invented thresholds: a cross-check fires on a recorded value (lot vs date, packing format vs product net weight, paper date/hours/line vs the selection); "low confidence" = below the OCR engine's own acceptance score, reported by the container.
- `scan` never touches another module's tables; permissions in `module.json`: `scan.use_scanner`, `scan.view_scans`, `scan.admin_aliases`. Writing a section also needs `production.shift.edit.<section>`.
- Every mutation calls `record_audit` in the same transaction — except the review autosave (`PUT /scan/sessions/{id}/review`), a working copy saved every few seconds; the apply is audited with the final result.
- Every `Err` carries `message_fr` (bilingual errors guard). UI strings bilingual via the `L(en, fr)` / `useLabel` helper (`features/production/shift/shiftText.ts`); the tab label in `i18n.en.ts` + `i18n.fr.ts`.
- Migrations are schema only (no `INSERT … VALUES`); never edit an applied one.
- Uploads: JPEG/PNG/WebP, ≤ 8 MB decoded each, ≤ 20 pages per session, sent as base64 JSON (the stack has no `python-multipart`; `apiFetch` is JSON-only). The browser applies EXIF rotation and downscales to 2400 px on the long side.
- The example photos contain workers' names: **never commit them**. OCR photo tests read `OCR_FIXTURES_DIR` and skip when absent.
- Don't push; a push to `huge_production_migration` deploys.

## Deviations from the spec (decided while planning)

- **Uploads are base64 JSON, not multipart**: the backend has no `python-multipart` and `apiFetch` sends JSON only; the size cost (~33 %) is irrelevant at ≤ 8 MB.
- **A page's attribution is computed when read, not stored**: `scan_pages` keeps `ocr_result` only (no `attribution` / `detected_header` columns), so a page never shows a stale verdict after the session's choices change.
- **Sacs × bag weight vs tonnes check is not in phase 1**: no product records a per-bag weight today, and the rule is to check only against recorded values.
- **An extra read-only endpoint `GET /scan/vocabulary`** feeds the Dictionnaire screen's value labels and edit choices.

## Review Focus

- **A photo whose OCR finds nothing (blurred, dark, a hand over the page):** the page must end `unrecognized` with "Choisir le type de fiche" and a re-read, never crash the reader loop or block the queue — pinned in Task 13 (`test_an_unrecognized_page_does_not_stop_the_queue`).
- **The OCR container down or slow during a batch upload:** pages must go back to `queued` and be retried, `failed` only after 3 pickups, and a worker restart must requeue pages stuck in `reading` — pinned in Task 13 (`test_ocr_down_requeues_then_fails_after_three`, `test_requeue_stale_reads`).
- **The team edits the section in the shift form while someone reviews a scan of it:** apply must refuse with `SECTION_CHANGED` rather than silently replace — pinned in Task 11 (`test_apply_refuses_a_section_changed_since_review`).
- **Two photos of the same fiche (a retake):** no duplicated rows (a silo `start` listed twice is refused by production) — pinned in Task 4 (`test_two_photos_of_the_same_block_merge_cell_by_cell`) and Task 7 (`test_a_retake_does_not_duplicate_silo_rows`).
- **A night shift (23–07):** times after midnight must land on the next day, or production refuses a stop that "ends before it starts" — pinned in Task 5 (`test_night_shift_times_after_midnight_are_next_day`).

---

## File structure

**Backend — new module `backend/modules/scan/`**

| File | Responsibility |
|---|---|
| `module.json` | manifest, permissions |
| `__init__.py`, `domain/__init__.py`, `api/__init__.py` | packages |
| `migrations/0001_scan_init.sql` | `scan.scan_sessions`, `scan_pages`, `scan_aliases`, `scan_field_outcomes` |
| `domain/text.py` | normalize, tokens, parse decimal/percent/int/time/date/lot, find times/intervals, decode lot, team letter |
| `domain/vocabulary.py` | `Term`, `Vocabulary`, `Resolution`, `resolve()` |
| `domain/ocr_result.py` | the OCR contract as dataclasses; `page_read_from_json()` |
| `domain/merge.py` | several photos of one fiche → one `PageRead` |
| `domain/attribution.py` | does a page belong to the selected shift |
| `domain/draft.py` | `ProposalContext`, `Draft` (rows, flags, sources, coded values, lots, loss pairing) |
| `domain/common.py` | header, stops and silo mappers shared by both fiches |
| `domain/fabrication.py` | *Fiche fabrication* → sections |
| `domain/conditionnement.py` | *Fiche conditionnement* → sections |
| `domain/proposal.py` | `build_proposal()` |
| `domain/review.py` | fingerprints, final values by path, private-key stripping, apply order |
| `domain/test_*.py` | unit tests (no DB) |
| `api/vocabulary_service.py` | builds the `Vocabulary` from core/production/maintenance services |
| `api/alias_service.py` | `ScanAliasService` |
| `api/session_service.py` | `ScanSessionService` (sessions, pages, proposal, review, apply) |
| `api/ocr_client.py` | HTTP call to the OCR container |
| `api/reader.py` | one queue step: pick, read, store |
| `api/router.py` | `/scan/...` endpoints |
| `api/test_*_integration.py` | DB tests |

**Backend — modified:** `core/migrations/runner.py` (register `scan`), `app/main.py` (router), `worker/main.py` (reader thread).

**OCR container — new `ocr/`:** `Dockerfile`, `requirements.txt`, `app/__init__.py`, `app/engine.py` (RapidOCR adapter), `app/geometry.py`, `app/templates.py`, `app/locate.py` (pure anchor/cell logic), `app/pipeline.py` (image → result), `app/main.py` (FastAPI), `templates/fabrication.json`, `templates/conditionnement.json`, `templates/bobines.json`, `tests/test_locate.py`, `tests/test_photos.py`, `README.md` (how to run the probe and calibrate).

**Deploy — modified:** `compose.yaml`, `.github/workflows/deploy.yml`.

**Frontend — new `frontend/src/features/scan/`:** `scanApi.ts`, `imagePrep.ts`, `scanText.ts`, `reviewModel.ts` (+ `reviewModel.test.ts`), `ScanTab.tsx`, `ScanStart.tsx`, `ScanSessionsTable.tsx`, `ScanWorkspace.tsx`, `PhotosPanel.tsx`, `PageImage.tsx`, `ReviewPanel.tsx`, `PhotoViewer.tsx`, `ApplyDialog.tsx`, `AliasesTable.tsx`, `ShiftPaperPages.tsx`.

**Frontend — modified:** `features/production/shift/ShiftGrid.tsx` (`decorate`), `features/production/shift/SectionCard.tsx` (`Part` passes `decorate`), `features/production/ProductionPage.tsx` (tab), `routes/Sidebar.tsx` (tab), `lib/i18n.en.ts` + `lib/i18n.fr.ts` (tab label), `features/production/shift/ShiftReportTab.tsx` (import button + paper pages).

## Contracts shared across tasks

**Field path** (flags, sources, coded values, outcomes): `"{section}/{part}/{ref}/{field}"`. A row's `ref` is its `_scan_ref` (`"{page_id}:{block}:{row_index}"`, plus `":sem"`, `":broy"`, or `":{n}"` for derived rows). A single-record part (staffing) uses ref `-`. Header fields: `"header/-/-/{field}"`. A section-wide notice: `"{section}/-/-/-"`.

**OCR result** (`POST /read` response; boxes are fractions 0–1 of the **upright** image; `rotation` is the clockwise rotation, in degrees, that made the upload upright):

```json
{
  "form_type": "fabrication",
  "form_confidence": 0.8,
  "rotation": 0,
  "accept_score": 0.5,
  "header": {"date": {"text": "Le07/09/2026", "confidence": 0.81, "box": [0.62, 0.07, 0.8, 0.1]}},
  "blocks": [{"key": "production", "found": true, "rows": [{"cells": {"lot": {"text": "D6249SNL", "confidence": 0.7, "box": [0.1, 0.2, 0.15, 0.3]}}}]}]
}
```

Header keys: `date`, `team_hours` (everything right of "Equipe"), `line_pc`, `line_pl` (`"x"` when ticked), and names (`conducteur`, `agent_fabrication` | `machiniste`, `aide_machiniste`).
Block keys and cell keys:

| form | block | cells |
|---|---|---|
| fabrication | `production` | `lot product start end sem_origin sem_lot sem_bags sem_tonnes broy_lot broy_percent broy_bags broy_kg water humidity` |
| fabrication | `waste_petrin`, `waste_finished` | `time format lot quantity cause` |
| fabrication | `mold_washes` | `mold time state` |
| fabrication | `staffing` | `control_room petrin semoule broyage` (one row) |
| both | `stops` | `panne start end action` |
| both | `silo_start`, `silo_end` | `format lot level line_state` |
| conditionnement | `packing` | `format lot fab_date pack_type film_type cartons bobine scotch ruban` |
| conditionnement | `packet_checks` | `time film weight long_weld vert_weld date_print observation` |
| conditionnement | `waste` | `time type quantity cause` |
| bobines | `changes` | `date team hours machine counter format reel_type internal_lot start end reel_weight core_weight waste remain_weight remain_conf remain_nonconf machinist` |

**Proposal JSON** (`GET /scan/sessions/{id}/proposal` → `proposal`):
`{header, sections: {section: {part: rows | record}}, flags: {path: [{reason, detail}]}, sources: {path: [{page_id, box, text, confidence}]}, coded: {path: {kind, read_text, value}}, set_aside: {section: [{part, row, reason}]}, pages: {page_id: {form_type, verdict, reasons, read, importable, included}}}`.

**Flag reasons:** `low_confidence`, `unreadable`, `lookalike`, `lot_format`, `unresolved`, `ambiguous`, `partial_match`, `conflicting`, `rows_disagree`, `lot_date`, `lot_team`, `team_mismatch`, `short_lot`, `inferred_stop`, `split_stop`, `fab_date`, `format_mismatch`, `of_product`. Set-aside reason: `same_loss`.

---

### Task 1: `scan` module skeleton, schema and registration

**Files:**
- Create: `backend/modules/scan/module.json`, `backend/modules/scan/__init__.py`, `backend/modules/scan/domain/__init__.py`, `backend/modules/scan/api/__init__.py`
- Create: `backend/modules/scan/migrations/0001_scan_init.sql`
- Modify: `backend/core/migrations/runner.py:15-38`
- Test: `backend/modules/scan/api/test_schema_integration.py`

**Interfaces:**
- Produces: tables `scan.scan_sessions`, `scan.scan_pages`, `scan.scan_aliases`, `scan.scan_field_outcomes` (columns below); permissions `scan.use_scanner`, `scan.view_scans`, `scan.admin_aliases` in the catalog.

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/scan/api/test_schema_integration.py
"""The scan schema exists once migrations have run, and its permissions reach the catalog."""
from __future__ import annotations

from core.permissions_registry import permission_catalog


def _columns(db, table: str) -> set[str]:
    rows = db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'scan' AND table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def test_scan_tables_exist(db):
    assert {"id", "tenant_id", "kind", "work_center_id", "report_date", "shift", "default_of_id",
            "shift_report_id", "status", "review_state", "created_by", "applied_at"} <= _columns(db, "scan_sessions")
    assert {"id", "tenant_id", "session_id", "image", "content_type", "status", "attempts", "form_hint",
            "form_type", "rotation", "ocr_result", "error", "read_at"} <= _columns(db, "scan_pages")
    assert {"tenant_id", "kind", "raw_text_normalized", "raw_text_example", "target_value", "use_count"} <= _columns(db, "scan_aliases")
    assert {"session_id", "field_path", "read_text", "proposed_value", "final_value", "changed"} <= _columns(db, "scan_field_outcomes")


def test_scan_permissions_are_in_the_catalog():
    codes = {entry["permission"] for entry in permission_catalog() if entry["module"] == "scan"}
    assert codes == {"scan.use_scanner", "scan.view_scans", "scan.admin_aliases"}
```

- [ ] **Step 2: Run it to verify it fails**

Run (from `backend/`): `.venv/Scripts/python -m pytest modules/scan/api/test_schema_integration.py -q`
Expected: FAIL/ERROR — `modules.scan` missing (or the columns sets are empty).

- [ ] **Step 3: Create the module files**

`backend/modules/scan/module.json`:

```json
{
  "name": "scan",
  "version": "0.1.0",
  "depends": ["core", "production"],
  "optional_depends": ["maintenance", "qc"],
  "provides_api": ["ScanSessionService", "ScanAliasService"],
  "publishes_events": [],
  "subscribes_events": [],
  "migrations_path": "./migrations",
  "permissions": ["scan.use_scanner", "scan.view_scans", "scan.admin_aliases"]
}
```

`backend/modules/scan/__init__.py`, `backend/modules/scan/domain/__init__.py`, `backend/modules/scan/api/__init__.py`: empty files.

`backend/modules/scan/migrations/0001_scan_init.sql`:

```sql
-- Paper scan: photos of the shift fiches, what the OCR read on them, the review in
-- progress, the codes the plant writes (learned from corrections) and, once applied,
-- how each proposed value compared with what the user kept.
CREATE SCHEMA IF NOT EXISTS scan;

CREATE TABLE IF NOT EXISTS scan.scan_sessions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('shift', 'qc')),
    work_center_id TEXT NOT NULL,
    report_date DATE NOT NULL,
    shift TEXT NOT NULL,
    default_of_id TEXT,
    shift_report_id TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'applied', 'discarded')),
    review_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_by TEXT,
    applied_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS scan_sessions_tenant_created ON scan.scan_sessions (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS scan_sessions_shift_report ON scan.scan_sessions (tenant_id, shift_report_id);

CREATE TABLE IF NOT EXISTS scan.scan_pages (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES scan.scan_sessions (id) ON DELETE CASCADE,
    image BYTEA NOT NULL,
    content_type TEXT NOT NULL,
    filename TEXT,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'reading', 'read', 'unrecognized', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    form_hint TEXT,
    form_type TEXT,
    rotation INTEGER NOT NULL DEFAULT 0,
    ocr_result JSONB,
    error TEXT,
    uploaded_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS scan_pages_session ON scan.scan_pages (session_id, created_at);
CREATE INDEX IF NOT EXISTS scan_pages_queued ON scan.scan_pages (created_at) WHERE status = 'queued';

CREATE TABLE IF NOT EXISTS scan.scan_aliases (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    raw_text_normalized TEXT NOT NULL,
    raw_text_example TEXT NOT NULL,
    target_value TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, kind, raw_text_normalized)
);

CREATE TABLE IF NOT EXISTS scan.scan_field_outcomes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES scan.scan_sessions (id) ON DELETE CASCADE,
    page_id TEXT,
    field_path TEXT NOT NULL,
    read_text TEXT,
    confidence NUMERIC,
    proposed_value TEXT,
    final_value TEXT,
    flag TEXT,
    changed BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS scan_field_outcomes_path ON scan.scan_field_outcomes (tenant_id, field_path);
```

- [ ] **Step 4: Register the module's migrations**

In `backend/core/migrations/runner.py`, add to `MODULE_MIGRATION_DIRS` after `"maintenance"`:

```python
    "scan": REPO_ROOT / "modules" / "scan" / "migrations",
```

and append `"scan"` to `MODULE_ORDER` (it reads production and maintenance only through their services, so last is fine); add a line to the comment above it:

```python
# scan runs last: it holds no foreign key into another module and reads them only
# through their api services.
MODULE_ORDER = ["core", "warehouse", "production", "crm", "sales", "finance", "hr", "payroll", "procurement", "qc", "maintenance", "scan"]
```

- [ ] **Step 5: Apply the migration to the dev database and run the test**

Run (from `backend/`):
`.venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv('../.env'); from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
then `.venv/Scripts/python -m pytest modules/scan/api/test_schema_integration.py core/migrations/test_migration_data_guard.py -q`
Expected: PASS (not skipped — if skipped, the DB is unreachable; start Postgres first).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/scan backend/core/migrations/runner.py
git commit -m "feat(scan): scan module skeleton and schema"
```

---

### Task 2: Reading handwritten values (`domain/text.py`)

**Files:**
- Create: `backend/modules/scan/domain/text.py`
- Test: `backend/modules/scan/domain/test_text.py`

**Interfaces:**
- Produces: `Parsed(value, sure=True)`, `NOTHING`, `UNREADABLE`, `normalize(text) -> str`, `tokens(text) -> set[str]`, `parse_decimal`, `parse_percent`, `parse_int`, `parse_time`, `parse_date`, `parse_lot` (each `(str | None) -> Parsed`), `find_times(text) -> list[Parsed]`, `find_intervals(text) -> list[tuple[Parsed, Parsed]]`, `first_number(text) -> float | None`, `is_short_lot(lot) -> bool`, `decode_lot(lot, around: date) -> tuple[str, date] | None`, `team_letter(text) -> str | None`, `team_and_hours(text) -> tuple[str | None, time | None]`, `minutes_between(start: time, end: time) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/domain/test_text.py
import datetime

import pytest

from modules.scan.domain.text import (
    NOTHING, UNREADABLE, decode_lot, find_intervals, find_times, first_number, is_short_lot, minutes_between,
    normalize, parse_date, parse_decimal, parse_int, parse_lot, parse_percent, parse_time, team_and_hours,
    team_letter, tokens,
)


def test_normalize_drops_case_accents_and_punctuation():
    assert normalize("  Déchet  Presse! ") == "dechet presse"
    assert normalize(None) == ""


def test_tokens_meet_singular_and_plural():
    assert tokens("Vermicelles") == {"vermicelle"}


@pytest.mark.parametrize("text, value, sure", [
    ("02,46kg", 2.46, True), ("0,35Kg", 0.35, True), ("75,28Kgs", 75.28, True), ("00", 0.0, True),
    ("3,25", 3.25, True), ("(500g)", 500.0, True), ("O5", 5.0, False), ("|", 1.0, False),
])
def test_decimals(text, value, sure):
    parsed = parse_decimal(text)
    assert parsed.value == pytest.approx(value) and parsed.sure is sure


def test_decimal_empty_and_unreadable():
    assert parse_decimal("") == NOTHING
    assert parse_decimal("-") == UNREADABLE


def test_percent_over_100_is_not_a_percent():
    assert parse_percent("29 %").value == 29
    assert parse_percent("129") == UNREADABLE


def test_int():
    assert parse_int("65").value == 65
    assert parse_int("6,5") == UNREADABLE


@pytest.mark.parametrize("text, expected", [
    ("09h27mn", datetime.time(9, 27)), ("14h", datetime.time(14, 0)), ("12H18", datetime.time(12, 18)),
    ("07:00", datetime.time(7, 0)), ("07 H", datetime.time(7, 0)),
])
def test_times(text, expected):
    assert parse_time(text).value == expected


def test_a_cell_with_two_times_is_not_one_time():
    assert parse_time("10h43-10h53") == UNREADABLE


def test_times_inside_a_sentence():
    assert [p.value for p in find_times("Démarrage de la production à 09h27mn")] == [datetime.time(9, 27)]


def test_intervals():
    pairs = find_intervals("Alarme silo à reprises 10h43-10h53, 12h56-12h58")
    assert [(a.value, b.value) for a, b in pairs] == [
        (datetime.time(10, 43), datetime.time(10, 53)), (datetime.time(12, 56), datetime.time(12, 58)),
    ]


@pytest.mark.parametrize("text, expected, sure", [
    ("Le07/09/2026", datetime.date(2026, 9, 7), True), ("07/09/26", datetime.date(2026, 9, 7), True),
    ("07.09.26", datetime.date(2026, 9, 7), True), ("07-0926", datetime.date(2026, 9, 7), False),
])
def test_dates(text, expected, sure):
    parsed = parse_date(text)
    assert parsed.value == expected and parsed.sure is sure


def test_lots():
    assert parse_lot("D6249SNL").value == "D6249SNL"
    assert parse_lot("d6249 snl").value == "D6249SNL"
    assert parse_lot("D6249").value == "D6249" and is_short_lot("D6249")
    odd = parse_lot("vermicelle")
    assert odd.value == "VERMICELLE" and odd.sure is False


def test_decode_lot_is_team_year_digit_and_day_of_year():
    assert decode_lot("D6249SNL", datetime.date(2026, 9, 7)) == ("D", datetime.date(2026, 9, 6))
    assert decode_lot("nonsense", datetime.date(2026, 9, 7)) is None


def test_team_letters():
    assert team_letter("Equipe D") == "D"
    assert team_letter("Eq A") == "A"
    assert team_letter("") is None
    assert team_and_hours("D 07 H à 14H00") == ("D", datetime.time(7, 0))


def test_first_number_and_minutes():
    assert first_number("(500g)") == 500
    assert first_number("Active") is None
    assert minutes_between(datetime.time(7, 0), datetime.time(14, 0)) == 420
    assert minutes_between(datetime.time(23, 0), datetime.time(7, 0)) == 480
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_text.py -q`
Expected: FAIL — `ModuleNotFoundError: modules.scan.domain.text`.

- [ ] **Step 3: Implement**

```python
# backend/modules/scan/domain/text.py
"""Reading handwritten cells: numbers, times, dates, lots, and text to compare.

Every parser returns a `Parsed`. `value` is None when nothing usable was read; `sure`
is False when the reading had to be bent to fit (an O read as a zero, a stroke read as
a one) or could not be read at all. Nothing here judges whether a value is plausible
for the plant -- only whether the handwriting can be read as that kind of value.
"""
from __future__ import annotations

import calendar
import datetime
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Parsed:
    value: Any
    sure: bool = True


NOTHING = Parsed(None, True)  # an empty cell: nothing to read, nothing to doubt
UNREADABLE = Parsed(None, False)  # ink that is not a value of this kind

# Characters handwriting and OCR confuse with digits; folded only where a digit is expected.
_LOOKALIKES = str.maketrans({"o": "0", "O": "0", "l": "1", "I": "1", "|": "1"})
_TRAILING_UNIT = re.compile(r"(kgs?|g|t|mn|min|%)$", re.IGNORECASE)
_TIME = re.compile(r"(?<!\d)(\d{1,2})\s*[hH:]\s*(\d{2})?(?!\d)")
_DATE = re.compile(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})")
# 07-0926: the second separator left out.
_DATE_RUN_ON = re.compile(r"(\d{1,2})\s*[/.\-]\s*(\d{2})(\d{2})(?!\d)")
_LOT = re.compile(r"([A-Z])(\d)(\d{3})([A-Z]{2,4})?")
_INTERVAL_SEPARATORS = {"-", "–", "—", "a", "à", "au", "/"}


def normalize(text: str | None) -> str:
    """Lower case, no accents, punctuation as spaces, single spaces: the form compared and learned."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def tokens(text: str | None) -> set[str]:
    """The words of a text, a plural `s` dropped so "Vermicelles" meets "Vermicelle"."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in normalize(text).split()}


def _exact(raw: str, folded: str, start: int, end: int) -> bool:
    return raw[start:end] == folded[start:end]


def parse_decimal(text: str | None) -> Parsed:
    raw = (text or "").strip()
    if not raw:
        return NOTHING
    compact = _TRAILING_UNIT.sub("", raw.replace(" ", "").strip("()"))
    folded = compact.translate(_LOOKALIKES)
    candidate = folded.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", candidate):
        return UNREADABLE
    return Parsed(float(candidate), folded == compact)


def parse_percent(text: str | None) -> Parsed:
    parsed = parse_decimal(text)
    if parsed.value is not None and parsed.value > 100:
        return UNREADABLE
    return parsed


def parse_int(text: str | None) -> Parsed:
    parsed = parse_decimal(text)
    if parsed.value is None:
        return parsed
    if not float(parsed.value).is_integer():
        return UNREADABLE
    return Parsed(int(parsed.value), parsed.sure)


def _time_matches(text: str) -> list[tuple[re.Match, Parsed]]:
    raw = text or ""
    folded = raw.translate(_LOOKALIKES)
    found = []
    for match in _TIME.finditer(folded):
        hour, minute = int(match[1]), int(match[2] or 0)
        if hour > 23 or minute > 59:
            continue
        found.append((match, Parsed(datetime.time(hour, minute), _exact(raw, folded, match.start(), match.end()))))
    return found


def find_times(text: str | None) -> list[Parsed]:
    """Every time written in the text, in order: 09h27mn, 14h, 12H18, 07:00."""
    return [parsed for _, parsed in _time_matches(text or "")]


def parse_time(text: str | None) -> Parsed:
    if not (text or "").strip():
        return NOTHING
    found = find_times(text)
    return found[0] if len(found) == 1 else UNREADABLE


def find_intervals(text: str | None) -> list[tuple[Parsed, Parsed]]:
    """Pairs of times written from-to (10h43-10h53, 12h56-12h58), in order."""
    raw = text or ""
    matches = _time_matches(raw)
    pairs: list[tuple[Parsed, Parsed]] = []
    index = 0
    while index + 1 < len(matches):
        (first, start), (second, end) = matches[index], matches[index + 1]
        between = raw[first.end():second.start()].strip().lower()
        if between in _INTERVAL_SEPARATORS:
            pairs.append((start, end))
            index += 2
        else:
            index += 1
    return pairs


def parse_date(text: str | None) -> Parsed:
    raw = (text or "").strip()
    if not raw:
        return NOTHING
    folded = raw.translate(_LOOKALIKES)
    for pattern, well_formed in ((_DATE, True), (_DATE_RUN_ON, False)):
        match = pattern.search(folded)
        if match is None:
            continue
        day, month, year = int(match[1]), int(match[2]), int(match[3])
        if year < 100:
            year += 2000
        try:
            value = datetime.date(year, month, day)
        except ValueError:
            return UNREADABLE
        return Parsed(value, well_formed and _exact(raw, folded, match.start(), match.end()))
    return UNREADABLE


def parse_lot(text: str | None) -> Parsed:
    """A lot as the plant writes it: team letter, year digit, day of the year, plant code (D6249SNL).

    A fiche often leaves the plant code off (D6249); the value is then that short form,
    completed later from a full lot on the same fiches. Text that is no lot at all is
    kept, marked unsure, so the user sees what was written.
    """
    raw = (text or "").strip()
    if not raw:
        return NOTHING
    compact = re.sub(r"\s+", "", raw).upper()
    match = _LOT.search(compact)
    if match is None:
        return Parsed(compact, False)
    return Parsed(match.group(0), True)


def is_short_lot(lot: str | None) -> bool:
    return bool(lot) and re.fullmatch(r"[A-Z]\d{4}", lot) is not None


def decode_lot(lot: str | None, around: datetime.date) -> tuple[str, datetime.date] | None:
    """(team letter, date) a lot names, read the way production's default_lot_number writes it.

    The lot carries only the year's last digit; the year is the nearest to `around` ending in it.
    """
    match = re.match(r"([A-Z])(\d)(\d{3})", lot or "")
    if match is None:
        return None
    letter, digit, day = match[1], int(match[2]), int(match[3])
    year = min((y for y in range(around.year - 5, around.year + 6) if y % 10 == digit), key=lambda y: abs(y - around.year))
    if not 1 <= day <= (366 if calendar.isleap(year) else 365):
        return None
    return letter, datetime.date(year, 1, 1) + datetime.timedelta(days=day - 1)


def team_letter(text: str | None) -> str | None:
    """The team letter in a team's name ("Equipe D", "Eq A", "D"), or None."""
    letters = [w for w in normalize(text).split() if len(w) == 1 and w.isalpha()]
    return letters[-1].upper() if len(letters) == 1 else None


def team_and_hours(text: str | None) -> tuple[str | None, datetime.time | None]:
    """What follows "Equipe :" on a fiche -- "D 07 H à 14H00" -- as (team letter, start hour)."""
    words = normalize(text).split()
    letter = words[0].upper() if words and len(words[0]) == 1 and words[0].isalpha() else None
    times = find_times(text)
    return letter, (times[0].value if times else None)


def first_number(text: str | None) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", text or "")
    return float(match.group(0).replace(",", ".")) if match else None


def minutes_between(start: datetime.time, end: datetime.time) -> int:
    """Minutes from start to end, across midnight when end is earlier."""
    return ((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) % (24 * 60)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_text.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/scan/domain/text.py backend/modules/scan/domain/test_text.py
git commit -m "feat(scan): parse handwritten numbers, times, dates and lots"
```

---

### Task 3: Vocabulary and dictionary resolution (`domain/vocabulary.py`)

**Files:**
- Create: `backend/modules/scan/domain/vocabulary.py`
- Test: `backend/modules/scan/domain/test_vocabulary.py`

**Interfaces:**
- Consumes: `normalize`, `tokens` (Task 2).
- Produces: `KINDS: tuple[str, ...]`, `Term(value, names, attrs={})`, `Vocabulary(terms: Mapping[str, tuple[Term, ...]])` with `.of(kind)`, `.attr(kind, value, key)`, `.label(kind, value)`; `Resolution(value, how, candidates=())` with `.sure`; `resolve(vocabulary, aliases: Mapping[tuple[str, str], str], kind, text, prefer=None) -> Resolution`. `how` ∈ `alias exact narrowed contained ambiguous none empty`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/domain/test_vocabulary.py
from modules.scan.domain.vocabulary import Term, Vocabulary, resolve

VOCAB = Vocabulary({
    "waste_production": (Term("press", ("Presse",)), Term("kneading", ("Pétrin",)), Term("raw_material", ("Matière",))),
    "finished_product": (
        Term("P-VERM", ("Vermicelle 500g PC", "PF-VERM"), {"net_weight_grams": 500}),
        Term("P-VERM-PL", ("Vermicelle 500g PL", "PF-VERM-PL")),
    ),
    "line_state": (Term("running", ("En marche", "Marche")), Term("stopped", ("En arrêt", "Arrêt"))),
    "check_state": (Term("good", ("Bon", "Conforme")), Term("not_good", ("Non bon", "Non conforme"))),
})


def test_a_learned_alias_wins():
    found = resolve(VOCAB, {("raw_material", "bsk1"): "MP-1"}, "raw_material", " BSK1 ")
    assert (found.value, found.how, found.sure) == ("MP-1", "alias", True)


def test_exact_name_or_code():
    assert resolve(VOCAB, {}, "line_state", "En Marche").how == "exact"
    assert resolve(VOCAB, {}, "finished_product", "pf-verm").value == "P-VERM"


def test_contained_name_is_a_partial_match():
    found = resolve(VOCAB, {}, "waste_production", "Déchet Presse")
    assert (found.value, found.how, found.sure) == ("press", "contained", False)


def test_exact_beats_contained():
    assert resolve(VOCAB, {}, "check_state", "Non conforme").value == "not_good"


def test_several_matches_are_narrowed_by_the_preferred_value():
    found = resolve(VOCAB, {}, "finished_product", "Vermicelles", prefer="P-VERM")
    assert (found.value, found.how, found.sure) == ("P-VERM", "narrowed", True)


def test_several_matches_without_preference_are_ambiguous():
    found = resolve(VOCAB, {}, "finished_product", "Vermicelles")
    assert found.value is None and found.how == "ambiguous" and set(found.candidates) == {"P-VERM", "P-VERM-PL"}


def test_unknown_and_empty():
    assert resolve(VOCAB, {}, "waste_production", "Broyage").how == "none"
    assert resolve(VOCAB, {}, "waste_production", "  ").how == "empty"


def test_attr_and_label():
    assert VOCAB.attr("finished_product", "P-VERM", "net_weight_grams") == 500
    assert VOCAB.label("finished_product", "P-VERM") == "Vermicelle 500g PC"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_vocabulary.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# backend/modules/scan/domain/vocabulary.py
"""Turning what is written on a fiche ("BSK1", "Déchet Presse", "C2") into a system value.

A learned alias always wins: it is what a person chose for exactly this writing. Then
an exact name or code, then a name whose words all appear in the writing (or the
reverse) -- a partial match a person should glance at. Several candidates are narrowed
by a preferred value (the default OF's product) when it is one of them; otherwise the
result is ambiguous. Nothing is guessed beyond that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from modules.scan.domain.text import normalize, tokens

KINDS: tuple[str, ...] = (
    "raw_material", "regrind_item", "finished_product", "film_item", "waste_production", "waste_packing",
    "equipment", "mold", "downtime_motif", "line_state", "check_state", "team", "person",
)


@dataclass(frozen=True)
class Term:
    value: str
    names: tuple[str, ...]
    attrs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Vocabulary:
    terms: Mapping[str, tuple[Term, ...]]

    def of(self, kind: str) -> tuple[Term, ...]:
        return tuple(self.terms.get(kind, ()))

    def attr(self, kind: str, value: str, key: str) -> Any:
        term = next((t for t in self.of(kind) if t.value == value), None)
        return term.attrs.get(key) if term else None

    def label(self, kind: str, value: str) -> str | None:
        term = next((t for t in self.of(kind) if t.value == value), None)
        return next((n for n in term.names if n), None) if term else None


@dataclass(frozen=True)
class Resolution:
    value: str | None
    how: str
    candidates: tuple[str, ...] = ()

    @property
    def sure(self) -> bool:
        return self.how in ("alias", "exact", "narrowed")


def _contains(name: str, written: set[str]) -> bool:
    words = tokens(name)
    return bool(words) and (words <= written or written <= words)


def resolve(
    vocabulary: Vocabulary, aliases: Mapping[tuple[str, str], str], kind: str, text: str | None, prefer: str | None = None
) -> Resolution:
    key = normalize(text)
    if not key:
        return Resolution(None, "empty")
    learned = aliases.get((kind, key))
    if learned is not None:
        return Resolution(learned, "alias")
    terms = vocabulary.of(kind)
    exact = list(dict.fromkeys(t.value for t in terms if any(normalize(n) == key for n in t.names)))
    if len(exact) == 1:
        return Resolution(exact[0], "exact")
    written = tokens(text)
    matches = exact or list(dict.fromkeys(t.value for t in terms if any(_contains(n, written) for n in t.names)))
    if prefer is not None and prefer in matches:
        return Resolution(prefer, "narrowed", tuple(matches))
    if len(matches) == 1:
        return Resolution(matches[0], "contained")
    if matches:
        return Resolution(None, "ambiguous", tuple(matches))
    return Resolution(None, "none")
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_vocabulary.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/scan/domain/vocabulary.py backend/modules/scan/domain/test_vocabulary.py
git commit -m "feat(scan): resolve written codes against the vocabulary and learned aliases"
```

---

### Task 4: OCR contract, page merge and page attribution

**Files:**
- Create: `backend/modules/scan/domain/ocr_result.py`, `backend/modules/scan/domain/merge.py`, `backend/modules/scan/domain/attribution.py`
- Test: `backend/modules/scan/domain/test_pages.py`

**Interfaces:**
- Consumes: Task 2 parsers.
- Produces:
  - `ReadCell(text, confidence, box=None, page_id=None, conflict=None)`, `EMPTY_CELL`, `ReadRow(cells)` with `.cell(key)`, `.is_blank()`; `ReadBlock(key, found, rows, rows_disagree=False)`; `PageRead(page_id, form_type, rotation, header, blocks, accept_score)` with `.block(key) -> ReadBlock | None` (found blocks only) and `.head(key) -> ReadCell`; `page_read_from_json(page_id: str, data: dict) -> PageRead`.
  - `merge_pages(pages: Sequence[PageRead]) -> PageRead`.
  - `Selection(report_date, shift_start, line_label)`, `Attribution(verdict, reasons, read)`, `line_label_of(*names) -> str | None`, `header_of_page(page) -> Mapping[str, ReadCell]`, `attribute(header, selection) -> Attribution`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/domain/test_pages.py
import datetime

from modules.scan.domain.attribution import Selection, attribute, header_of_page, line_label_of
from modules.scan.domain.merge import merge_pages
from modules.scan.domain.ocr_result import ReadCell, page_read_from_json

SELECTION = Selection(report_date=datetime.date(2026, 9, 7), shift_start=datetime.time(7, 0), line_label="PC")


def _json(header=None, blocks=None, form_type="fabrication"):
    def cells(values):
        return {k: {"text": v[0], "confidence": v[1], "box": [0.1, 0.1, 0.2, 0.2]} for k, v in values.items()}
    return {
        "form_type": form_type, "rotation": 0, "accept_score": 0.5,
        "header": cells(header or {}),
        "blocks": [{"key": k, "found": True, "rows": [{"cells": cells(r)} for r in rows]} for k, rows in (blocks or {}).items()],
    }


def test_page_read_from_json_keeps_page_ids_and_found_blocks():
    page = page_read_from_json("P1", _json({"date": ("07/09/26", 0.9)}, {"stops": [{"panne": ("coupure", 0.6)}]}))
    assert page.head("date").page_id == "P1"
    assert page.block("stops").rows[0].cell("panne").text == "coupure"
    assert page.block("silo_start") is None
    assert page.head("missing").text == ""


def test_two_photos_of_the_same_block_merge_cell_by_cell():
    a = page_read_from_json("A", _json(blocks={"silo_start": [{"level": ("20 %", 0.4), "lot": ("D6249SNL", 0.9)}]}))
    b = page_read_from_json("B", _json(blocks={"silo_start": [{"level": ("0 %", 0.8), "lot": ("D6249SNL", 0.5)}]}))
    row = merge_pages([a, b]).block("silo_start").rows[0]
    assert (row.cell("level").text, row.cell("level").page_id, row.cell("level").conflict) == ("0 %", "B", "20 %")
    assert (row.cell("lot").page_id, row.cell("lot").conflict) == ("A", None)


def test_blocks_with_different_row_counts_keep_the_longer_one():
    a = page_read_from_json("A", _json(blocks={"stops": [{"panne": ("x", 0.9)}]}))
    b = page_read_from_json("B", _json(blocks={"stops": [{"panne": ("x", 0.9)}, {"panne": ("y", 0.9)}]}))
    block = merge_pages([a, b]).block("stops")
    assert len(block.rows) == 2 and block.rows_disagree


def test_line_label_from_the_line_name():
    assert line_label_of("LIGNE-PC", None) == "PC"
    assert line_label_of("Ligne pâtes longues PL") == "PL"
    assert line_label_of("Broyeur") is None


def test_same_shift():
    page = page_read_from_json("P", _json({"date": ("Le07/09/2026", 0.9), "team_hours": ("D 07 H à 14H00", 0.8), "line_pc": ("x", 0.9)}))
    result = attribute(header_of_page(page), SELECTION)
    assert result.verdict == "this_shift" and result.read == {"date": "2026-09-07", "team": "D", "hours_from": "07:00", "line": "PC"}


def test_other_shift_by_hours_and_line():
    page = page_read_from_json("P", _json({"date": ("07/09/26", 0.9), "team_hours": ("A 15H à 23H", 0.8), "line_pl": ("x", 0.9)}))
    result = attribute(header_of_page(page), SELECTION)
    assert result.verdict == "other_shift" and set(result.reasons) == {"hours", "line"}


def test_nothing_readable_is_unknown():
    page = page_read_from_json("P", _json({}))
    assert attribute(header_of_page(page), SELECTION).verdict == "unknown"


def test_the_bobines_sheet_is_judged_by_its_first_row():
    page = page_read_from_json("P", _json(blocks={"changes": [{"date": ("07/09/26", 0.9), "team": ("A", 0.9), "hours": ("14H23H", 0.9)}]}, form_type="bobines"))
    result = attribute(header_of_page(page), SELECTION)
    assert result.verdict == "other_shift" and result.reasons == ("hours",)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_pages.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement `ocr_result.py`**

```python
# backend/modules/scan/domain/ocr_result.py
"""What the OCR container returns for one photo, as the domain reads it.

The container only locates printed anchors and returns the handwriting found in each
cell with the engine's confidence and the cell's box (fractions of the upright image).
Every cell remembers the photo it came from, so a value can be shown on its photo even
after several photos of the same fiche are merged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class ReadCell:
    text: str
    confidence: float
    box: tuple[float, float, float, float] | None = None
    page_id: str | None = None
    # Another photo's different reading of the same cell, kept so the user can choose.
    conflict: str | None = None


EMPTY_CELL = ReadCell("", 1.0)


@dataclass(frozen=True)
class ReadRow:
    cells: Mapping[str, ReadCell]

    def cell(self, key: str) -> ReadCell:
        return self.cells.get(key, EMPTY_CELL)

    def is_blank(self) -> bool:
        return all(not c.text.strip() for c in self.cells.values())


@dataclass(frozen=True)
class ReadBlock:
    key: str
    found: bool
    rows: tuple[ReadRow, ...]
    # Photos of this block showed different numbers of written rows; the longest was kept.
    rows_disagree: bool = False


@dataclass(frozen=True)
class PageRead:
    page_id: str
    form_type: str | None
    rotation: int
    header: Mapping[str, ReadCell]
    blocks: Mapping[str, ReadBlock] = field(default_factory=dict)
    accept_score: float = 0.5

    def block(self, key: str) -> ReadBlock | None:
        block = self.blocks.get(key)
        return block if block is not None and block.found else None

    def head(self, key: str) -> ReadCell:
        return self.header.get(key, EMPTY_CELL)


def _cell(data: dict, page_id: str) -> ReadCell:
    box = data.get("box")
    return ReadCell(
        text=str(data.get("text") or ""),
        confidence=float(data.get("confidence") or 0.0),
        box=tuple(float(v) for v in box) if box else None,
        page_id=page_id,
    )


def page_read_from_json(page_id: str, data: dict) -> PageRead:
    header = {key: _cell(value, page_id) for key, value in (data.get("header") or {}).items()}
    blocks = {}
    for block in data.get("blocks") or []:
        rows = tuple(
            ReadRow({key: _cell(value, page_id) for key, value in (row.get("cells") or {}).items()})
            for row in block.get("rows") or []
        )
        blocks[block["key"]] = ReadBlock(block["key"], bool(block.get("found")), rows)
    return PageRead(
        page_id=page_id,
        form_type=data.get("form_type"),
        rotation=int(data.get("rotation") or 0),
        header=header,
        blocks=blocks,
        accept_score=float(data.get("accept_score") or 0.5),
    )
```

- [ ] **Step 4: Implement `merge.py`**

```python
# backend/modules/scan/domain/merge.py
"""One fiche from several photos of it: the best reading of each cell wins.

Photos of the same block with the same number of written rows are merged cell by cell,
and a cell whose readings differ keeps the other reading as its `conflict`. When the
row counts differ the block with more written rows is kept whole and marked
`rows_disagree`: lining rows up across photos would be a guess.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from modules.scan.domain.ocr_result import PageRead, ReadBlock, ReadCell, ReadRow
from modules.scan.domain.text import normalize


def _better(a: ReadCell, b: ReadCell) -> ReadCell:
    if not a.text.strip():
        return b
    if not b.text.strip():
        return a
    keep, other = (a, b) if a.confidence >= b.confidence else (b, a)
    if normalize(keep.text) == normalize(other.text):
        return keep
    return replace(keep, conflict=other.text)


def _merge_cells(maps: Sequence[Mapping[str, ReadCell]]) -> dict[str, ReadCell]:
    out: dict[str, ReadCell] = {}
    for cells in maps:
        for key, cell in cells.items():
            out[key] = _better(out[key], cell) if key in out else cell
    return out


def _written(block: ReadBlock) -> list[ReadRow]:
    return [row for row in block.rows if not row.is_blank()]


def _merge_blocks(blocks: list[ReadBlock]) -> ReadBlock:
    if len(blocks) == 1:
        return blocks[0]
    rows = [_written(block) for block in blocks]
    if len({len(r) for r in rows}) == 1:
        merged = tuple(ReadRow(_merge_cells([r[i].cells for r in rows])) for i in range(len(rows[0])))
        return ReadBlock(blocks[0].key, True, merged)
    widest = max(range(len(blocks)), key=lambda i: len(rows[i]))
    return ReadBlock(blocks[0].key, True, tuple(rows[widest]), rows_disagree=True)


def merge_pages(pages: Sequence[PageRead]) -> PageRead:
    first = pages[0]
    if len(pages) == 1:
        return first
    keys = dict.fromkeys(key for page in pages for key, block in page.blocks.items() if block.found)
    blocks = {key: _merge_blocks([p.blocks[key] for p in pages if key in p.blocks and p.blocks[key].found]) for key in keys}
    return PageRead(
        page_id=first.page_id,
        form_type=first.form_type,
        rotation=first.rotation,
        header=_merge_cells([page.header for page in pages]),
        blocks=blocks,
        accept_score=first.accept_score,
    )
```

- [ ] **Step 5: Implement `attribution.py`**

```python
# backend/modules/scan/domain/attribution.py
"""Does a photographed fiche belong to the shift the user picked?

The user always picks line, date and shift first; each page's own header is compared
with that choice. A different date, start hour or ticked line puts the page aside as
another shift's -- the example upload mixed a team D morning fiche with a team A
afternoon bobines sheet. A header with neither a date nor an hour read is "unknown":
included, but nothing on it confirms the shift.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Mapping

from modules.scan.domain.ocr_result import EMPTY_CELL, PageRead, ReadCell
from modules.scan.domain.text import normalize, parse_date, team_and_hours


@dataclass(frozen=True)
class Selection:
    report_date: datetime.date
    shift_start: datetime.time
    line_label: str | None


@dataclass(frozen=True)
class Attribution:
    verdict: str  # this_shift | other_shift | unknown
    reasons: tuple[str, ...]  # date | hours | line
    read: dict


def line_label_of(*names: str | None) -> str | None:
    """PC or PL when a line's code or name says so -- the box ticked on the fiche."""
    for name in names:
        words = normalize(name).split()
        if "pc" in words:
            return "PC"
        if "pl" in words:
            return "PL"
    return None


def header_of_page(page: PageRead) -> Mapping[str, ReadCell]:
    """The cells that say whose fiche it is.

    The bobines sheet has no header: every row names its date, team and working hours,
    so its first written row stands for the page.
    """
    if page.form_type != "bobines":
        return page.header
    block = page.block("changes")
    row = next((r for r in block.rows if not r.is_blank()), None) if block else None
    if row is None:
        return {}
    team, hours = row.cell("team"), row.cell("hours")
    return {"date": row.cell("date"), "team_hours": ReadCell(f"{team.text} {hours.text}".strip(), min(team.confidence, hours.confidence))}


def _ticked_line(header: Mapping[str, ReadCell]) -> str | None:
    pc = bool(header.get("line_pc", EMPTY_CELL).text.strip())
    pl = bool(header.get("line_pl", EMPTY_CELL).text.strip())
    if pc == pl:
        return None
    return "PC" if pc else "PL"


def attribute(header: Mapping[str, ReadCell], selection: Selection) -> Attribution:
    date = parse_date(header.get("date", EMPTY_CELL).text).value
    team, hours = team_and_hours(header.get("team_hours", EMPTY_CELL).text)
    line = _ticked_line(header)
    reasons: list[str] = []
    if date is not None and date != selection.report_date:
        reasons.append("date")
    if hours is not None and hours.hour != selection.shift_start.hour:
        reasons.append("hours")
    if line is not None and selection.line_label is not None and line != selection.line_label:
        reasons.append("line")
    read = {
        "date": date.isoformat() if date else None,
        "team": team,
        "hours_from": hours.strftime("%H:%M") if hours else None,
        "line": line,
    }
    if reasons:
        return Attribution("other_shift", tuple(reasons), read)
    if date is None and hours is None:
        return Attribution("unknown", (), read)
    return Attribution("this_shift", (), read)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_pages.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/scan/domain/ocr_result.py backend/modules/scan/domain/merge.py backend/modules/scan/domain/attribution.py backend/modules/scan/domain/test_pages.py
git commit -m "feat(scan): OCR page contract, merging retakes, and matching a page to the shift"
```

### Task 5: The draft proposal and the mappers both fiches share

**Files:**
- Create: `backend/modules/scan/domain/draft.py`, `backend/modules/scan/domain/common.py`, `backend/modules/scan/domain/example_pages.py`
- Test: `backend/modules/scan/domain/test_draft.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `path(section, part, ref, field) -> str`, `header_path(field)`, `section_path(section)`.
  - `ProposalContext(report_date, shift_start, shift_end, team, default_of_id, default_product_id, vocabulary, aliases)` with `.at(time) -> str` (ISO minutes, next day after midnight on a night shift).
  - `Draft(ctx)`: attributes `header`, `sections`, `flags`, `sources`, `coded`, `set_aside`, `team_letter_read`, `fabrication_losses`, `accept_score`; methods `rows(section, part)`, `add_row(section, part, ref, row) -> dict`, `single(section, part) -> dict`, `flag(at, reason, detail=None)`, `see(at, cell)`, `text/decimal/percent/integer/time/date(at, cell)`, `code(at, kind, cell, *, prefer=None, quiet=False)`, `lot(at, cell, row, field, *, check=False)`, `finish()`, `to_json(pages) -> dict`.
  - `map_header(page, draft, person_fields)`, `map_stops(page, draft, block_key)`, `map_silo(page, draft, side)`.
  - `example_pages`: `VOCABULARY`, `context(**overrides)`, `make_page(page_id, form_type, header, blocks, confidence=0.9)`, `fabrication_page(page_id="FAB")`, `conditionnement_page(page_id="COND")`, `bobines_page(page_id="BOB")`.

- [ ] **Step 1: Write the example pages used by the domain tests**

```python
# backend/modules/scan/domain/example_pages.py
"""The client's example fiches (07/09/2026, line PC, team D) as the OCR would return them.

Transcribed from the photos, with the workers' names replaced: the photos themselves
are never committed. Used by the domain tests only.
"""
from __future__ import annotations

import datetime

from modules.scan.domain.draft import ProposalContext
from modules.scan.domain.ocr_result import PageRead, ReadBlock, ReadCell, ReadRow
from modules.scan.domain.vocabulary import Term, Vocabulary

VOCABULARY = Vocabulary({
    "finished_product": (Term("P-VERM", ("Vermicelle 500g PC", "PF-VERM-500"), {"net_weight_grams": 500}),),
    "raw_material": (Term("MP-SSSE", ("Semoule SSSE", "MP-SSSE")),),
    "regrind_item": (Term("RB-PC", ("Rebroyat PC",)),),
    "film_item": (Term("FILM-ACT", ("Film Active PC 390mm",)),),
    "waste_production": (Term("press", ("Presse",)), Term("raw_material", ("Matière",)), Term("kneading", ("Pétrin",))),
    "waste_packing": (Term("product", ("Produit",)), Term("packaging", ("Emballage",))),
    "line_state": (Term("running", ("En marche", "Marche")), Term("stopped", ("En arrêt", "Arrêt"))),
    "check_state": (Term("good", ("Bon", "B", "OK", "Conforme")), Term("not_good", ("Non bon", "NB", "Non conforme"))),
    "team": (Term("Equipe D", ("Equipe D",), {"letter": "D"}), Term("Equipe A", ("Equipe A",), {"letter": "A"})),
    "downtime_motif": (Term("electrical_failure", ("electrical_failure",)),),
    "equipment": (),
    "mold": (),
})


def context(**overrides) -> ProposalContext:
    values = dict(
        report_date=datetime.date(2026, 9, 7),
        shift_start=datetime.time(7, 0),
        shift_end=datetime.time(15, 0),
        team="Equipe D",
        default_of_id="OF1",
        default_product_id="P-VERM",
        vocabulary=VOCABULARY,
        aliases={("raw_material", "bsk1"): "MP-SSSE"},
    )
    values.update(overrides)
    return ProposalContext(**values)


def make_page(page_id: str, form_type: str | None, header: dict, blocks: dict, confidence: float = 0.9) -> PageRead:
    def cell(text: str) -> ReadCell:
        return ReadCell(text, confidence, (0.1, 0.1, 0.2, 0.2), page_id)

    return PageRead(
        page_id=page_id,
        form_type=form_type,
        rotation=0,
        header={key: cell(value) for key, value in header.items()},
        blocks={
            key: ReadBlock(key, True, tuple(ReadRow({k: cell(v) for k, v in row.items()}) for row in rows))
            for key, rows in blocks.items()
        },
        accept_score=0.5,
    )


def fabrication_page(page_id: str = "FAB") -> PageRead:
    return make_page(
        page_id,
        "fabrication",
        {"date": "Le07/09/2026", "team_hours": "D 07 H à 14H00", "line_pc": "x", "conducteur": "Conducteur Un", "agent_fabrication": "Agent Deux"},
        {
            "production": [
                {"lot": "D6249SNL", "product": "Vermicelle", "start": "07h00", "sem_origin": "BSK1", "sem_bags": "65",
                 "sem_tonnes": "3,25", "water": "28,9", "humidity": "9,83"},
                {"sem_origin": "B05I", "sem_bags": "66", "sem_tonnes": "3,3"},
            ],
            "waste_petrin": [
                {"time": "14h", "format": "Ver", "lot": "D6249", "quantity": "1,47", "cause": "Déchet Presse"},
                {"time": "14h", "format": "semoule", "lot": "D6249", "quantity": "05", "cause": "Déchet semoule"},
            ],
            "waste_finished": [{"time": "14h", "format": "Ver", "lot": "D6249", "quantity": "75,25", "cause": "A Broyer"}],
            "stops": [
                {"panne": "Démarrage de la production à 09h27mn"},
                {"panne": "Alarme silo à reprises 10h43-10h53, 12h56-12h58"},
                {"panne": "coupure sur l'EDM", "start": "12h18", "end": "12h37", "action": "Production sur GE"},
            ],
            "silo_start": [{"format": "Vermicelle", "lot": "D6249SNL", "level": "0 %", "line_state": "En Arrêt"}],
            "silo_end": [{"format": "Vermicelle", "lot": "D6249SNL", "level": "29 %", "line_state": "En Marche"}],
        },
    )


def conditionnement_page(page_id: str = "COND") -> PageRead:
    return make_page(
        page_id,
        "conditionnement",
        {"date": "07/09/26", "team_hours": "D 07H à 14H", "line_pc": "x", "machiniste": "Machiniste Trois", "aide_machiniste": "Aide Quatre"},
        {
            "silo_start": [{"format": "Vermicelles", "lot": "D6249SNL", "level": "20 %", "line_state": "En Arrêt"}],
            "silo_end": [{"format": "Vermicelles", "lot": "D6249SNL", "level": "29 %", "line_state": "En Marche"}],
            "packing": [
                {"format": "Vermicelles", "lot": "D6249SNL", "fab_date": "07-09-26", "pack_type": "(500g)",
                 "film_type": "Active", "cartons": "|", "bobine": "|", "scotch": "-"},
            ],
            "waste": [
                {"time": "07H14", "type": "Produits finis", "quantity": "02,46kg", "cause": "Nettoyage de la Machine"},
                {"type": "Films Déchet C1", "quantity": "0,35Kg", "cause": "Réglage de Machine"},
                {"type": "Films Déchet C2", "quantity": "0,23Kg"},
                {"type": "Carton Déchets", "quantity": "00", "cause": "Sale"},
                {"type": "Broyage", "quantity": "75,28Kg", "cause": "Produit non Conforme"},
            ],
        },
    )


def bobines_page(page_id: str = "BOB") -> PageRead:
    return make_page(
        page_id,
        "bobines",
        {},
        {"changes": [{"date": "07/09/26", "team": "A", "hours": "14H23H", "machine": "C1", "reel_weight": "87,00", "core_weight": "0,63"}]},
    )
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/modules/scan/domain/test_draft.py
import datetime

from modules.scan.domain.common import map_header, map_silo, map_stops
from modules.scan.domain.draft import Draft, header_path, path
from modules.scan.domain.example_pages import context, make_page
from modules.scan.domain.ocr_result import ReadCell


def _reasons(draft, at):
    return [flag["reason"] for flag in draft.flags.get(at, [])]


def test_stops_are_split_inferred_and_timed():
    draft = Draft(context())
    page = make_page("P", "fabrication", {}, {"stops": [
        {"panne": "Démarrage de la production à 09h27mn"},
        {"panne": "Alarme silo à reprises 10h43-10h53, 12h56-12h58"},
        {"panne": "coupure sur l'EDM", "start": "12h18", "end": "12h37", "action": "Production sur GE"},
    ]})
    map_stops(page, draft, "stops")
    stops = draft.sections["stops"]["stops"]
    assert [(s["started_at"], s["ended_at"]) for s in stops] == [
        ("2026-09-07T07:00", "2026-09-07T09:27"),
        ("2026-09-07T10:43", "2026-09-07T10:53"),
        ("2026-09-07T12:56", "2026-09-07T12:58"),
        ("2026-09-07T12:18", "2026-09-07T12:37"),
    ]
    assert _reasons(draft, path("stops", "stops", stops[0]["_scan_ref"], "started_at")) == ["inferred_stop"]
    assert _reasons(draft, path("stops", "stops", stops[1]["_scan_ref"], "started_at")) == ["split_stop"]
    assert (stops[3]["note"], stops[3]["corrective_action"]) == ("coupure sur l'EDM", "Production sur GE")


def test_night_shift_times_after_midnight_are_next_day():
    draft = Draft(context(shift_start=datetime.time(23, 0), shift_end=datetime.time(7, 0)))
    page = make_page("P", "fabrication", {}, {"stops": [{"panne": "panne presse", "start": "23h40", "end": "01h10"}]})
    map_stops(page, draft, "stops")
    stop = draft.sections["stops"]["stops"][0]
    assert (stop["started_at"], stop["ended_at"]) == ("2026-09-07T23:40", "2026-09-08T01:10")


def test_silo_rows_carry_side_and_phase():
    draft = Draft(context())
    page = make_page("P", "conditionnement", {}, {
        "silo_start": [{"format": "Vermicelles", "lot": "D6249SNL", "level": "20 %", "line_state": "En Arrêt"}],
        "silo_end": [{"level": "29 %", "line_state": "En Marche"}],
    })
    map_silo(page, draft, "packing")
    states = draft.sections["silo"]["states"]
    assert [(s["side"], s["phase"], s["level_percent"], s["line_state"]) for s in states] == [
        ("packing", "start", 20.0, "stopped"), ("packing", "end", 29.0, "running"),
    ]


def test_header_names_team_and_mismatch():
    draft = Draft(context(team="Equipe A"))
    page = make_page("P", "fabrication", {"team_hours": "D 07 H à 14H00", "conducteur": "Conducteur Un"}, {})
    map_header(page, draft, ("conducteur", "agent_fabrication"))
    assert draft.header == {"team": "Equipe A", "conducteur": "Conducteur Un"}
    assert _reasons(draft, header_path("team")) == ["team_mismatch"]
    assert draft.coded[header_path("conducteur")] == {"kind": "person", "read_text": "Conducteur Un", "value": "Conducteur Un"}


def test_a_new_shift_takes_the_team_named_by_its_letter():
    draft = Draft(context(team=None))
    map_header(make_page("P", "fabrication", {"team_hours": "D 07 H"}, {}), draft, ())
    assert draft.header["team"] == "Equipe D" and draft.team_letter_read == "D"


def test_lots_are_completed_and_checked_against_the_shift():
    draft = Draft(context())
    run = draft.add_row("runs", "runs", "r", {})
    waste = draft.add_row("waste_production", "waste_lines", "w", {})
    draft.lot(path("runs", "runs", "r", "lot_number"), ReadCell("D6249SNL", 0.9, None, "P"), run, "lot_number", check=True)
    draft.lot(path("waste_production", "waste_lines", "w", "lot_number"), ReadCell("D6249", 0.9, None, "P"), waste, "lot_number")
    draft.finish()
    assert waste["lot_number"] == "D6249SNL"
    assert _reasons(draft, path("waste_production", "waste_lines", "w", "lot_number")) == ["short_lot"]
    assert {"reason": "lot_date", "detail": "2026-09-06"} in draft.flags[path("runs", "runs", "r", "lot_number")]


def test_low_confidence_and_unreadable_cells_are_flagged():
    draft = Draft(context())
    assert draft.decimal("a/b/c/d", ReadCell("abc", 0.2, None, "P")) is None
    assert _reasons(draft, "a/b/c/d") == ["low_confidence", "unreadable"]
    assert draft.sources["a/b/c/d"] == [{"page_id": "P", "box": None, "text": "abc", "confidence": 0.2}]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_draft.py -q`
Expected: FAIL — `modules.scan.domain.draft` missing.

- [ ] **Step 4: Implement `draft.py`**

```python
# backend/modules/scan/domain/draft.py
"""The proposal being built from the read pages.

Rows are collected per section and part in the payload shape `save_section` takes,
each carrying `_scan_ref`. Beside them, per field path: where the value was read
(`sources`), why a person should look at it (`flags`), and, for coded values, what was
written and what it resolved to (`coded`, the base for learning aliases on apply).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Mapping

from modules.scan.domain.ocr_result import ReadCell
from modules.scan.domain.text import (
    Parsed, decode_lot, is_short_lot, parse_date, parse_decimal, parse_int, parse_lot, parse_percent, parse_time, team_letter,
)
from modules.scan.domain.vocabulary import Vocabulary, resolve

_REASON_FOR_RESOLUTION = {"contained": "partial_match", "ambiguous": "ambiguous", "none": "unresolved"}


def path(section: str, part: str, ref: str, field: str) -> str:
    return f"{section}/{part}/{ref}/{field}"


def header_path(field: str) -> str:
    return path("header", "-", "-", field)


def section_path(section: str) -> str:
    return path(section, "-", "-", "-")


@dataclass(frozen=True)
class ProposalContext:
    report_date: datetime.date
    shift_start: datetime.time
    shift_end: datetime.time
    team: str | None
    default_of_id: str | None
    default_product_id: str | None
    vocabulary: Vocabulary
    aliases: Mapping[tuple[str, str], str]

    def at(self, moment: datetime.time) -> str:
        """The timestamp of a time written on the fiche: the report date, or the next day
        for the early hours of a shift that runs past midnight."""
        day = self.report_date
        if self.shift_end <= self.shift_start and moment < self.shift_start:
            day += datetime.timedelta(days=1)
        return datetime.datetime.combine(day, moment).isoformat(timespec="minutes")


class Draft:
    def __init__(self, ctx: ProposalContext) -> None:
        self.ctx = ctx
        self.accept_score = 0.5
        self.header: dict[str, Any] = {}
        self.sections: dict[str, dict[str, Any]] = {}
        self.flags: dict[str, list[dict]] = {}
        self.sources: dict[str, list[dict]] = {}
        self.coded: dict[str, dict] = {}
        self.set_aside: dict[str, list[dict]] = {}
        self.team_letter_read: str | None = None
        # Packing-side waste lines that came from the fabrication sheet's "Produit fini" block.
        self.fabrication_losses: list[dict] = []
        self._lots: list[tuple[dict, str, str, bool]] = []

    # ---- structure ---------------------------------------------------------

    def rows(self, section: str, part: str) -> list[dict]:
        return self.sections.setdefault(section, {}).setdefault(part, [])

    def add_row(self, section: str, part: str, ref: str, row: dict) -> dict:
        row["_scan_ref"] = ref
        self.rows(section, part).append(row)
        return row

    def single(self, section: str, part: str) -> dict:
        return self.sections.setdefault(section, {}).setdefault(part, {})

    # ---- flags and sources -------------------------------------------------

    def flag(self, at: str, reason: str, detail: str | None = None) -> None:
        entry = {"reason": reason, "detail": detail}
        bucket = self.flags.setdefault(at, [])
        if entry not in bucket:
            bucket.append(entry)

    def see(self, at: str, cell: ReadCell) -> None:
        if not cell.text.strip():
            return
        self.sources.setdefault(at, []).append(
            {"page_id": cell.page_id, "box": list(cell.box) if cell.box else None, "text": cell.text, "confidence": round(cell.confidence, 3)}
        )
        if cell.confidence < self.accept_score:
            self.flag(at, "low_confidence")
        if cell.conflict is not None:
            self.flag(at, "conflicting", cell.conflict)

    def _read(self, at: str, cell: ReadCell, parsed: Parsed) -> Any:
        self.see(at, cell)
        if cell.text.strip() and parsed.value is None:
            self.flag(at, "unreadable")
        elif parsed.value is not None and not parsed.sure:
            self.flag(at, "lookalike")
        return parsed.value

    def text(self, at: str, cell: ReadCell) -> str | None:
        self.see(at, cell)
        return cell.text.strip() or None

    def decimal(self, at: str, cell: ReadCell) -> float | None:
        return self._read(at, cell, parse_decimal(cell.text))

    def percent(self, at: str, cell: ReadCell) -> float | None:
        return self._read(at, cell, parse_percent(cell.text))

    def integer(self, at: str, cell: ReadCell) -> int | None:
        return self._read(at, cell, parse_int(cell.text))

    def time(self, at: str, cell: ReadCell) -> datetime.time | None:
        return self._read(at, cell, parse_time(cell.text))

    def date(self, at: str, cell: ReadCell) -> datetime.date | None:
        return self._read(at, cell, parse_date(cell.text))

    def code(self, at: str, kind: str, cell: ReadCell, *, prefer: str | None = None, quiet: bool = False) -> str | None:
        """A written code turned into a system value; `quiet` for optional fields nobody must check."""
        self.see(at, cell)
        written = cell.text.strip()
        if not written:
            return None
        found = resolve(self.ctx.vocabulary, self.ctx.aliases, kind, written, prefer=prefer)
        self.coded[at] = {"kind": kind, "read_text": written, "value": found.value}
        reason = _REASON_FOR_RESOLUTION.get(found.how)
        if reason and not quiet:
            self.flag(at, reason)
        return found.value

    def lot(self, at: str, cell: ReadCell, row: dict, field: str, *, check: bool = False) -> None:
        """Store a written lot on the row; `check` compares it with the shift once all pages are read."""
        self.see(at, cell)
        parsed = parse_lot(cell.text)
        row[field] = parsed.value
        if parsed.value is None:
            return
        if not parsed.sure:
            self.flag(at, "lot_format")
        self._lots.append((row, field, at, check))

    # ---- after every page --------------------------------------------------

    def finish(self) -> None:
        self._complete_short_lots()
        self._check_lots()
        self._set_aside_losses_counted_twice()

    def _complete_short_lots(self) -> None:
        full = {row[field] for row, field, _, _ in self._lots if row.get(field) and not is_short_lot(row[field])}
        for row, field, at, _ in self._lots:
            if is_short_lot(row.get(field)):
                matches = sorted(lot for lot in full if lot.startswith(row[field]))
                if len(matches) == 1:
                    row[field] = matches[0]
                    self.flag(at, "short_lot")

    def _check_lots(self) -> None:
        expected_letter = team_letter(self.ctx.team) or self.team_letter_read
        for row, field, at, check in self._lots:
            if not check or not row.get(field) or is_short_lot(row[field]):
                continue
            decoded = decode_lot(row[field], self.ctx.report_date)
            if decoded is None:
                continue
            letter, day = decoded
            if day != self.ctx.report_date:
                self.flag(at, "lot_date", day.isoformat())
            if expected_letter and letter != expected_letter:
                self.flag(at, "lot_team", letter)

    def _set_aside_losses_counted_twice(self) -> None:
        """One place per loss: finished product lost is filed on the packing side.

        When the conditionnement sheet of the same session lists finished product lost
        and packed the same lot, the fabrication sheet's "Produit fini" line is most
        likely the same kilos; it is put aside (the user can add it back), not counted twice.
        """
        lines = self.sections.get("waste_packing", {}).get("waste_lines", [])
        packed_lots = {row.get("lot_number") for row in self.sections.get("packing", {}).get("rows", []) if row.get("lot_number")}
        packing_product_lines = [
            row for row in lines if row.get("category") == "product" and all(row is not loss for loss in self.fabrication_losses)
        ]
        if not packing_product_lines:
            return
        for loss in self.fabrication_losses:
            if loss.get("lot_number") in packed_lots:
                lines.remove(loss)
                self.set_aside.setdefault("waste_packing", []).append({"part": "waste_lines", "row": loss, "reason": "same_loss"})

    def to_json(self, pages: dict) -> dict:
        return {
            "header": self.header,
            "sections": self.sections,
            "flags": self.flags,
            "sources": self.sources,
            "coded": self.coded,
            "set_aside": self.set_aside,
            "pages": pages,
        }
```

- [ ] **Step 5: Implement `common.py`**

```python
# backend/modules/scan/domain/common.py
"""What both fiches share: the header (team and names), the stops table and the silo."""
from __future__ import annotations

from functools import partial

from modules.scan.domain.draft import Draft, header_path, path, section_path
from modules.scan.domain.ocr_result import PageRead
from modules.scan.domain.text import Parsed, find_intervals, find_times, normalize, team_and_hours, team_letter


def map_header(page: PageRead, draft: Draft, person_fields: tuple[str, ...]) -> None:
    cell = page.head("team_hours")
    letter, _ = team_and_hours(cell.text)
    if letter:
        at = header_path("team")
        draft.see(at, cell)
        draft.team_letter_read = draft.team_letter_read or letter
        shift_letter = team_letter(draft.ctx.team)
        if shift_letter and shift_letter != letter:
            draft.flag(at, "team_mismatch", letter)
        if "team" not in draft.header:
            by_letter = next((t.value for t in draft.ctx.vocabulary.of("team") if t.attrs.get("letter") == letter), None)
            draft.header["team"] = draft.ctx.team or by_letter
    for field in person_fields:
        cell = page.head(field)
        written = cell.text.strip()
        if not written or field in draft.header:
            continue
        at = header_path(field)
        draft.see(at, cell)
        learned = draft.ctx.aliases.get(("person", normalize(written)))
        draft.coded[at] = {"kind": "person", "read_text": written, "value": learned or written}
        draft.header[field] = learned or written


def map_stops(page: PageRead, draft: Draft, block_key: str) -> None:
    """A paper stop line becomes one stop per interval written on it.

    Times are read from the start/end cells; when those hold no single time, from the
    whole line -- teams write "Alarme silo à reprises 10h43-10h53, 12h56-12h58" across
    the table. A line naming only a start ("Démarrage de la production à 09h27") is the
    time lost from the shift's start to it.
    """
    block = page.block(block_key)
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("stops"), "rows_disagree")
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        panne, start, end, action = (row.cell(key) for key in ("panne", "start", "end", "action"))
        starts, ends = find_times(start.text), find_times(end.text)
        how = None
        if len(starts) == 1:
            spans = [(starts[0], ends[0] if len(ends) == 1 else None, start, end)]
        else:
            pairs = find_intervals(" ".join((start.text, end.text, panne.text)))
            lone = find_times(panne.text)
            if pairs:
                spans = [(a, b, panne, panne) for a, b in pairs]
                how = "split_stop" if len(pairs) > 1 else None
            elif len(lone) == 1 and "demarrage" in normalize(panne.text):
                spans = [(Parsed(draft.ctx.shift_start), lone[0], panne, panne)]
                how = "inferred_stop"
            elif len(lone) == 1:
                spans = [(lone[0], None, panne, panne)]
            else:
                spans = [(None, None, start, end)]
        for number, (begin, finish, begin_cell, finish_cell) in enumerate(spans):
            ref = f"{page.page_id}:{block_key}:{index}:{number}"
            at = partial(path, "stops", "stops", ref)
            stop = draft.add_row("stops", "stops", ref, {"started_at": None, "ended_at": None, "motif": None, "note": None, "corrective_action": None})
            draft.see(at("started_at"), begin_cell)
            draft.see(at("ended_at"), finish_cell)
            if begin is not None:
                stop["started_at"] = draft.ctx.at(begin.value)
                if not begin.sure:
                    draft.flag(at("started_at"), "lookalike")
            elif begin_cell.text.strip():
                draft.flag(at("started_at"), "unreadable")
            if finish is not None:
                stop["ended_at"] = draft.ctx.at(finish.value)
                if not finish.sure:
                    draft.flag(at("ended_at"), "lookalike")
            if how:
                draft.flag(at("started_at"), how)
            stop["note"] = draft.text(at("note"), panne)
            stop["corrective_action"] = draft.text(at("corrective_action"), action)
            stop["motif"] = draft.code(at("motif"), "downtime_motif", panne, quiet=True)


def map_silo(page: PageRead, draft: Draft, side: str) -> None:
    for phase, key in (("start", "silo_start"), ("end", "silo_end")):
        block = page.block(key)
        row = next((r for r in block.rows if not r.is_blank()), None) if block else None
        if row is None:
            continue
        ref = f"{page.page_id}:{key}:0"
        at = partial(path, "silo", "states", ref)
        state = draft.add_row("silo", "states", ref, {"side": side, "phase": phase, "format": None, "lot_number": None, "level_percent": None, "line_state": None})
        state["format"] = draft.text(at("format"), row.cell("format"))
        draft.lot(at("lot_number"), row.cell("lot"), state, "lot_number")
        state["level_percent"] = draft.percent(at("level_percent"), row.cell("level"))
        state["line_state"] = draft.code(at("line_state"), "line_state", row.cell("line_state"))
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_draft.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/scan/domain/draft.py backend/modules/scan/domain/common.py backend/modules/scan/domain/example_pages.py backend/modules/scan/domain/test_draft.py
git commit -m "feat(scan): proposal draft with sources and flags; header, stops and silo mapping"
```

---

### Task 6: The two fiches' own blocks

**Files:**
- Create: `backend/modules/scan/domain/fabrication.py`, `backend/modules/scan/domain/conditionnement.py`
- Test: `backend/modules/scan/domain/test_fiches.py`

**Interfaces:**
- Consumes: Task 5 (`Draft`, `path`, `section_path`, `map_header`, `map_stops`, `map_silo`, example pages), Task 2 (`first_number`, `minutes_between`, `parse_decimal`), Task 3 (`resolve`).
- Produces: `map_fabrication(page: PageRead, draft: Draft) -> None`, `map_conditionnement(page: PageRead, draft: Draft) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/domain/test_fiches.py
from modules.scan.domain.conditionnement import map_conditionnement
from modules.scan.domain.draft import Draft, path
from modules.scan.domain.example_pages import conditionnement_page, context, fabrication_page, make_page
from modules.scan.domain.fabrication import map_fabrication


def _reasons(draft, at):
    return [flag["reason"] for flag in draft.flags.get(at, [])]


def _fabrication():
    draft = Draft(context())
    map_fabrication(fabrication_page(), draft)
    return draft


def _conditionnement(page=None):
    draft = Draft(context())
    map_conditionnement(page or conditionnement_page(), draft)
    return draft


def test_fabrication_run_and_versements():
    draft = _fabrication()
    runs = draft.sections["runs"]
    [run] = runs["runs"]
    assert (run["of_id"], run["lot_number"], run["start_time"], run["water_percentage"], run["humidity_percentage"]) == (
        "OF1", "D6249SNL", "07:00", 28.9, 9.83,
    )
    assert [(v["product_id"], v["quantity"]) for v in runs["versements"]] == [("MP-SSSE", 3.25), (None, 3.3)]
    assert _reasons(draft, path("runs", "versements", runs["versements"][1]["_scan_ref"], "product_id")) == ["unresolved"]
    assert path("runs", "runs", run["_scan_ref"], "of_id") not in draft.flags  # "Vermicelle" is the OF's product


def test_fabrication_run_minutes_from_its_hours():
    draft = Draft(context())
    map_fabrication(make_page("P", "fabrication", {}, {"production": [{"lot": "D6250SNL", "start": "07h00", "end": "14h00"}]}), draft)
    assert draft.sections["runs"]["runs"][0]["production_minutes"] == 420


def test_fabrication_waste_goes_to_the_right_side():
    draft = _fabrication()
    petrin = draft.sections["waste_production"]["waste_lines"]
    assert [(w["category"], w["quantity"], w["occurred_at"]) for w in petrin] == [
        ("press", 1.47, "2026-09-07T14:00"), (None, 5.0, "2026-09-07T14:00"),
    ]
    [finished] = draft.sections["waste_packing"]["waste_lines"]
    assert (finished["category"], finished["quantity"]) == ("product", 75.25)
    assert draft.fabrication_losses == [finished]


def test_fabrication_header_stops_and_silo():
    draft = _fabrication()
    assert draft.header == {"team": "Equipe D", "conducteur": "Conducteur Un", "agent_fabrication": "Agent Deux"}
    assert len(draft.sections["stops"]["stops"]) == 4
    assert [(s["side"], s["phase"]) for s in draft.sections["silo"]["states"]] == [("production", "start"), ("production", "end")]
    assert "staffing" not in draft.sections


def test_fabrication_staffing_and_mold_washes():
    draft = Draft(context())
    page = make_page("P", "fabrication", {}, {
        "staffing": [{"control_room": "1", "petrin": "2", "semoule": "1", "broyage": ""}],
        "mold_washes": [{"mold": "M12", "time": "10h", "state": "propre"}],
    })
    map_fabrication(page, draft)
    assert draft.sections["staffing"]["staffing"] == {"control_room": 1, "petrin": 2, "semoule": 1, "broyage": None}
    [wash] = draft.sections["waste_production"]["mold_washes"]
    assert (wash["mold_id"], wash["washed_at"], wash["state"]) == (None, "2026-09-07T10:00", "propre")


def test_conditionnement_packing_row():
    draft = _conditionnement()
    [row] = draft.sections["packing"]["rows"]
    assert (row["product_id"], row["of_id"], row["lot_number"], row["film_product_id"]) == ("P-VERM", "OF1", "D6249SNL", "FILM-ACT")
    assert (row["carton_quantity"], row["tape_quantity"], row["scotch_quantity"], row["ruban_quantity"]) == (1.0, 1.0, None, None)
    at = lambda field: path("packing", "rows", row["_scan_ref"], field)  # noqa: E731
    assert _reasons(draft, at("carton_quantity")) == ["lookalike"]
    assert _reasons(draft, at("scotch_quantity")) == ["unreadable"]
    assert _reasons(draft, at("film_product_id")) == ["partial_match"]
    assert at("product_id") not in draft.flags


def test_packing_format_that_is_not_the_products_weight():
    page = make_page("P", "conditionnement", {}, {"packing": [{"format": "Vermicelles", "lot": "D6250SNL", "pack_type": "(250g)"}]})
    draft = _conditionnement(page)
    row = draft.sections["packing"]["rows"][0]
    assert draft.flags[path("packing", "rows", row["_scan_ref"], "product_id")] == [{"reason": "format_mismatch", "detail": "250 g"}]


def test_conditionnement_waste_skips_nothing_written_as_00():
    lines = _conditionnement().sections["waste_packing"]["waste_lines"]
    assert [(line["category"], line["quantity"]) for line in lines] == [("product", 2.46), (None, 0.35), (None, 0.23), (None, 75.28)]
    assert lines[0]["product_id"] == "P-VERM" and lines[1]["product_id"] is None


def test_packet_checks():
    page = make_page("P", "conditionnement", {}, {"packet_checks": [
        {"time": "08h00", "film": "Bon", "weight": "502", "long_weld": "B", "vert_weld": "NB", "date_print": "OK", "observation": "RAS"},
    ]})
    [check] = _conditionnement(page).sections["packet_checks"]["checks"]
    assert {k: v for k, v in check.items() if k != "_scan_ref"} == {
        "checked_at": "2026-09-07T08:00", "film_state": "good", "packet_weight_grams": 502.0,
        "long_weld": "good", "vertical_weld": "not_good", "date_print": "good", "note": "RAS",
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_fiches.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement `fabrication.py`**

```python
# backend/modules/scan/domain/fabrication.py
"""The Fiche fabrication par équipe, block by block, into the shift report's sections.

Production rows: a row naming a lot, product or start begins a run; the semoule and
broyage columns of every row are the shift's versements (the report records them once
per shift). "Pâtes non conformes -- Produit fini" is finished product lost, which the
report files on the packing side ("one place per loss").
"""
from __future__ import annotations

from functools import partial

from modules.scan.domain.common import map_header, map_silo, map_stops
from modules.scan.domain.draft import Draft, path, section_path
from modules.scan.domain.ocr_result import PageRead, ReadRow
from modules.scan.domain.text import minutes_between
from modules.scan.domain.vocabulary import resolve

PERSON_FIELDS = ("conducteur", "agent_fabrication")
_RUN_STARTERS = ("lot", "product", "start")


def map_fabrication(page: PageRead, draft: Draft) -> None:
    draft.accept_score = page.accept_score
    map_header(page, draft, PERSON_FIELDS)
    _production(page, draft)
    _waste_petrin(page, draft)
    _waste_finished(page, draft)
    _mold_washes(page, draft)
    _staffing(page, draft)
    map_stops(page, draft, "stops")
    map_silo(page, draft, "production")


def _written(row: ReadRow, *keys: str) -> bool:
    return any(row.cell(key).text.strip() for key in keys)


def _new_run(page: PageRead, draft: Draft, row: ReadRow, ref: str) -> dict:
    at = partial(path, "runs", "runs", ref)
    run = draft.add_row("runs", "runs", ref, {
        "of_id": draft.ctx.default_of_id, "lot_number": None, "start_time": None, "end_time": None,
        "production_minutes": 0, "water_percentage": None, "humidity_percentage": None,
    })
    draft.lot(at("lot_number"), row.cell("lot"), run, "lot_number", check=True)
    start = draft.time(at("start_time"), row.cell("start"))
    end = draft.time(at("end_time"), row.cell("end"))
    run["start_time"] = start.strftime("%H:%M") if start else None
    run["end_time"] = end.strftime("%H:%M") if end else None
    if start and end:
        run["production_minutes"] = minutes_between(start, end)
    product = row.cell("product")
    if product.text.strip():
        # The run's product is its OF's; a product written that is surely another one is worth a look.
        draft.see(at("of_id"), product)
        found = resolve(draft.ctx.vocabulary, draft.ctx.aliases, "finished_product", product.text, prefer=draft.ctx.default_product_id)
        if found.how in ("alias", "exact") and draft.ctx.default_product_id and found.value != draft.ctx.default_product_id:
            draft.flag(at("of_id"), "of_product")
    return run


def _production(page: PageRead, draft: Draft) -> None:
    block = page.block("production")
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("runs"), "rows_disagree")
    run = None
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:production:{index}"
        if run is None or _written(row, *_RUN_STARTERS):
            run = _new_run(page, draft, row, ref)
        run_at = partial(path, "runs", "runs", run["_scan_ref"])
        for field, key in (("water_percentage", "water"), ("humidity_percentage", "humidity")):
            if row.cell(key).text.strip():
                run[field] = draft.percent(run_at(field), row.cell(key))
        if _written(row, "sem_origin", "sem_bags", "sem_tonnes"):
            sem_ref = f"{ref}:sem"
            at = partial(path, "runs", "versements", sem_ref)
            versement = draft.add_row("runs", "versements", sem_ref, {"product_id": None, "quantity": None})
            versement["product_id"] = draft.code(at("product_id"), "raw_material", row.cell("sem_origin"))
            versement["quantity"] = draft.decimal(at("quantity"), row.cell("sem_tonnes"))
        if _written(row, "broy_kg", "broy_bags", "broy_lot"):
            broy_ref = f"{ref}:broy"
            at = partial(path, "runs", "rebroyat_versements", broy_ref)
            kilos = draft.decimal(at("quantity"), row.cell("broy_kg"))
            regrind = draft.ctx.vocabulary.of("regrind_item")
            draft.add_row("runs", "rebroyat_versements", broy_ref, {
                # The fiche names no item; the plant's only rebroyat item when there is exactly one.
                "product_id": regrind[0].value if len(regrind) == 1 else None,
                "quantity": round(kilos / 1000, 6) if kilos is not None else None,
            })


def _waste_line(page: PageRead, draft: Draft, row: ReadRow, section: str, ref: str, kind: str | None) -> dict:
    at = partial(path, section, "waste_lines", ref)
    line = draft.add_row(section, "waste_lines", ref, {"category": None, "quantity": None, "lot_number": None, "occurred_at": None, "note": None})
    cause = row.cell("cause")
    if kind is not None:
        line["category"] = draft.code(at("category"), kind, cause if cause.text.strip() else row.cell("format"))
    line["quantity"] = draft.decimal(at("quantity"), row.cell("quantity"))
    draft.lot(at("lot_number"), row.cell("lot"), line, "lot_number")
    moment = draft.time(at("occurred_at"), row.cell("time"))
    line["occurred_at"] = draft.ctx.at(moment) if moment else None
    line["note"] = draft.text(at("note"), cause)
    return line


def _waste_petrin(page: PageRead, draft: Draft) -> None:
    block = page.block("waste_petrin")
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("waste_production"), "rows_disagree")
    for index, row in enumerate(block.rows):
        if not row.is_blank():
            _waste_line(page, draft, row, "waste_production", f"{page.page_id}:waste_petrin:{index}", "waste_production")


def _waste_finished(page: PageRead, draft: Draft) -> None:
    block = page.block("waste_finished")
    if block is None:
        return
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:waste_finished:{index}"
        line = _waste_line(page, draft, row, "waste_packing", ref, None)
        line["category"] = "product"
        line["product_id"] = draft.code(
            path("waste_packing", "waste_lines", ref, "product_id"), "finished_product", row.cell("format"),
            prefer=draft.ctx.default_product_id,
        )
        draft.fabrication_losses.append(line)


def _mold_washes(page: PageRead, draft: Draft) -> None:
    block = page.block("mold_washes")
    if block is None:
        return
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:mold_washes:{index}"
        at = partial(path, "waste_production", "mold_washes", ref)
        wash = draft.add_row("waste_production", "mold_washes", ref, {"mold_id": None, "washed_at": None, "state": None})
        wash["mold_id"] = draft.code(at("mold_id"), "mold", row.cell("mold"))
        moment = draft.time(at("washed_at"), row.cell("time"))
        wash["washed_at"] = draft.ctx.at(moment) if moment else None
        wash["state"] = draft.text(at("state"), row.cell("state"))


def _staffing(page: PageRead, draft: Draft) -> None:
    block = page.block("staffing")
    row = next((r for r in block.rows if not r.is_blank()), None) if block else None
    if row is None:
        return
    staffing = draft.single("staffing", "staffing")
    for key in ("control_room", "petrin", "semoule", "broyage"):
        staffing[key] = draft.integer(path("staffing", "staffing", "-", key), row.cell(key))
```

- [ ] **Step 4: Implement `conditionnement.py`**

```python
# backend/modules/scan/domain/conditionnement.py
"""The Fiche conditionnement par équipe, block by block, into the shift report's sections."""
from __future__ import annotations

from functools import partial

from modules.scan.domain.common import map_header, map_silo, map_stops
from modules.scan.domain.draft import Draft, path, section_path
from modules.scan.domain.ocr_result import PageRead
from modules.scan.domain.text import first_number, parse_decimal

PERSON_FIELDS = ("machiniste", "aide_machiniste")
_QUANTITIES = (("carton_quantity", "cartons"), ("tape_quantity", "bobine"), ("scotch_quantity", "scotch"), ("ruban_quantity", "ruban"))
_CHECKS = (("film_state", "film"), ("long_weld", "long_weld"), ("vertical_weld", "vert_weld"), ("date_print", "date_print"))


def map_conditionnement(page: PageRead, draft: Draft) -> None:
    draft.accept_score = page.accept_score
    map_header(page, draft, PERSON_FIELDS)
    map_silo(page, draft, "packing")
    _packing(page, draft)
    _packet_checks(page, draft)
    _waste(page, draft)
    map_stops(page, draft, "stops")


def _packing(page: PageRead, draft: Draft) -> None:
    block = page.block("packing")
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("packing"), "rows_disagree")
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:packing:{index}"
        at = partial(path, "packing", "rows", ref)
        line = draft.add_row("packing", "rows", ref, {
            "product_id": None, "of_id": draft.ctx.default_of_id, "lot_number": None, "film_product_id": None,
            "carton_quantity": None, "tape_quantity": None, "scotch_quantity": None, "ruban_quantity": None,
        })
        line["product_id"] = draft.code(at("product_id"), "finished_product", row.cell("format"), prefer=draft.ctx.default_product_id)
        draft.lot(at("lot_number"), row.cell("lot"), line, "lot_number", check=True)
        made = draft.date(at("lot_number"), row.cell("fab_date"))
        if made is not None and made != draft.ctx.report_date:
            draft.flag(at("lot_number"), "fab_date", made.isoformat())
        grams = first_number(row.cell("pack_type").text)
        weight = draft.ctx.vocabulary.attr("finished_product", line["product_id"], "net_weight_grams") if line["product_id"] else None
        if grams is not None and weight and float(weight) != grams:
            draft.flag(at("product_id"), "format_mismatch", f"{grams:g} g")
        line["film_product_id"] = draft.code(at("film_product_id"), "film_item", row.cell("film_type"))
        for field, key in _QUANTITIES:
            line[field] = draft.decimal(at(field), row.cell(key))


def _packet_checks(page: PageRead, draft: Draft) -> None:
    block = page.block("packet_checks")
    if block is None:
        return
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:packet_checks:{index}"
        at = partial(path, "packet_checks", "checks", ref)
        check = draft.add_row("packet_checks", "checks", ref, {})
        moment = draft.time(at("checked_at"), row.cell("time"))
        check["checked_at"] = draft.ctx.at(moment) if moment else None
        for field, key in _CHECKS:
            check[field] = draft.code(at(field), "check_state", row.cell(key))
        check["packet_weight_grams"] = draft.decimal(at("packet_weight_grams"), row.cell("weight"))
        check["note"] = draft.text(at("note"), row.cell("observation"))


def _waste(page: PageRead, draft: Draft) -> None:
    block = page.block("waste")
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("waste_packing"), "rows_disagree")
    for index, row in enumerate(block.rows):
        if row.is_blank() or parse_decimal(row.cell("quantity").text).value == 0:
            continue  # "00" on the fiche: nothing was lost
        ref = f"{page.page_id}:waste:{index}"
        at = partial(path, "waste_packing", "waste_lines", ref)
        line = draft.add_row("waste_packing", "waste_lines", ref, {"category": None, "quantity": None, "occurred_at": None, "note": None, "product_id": None})
        kind_cell = row.cell("type") if row.cell("type").text.strip() else row.cell("cause")
        line["category"] = draft.code(at("category"), "waste_packing", kind_cell)
        line["quantity"] = draft.decimal(at("quantity"), row.cell("quantity"))
        moment = draft.time(at("occurred_at"), row.cell("time"))
        line["occurred_at"] = draft.ctx.at(moment) if moment else None
        line["note"] = draft.text(at("note"), row.cell("cause"))
        if line["category"] == "product":
            line["product_id"] = draft.ctx.default_product_id
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan/domain -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/scan/domain/fabrication.py backend/modules/scan/domain/conditionnement.py backend/modules/scan/domain/test_fiches.py
git commit -m "feat(scan): map the fabrication and conditionnement fiches to shift sections"
```

---

### Task 7: Building the proposal, and the review helpers apply relies on

**Files:**
- Create: `backend/modules/scan/domain/proposal.py`, `backend/modules/scan/domain/review.py`
- Test: `backend/modules/scan/domain/test_proposal.py`

**Interfaces:**
- Consumes: Tasks 4–6.
- Produces:
  - `IMPORTABLE_FORMS = ("fabrication", "conditionnement")`; `build_proposal(pages: Sequence[PageRead], ctx: ProposalContext, selection: Selection, include_pages: Collection[str]) -> dict` (the Proposal JSON of the contracts section).
  - `review.APPLY_ORDER = ("runs", "waste_production", "stops", "silo", "staffing", "packing", "packet_checks", "waste_packing")`, `fingerprint(payload) -> str`, `count_rows(payload) -> int`, `final_values(sections, header) -> dict[str, Any]`, `strip_private(payload) -> dict`, `stale_sections(requested, current, shown) -> list[str]`, `outcomes(proposal, finals) -> list[dict]`, `aliases_to_learn(coded, finals) -> list[tuple[str, str, str]]`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/domain/test_proposal.py
import datetime
import json

from modules.scan.domain.attribution import Selection
from modules.scan.domain.example_pages import bobines_page, conditionnement_page, context, fabrication_page, make_page
from modules.scan.domain.proposal import build_proposal
from modules.scan.domain.review import (
    aliases_to_learn, count_rows, final_values, fingerprint, outcomes, stale_sections, strip_private,
)

SELECTION = Selection(report_date=datetime.date(2026, 9, 7), shift_start=datetime.time(7, 0), line_label="PC")


def _build(pages, include=()):
    return build_proposal(pages, context(), SELECTION, include_pages=include)


def test_the_example_upload():
    proposal = _build([fabrication_page(), conditionnement_page(), bobines_page()])
    pages = proposal["pages"]
    assert pages["FAB"]["included"] and pages["COND"]["included"]
    assert (pages["BOB"]["verdict"], pages["BOB"]["importable"], pages["BOB"]["included"]) == ("other_shift", False, False)
    assert set(proposal["sections"]) == {"runs", "waste_production", "stops", "silo", "packing", "waste_packing"}
    assert len(proposal["sections"]["silo"]["states"]) == 4
    [aside] = proposal["set_aside"]["waste_packing"]
    assert aside["reason"] == "same_loss" and aside["row"]["quantity"] == 75.25
    assert [line["quantity"] for line in proposal["sections"]["waste_packing"]["waste_lines"]] == [2.46, 0.35, 0.23, 75.28]
    assert proposal["header"] == {
        "team": "Equipe D", "conducteur": "Conducteur Un", "agent_fabrication": "Agent Deux",
        "machiniste": "Machiniste Trois", "aide_machiniste": "Aide Quatre",
    }
    json.dumps(proposal)  # everything is JSON-safe


def test_an_other_shift_page_is_used_only_when_included():
    page = make_page("LATE", "fabrication", {"date": "07/09/26", "team_hours": "A 15H", "line_pc": "x"}, {"stops": [{"panne": "x", "start": "16h00"}]})
    assert "stops" not in _build([page])["sections"]
    assert "stops" in _build([page], include={"LATE"})["sections"]


def test_a_retake_does_not_duplicate_silo_rows():
    proposal = _build([fabrication_page("A"), fabrication_page("B")])
    assert len(proposal["sections"]["silo"]["states"]) == 2
    assert len(proposal["sections"]["stops"]["stops"]) == 4


def test_without_the_conditionnement_sheet_the_finished_loss_stays():
    proposal = _build([fabrication_page()])
    assert proposal["set_aside"] == {}
    assert proposal["sections"]["waste_packing"]["waste_lines"][0]["quantity"] == 75.25


def test_final_values_and_strip_private():
    sections = {"runs": {"runs": [{"_scan_ref": "R1", "_key": "k", "of_id": "OF1", "lot_number": "L"}]}, "staffing": {"staffing": {"petrin": 2}}}
    assert final_values(sections, {"team": "Equipe D"}) == {
        "header/-/-/team": "Equipe D", "runs/runs/R1/of_id": "OF1", "runs/runs/R1/lot_number": "L", "staffing/staffing/-/petrin": 2,
    }
    assert strip_private(sections["runs"]) == {"runs": [{"of_id": "OF1", "lot_number": "L"}]}


def test_fingerprint_ignores_key_order_and_count_rows():
    assert fingerprint({"runs": [{"a": 1, "b": 2}], "energy": None}) == fingerprint({"energy": None, "runs": [{"b": 2, "a": 1}]})
    assert count_rows({"runs": [{}, {}], "versements": [], "staffing": {"petrin": 1}, "energy": None}) == 3


def test_stale_sections():
    current = {"runs": {"fingerprint": "f1", "rows": 2}, "stops": {"fingerprint": "f2", "rows": 0}}
    assert stale_sections(["runs"], current, {"runs": "f1"}) == []
    assert stale_sections(["runs"], current, {"runs": "old"}) == ["runs"]
    assert stale_sections(["runs", "stops"], current, {}) == ["runs"]  # nothing shown, rows appeared since
    assert stale_sections(["runs"], None, {}) == []


def test_outcomes_compare_proposed_and_final():
    proposal = {
        "header": {}, "sections": {"runs": {"runs": [{"_scan_ref": "R1", "lot_number": "D6249SNL", "water_percentage": 28.9}]}},
        "sources": {
            "runs/runs/R1/lot_number": [{"page_id": "P", "box": None, "text": "D6249SNL", "confidence": 0.8}],
            "runs/runs/R1/water_percentage": [{"page_id": "P", "box": None, "text": "28,9", "confidence": 0.7}],
        },
        "flags": {"runs/runs/R1/lot_number": [{"reason": "lot_date", "detail": "2026-09-06"}]},
    }
    rows = outcomes(proposal, {"runs/runs/R1/lot_number": "D6250SNL", "runs/runs/R1/water_percentage": "28.9"})
    assert rows == [
        {"field_path": "runs/runs/R1/lot_number", "page_id": "P", "read_text": "D6249SNL", "confidence": 0.8,
         "proposed_value": "D6249SNL", "final_value": "D6250SNL", "flag": "lot_date", "changed": True},
        {"field_path": "runs/runs/R1/water_percentage", "page_id": "P", "read_text": "28,9", "confidence": 0.7,
         "proposed_value": "28.9", "final_value": "28.9", "flag": None, "changed": False},
    ]


def test_aliases_to_learn():
    coded = {
        "runs/versements/V1/product_id": {"kind": "raw_material", "read_text": "B05I", "value": None},
        "header/-/-/conducteur": {"kind": "person", "read_text": "Raclne", "value": "Raclne"},
        "runs/versements/V0/product_id": {"kind": "raw_material", "read_text": "BSK1", "value": "MP-1"},
    }
    finals = {"runs/versements/V1/product_id": "MP-2", "header/-/-/conducteur": "Racine", "runs/versements/V0/product_id": "MP-1"}
    assert aliases_to_learn(coded, finals) == [("raw_material", "B05I", "MP-2"), ("person", "Raclne", "Racine")]
    assert aliases_to_learn(coded, {"runs/versements/V1/product_id": None}) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/domain/test_proposal.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement `proposal.py`**

```python
# backend/modules/scan/domain/proposal.py
"""Every read page of a session into one proposal for the review screen.

Each page is first matched to the selected shift; pages of another shift stay out
unless the user includes them, and the bobines sheet is recognised but has no section
to fill yet (phase 2). The included pages of each fiche are merged into one, mapped,
and the draft is finished (lots completed and checked, a loss counted twice put aside).
"""
from __future__ import annotations

from typing import Callable, Collection, Sequence

from modules.scan.domain.attribution import Selection, attribute, header_of_page
from modules.scan.domain.conditionnement import map_conditionnement
from modules.scan.domain.draft import Draft, ProposalContext
from modules.scan.domain.fabrication import map_fabrication
from modules.scan.domain.merge import merge_pages
from modules.scan.domain.ocr_result import PageRead

_MAPPERS: dict[str, Callable[[PageRead, Draft], None]] = {
    "fabrication": map_fabrication,
    "conditionnement": map_conditionnement,
}
IMPORTABLE_FORMS = tuple(_MAPPERS)


def build_proposal(
    pages: Sequence[PageRead], ctx: ProposalContext, selection: Selection, include_pages: Collection[str]
) -> dict:
    summaries: dict[str, dict] = {}
    groups: dict[str, list[PageRead]] = {form: [] for form in _MAPPERS}
    for page in pages:
        attribution = attribute(header_of_page(page), selection)
        importable = page.form_type in _MAPPERS
        included = importable and (attribution.verdict != "other_shift" or page.page_id in include_pages)
        summaries[page.page_id] = {
            "form_type": page.form_type,
            "verdict": attribution.verdict,
            "reasons": list(attribution.reasons),
            "read": attribution.read,
            "importable": importable,
            "included": included,
        }
        if included:
            groups[page.form_type].append(page)
    draft = Draft(ctx)
    for form, mapper in _MAPPERS.items():
        if groups[form]:
            mapper(merge_pages(groups[form]), draft)
    draft.finish()
    return draft.to_json(summaries)
```

- [ ] **Step 4: Implement `review.py`**

```python
# backend/modules/scan/domain/review.py
"""What applying a reviewed scan needs: section fingerprints (to refuse a stale review),
values by field path (to learn aliases and record outcomes), and payload cleaning."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Collection, Mapping

from modules.scan.domain.draft import path

# The paper fiches' order, energy excepted (it is on no fiche). Runs first: the other
# sections' derived figures read the runs.
APPLY_ORDER: tuple[str, ...] = (
    "runs", "waste_production", "stops", "silo", "staffing", "packing", "packet_checks", "waste_packing",
)


def fingerprint(payload: Mapping[str, Any] | None) -> str:
    text = json.dumps(payload or {}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def count_rows(payload: Mapping[str, Any] | None) -> int:
    total = 0
    for value in (payload or {}).values():
        if isinstance(value, list):
            total += len(value)
        elif isinstance(value, dict):
            total += 1
    return total


def final_values(sections: Mapping[str, Mapping[str, Any]], header: Mapping[str, Any]) -> dict[str, Any]:
    """Every value by its field path, for rows that came from the scan (they carry `_scan_ref`)."""
    out = {path("header", "-", "-", key): value for key, value in header.items()}
    for section, parts in sections.items():
        for part, value in parts.items():
            if isinstance(value, list):
                for row in value:
                    ref = row.get("_scan_ref")
                    if ref:
                        out.update({path(section, part, ref, k): v for k, v in row.items() if not k.startswith("_")})
            elif isinstance(value, dict):
                out.update({path(section, part, "-", k): v for k, v in value.items() if not k.startswith("_")})
    return out


def strip_private(payload: Mapping[str, Any]) -> dict:
    """The payload without the screen's own keys (`_scan_ref`, `_key`, ...), as save_section takes it."""
    def clean(value: Any) -> Any:
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if not k.startswith("_")}
        return value
    return clean(dict(payload))


def stale_sections(
    requested: Collection[str], current: Mapping[str, Mapping[str, Any]] | None, shown: Mapping[str, str | None]
) -> list[str]:
    """Sections the review would overwrite that changed since the review loaded them."""
    changed = []
    for key in requested:
        now = (current or {}).get(key)
        expected = shown.get(key)
        if expected is None:
            if now is not None and now["rows"] > 0:
                changed.append(key)
        elif now is None or now["fingerprint"] != expected:
            changed.append(key)
    return changed


def _as_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return str(value).lower()
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value).strip()


def outcomes(proposal: Mapping[str, Any], finals: Mapping[str, Any]) -> list[dict]:
    """For every value the scan proposed: what was read, proposed and finally kept."""
    proposed = final_values(proposal["sections"], proposal["header"])
    rows = []
    for at, sources in proposal["sources"].items():
        first = sources[0]
        flags = proposal["flags"].get(at) or []
        before, after = _as_text(proposed.get(at)), _as_text(finals.get(at))
        rows.append({
            "field_path": at,
            "page_id": first["page_id"],
            "read_text": first["text"],
            "confidence": first["confidence"],
            "proposed_value": before,
            "final_value": after,
            "flag": flags[0]["reason"] if flags else None,
            "changed": before != after,
        })
    return rows


def aliases_to_learn(coded: Mapping[str, Mapping[str, Any]], finals: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """(kind, text written, value chosen) wherever the user chose something other than the resolution."""
    learned = []
    for at, entry in coded.items():
        final = finals.get(at)
        if final in (None, "") or final == entry["value"] or not entry["read_text"].strip():
            continue
        learned.append((entry["kind"], entry["read_text"], str(final)))
    return learned
```

- [ ] **Step 5: Run the whole domain suite**

Run: `.venv/Scripts/python -m pytest modules/scan/domain -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/scan/domain/proposal.py backend/modules/scan/domain/review.py backend/modules/scan/domain/test_proposal.py
git commit -m "feat(scan): build the review proposal; fingerprints, outcomes and alias learning"
```

### Task 8: Vocabulary from the other modules, and the alias dictionary

**Files:**
- Create: `backend/modules/scan/api/vocabulary_service.py`, `backend/modules/scan/api/alias_service.py`, `backend/modules/scan/api/scan_world.py` (integration-test world, not collected by pytest)
- Test: `backend/modules/scan/api/test_vocabulary_alias_integration.py`

**Interfaces:**
- Consumes: `CoreService.list_products(tenant_id)`, `ProductClassificationService.list_classifications(tenant_id)`, `WasteTypeService.list_builtin_settings(tenant_id=)` / `.list_types(tenant_id=, include_inactive=False)`, `EquipmentService.list_equipment(tenant_id=, work_center_id=)`, `MoldService.list_molds(tenant_id=)`, `ReportOptionsService.list_options(tenant_id=, kind="team")`, `DOWNTIME_MOTIFS_BY_REPORT_TYPE`; domain `Term`, `Vocabulary`, `KINDS`, `normalize`, `team_letter`.
- Produces: `build_vocabulary(connection, *, tenant_id, work_center_id) -> Vocabulary`; `vocabulary_options(vocabulary) -> dict[str, list[dict]]` (`{kind: [{value, label}]}`); `ScanAliasService(connection)` with `alias_map(*, tenant_id) -> dict[tuple[str, str], str]`, `list_aliases(*, tenant_id, kind=None) -> list[dict]`, `learn(*, tenant_id, actor_id, kind, read_text, target_value) -> None`, `update_alias(*, tenant_id, actor_id, alias_id, target_value) -> Result[dict]`, `delete_alias(*, tenant_id, actor_id, alias_id) -> Result[dict]`; `scan_world.make_world(db, tenant) -> dict`, `scan_world.fabrication_result(date="04/03/2030", hours="D 07 H") -> dict`, `scan_world.ok(result)`.

- [ ] **Step 1: Write the integration-test world**

```python
# backend/modules/scan/api/scan_world.py
"""A tenant with a PC line, its shifts, products and an open OF, for the scan integration tests."""
from __future__ import annotations

import datetime

from ulid import ULID

from core.domain.result import Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService

DAY = datetime.date(2030, 3, 4)  # lot D0063SNL: team D, year digit 0, day 63


def ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def make_world(db, tenant: str) -> dict:
    actor, uom, pasta, semoule, film, work_center, location = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, tenant, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, tenant))
    for product_id, sku, name in ((pasta, "SC-VERM", "Vermicelle 500g PC"), (semoule, "SC-SSSE", "Semoule SSSE"), (film, "SC-FILM", "Film Active PC")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, tenant, sku, name, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SC-LOC', 'Store')", (location, tenant))
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = ANY(%s)", (location, [pasta, semoule, film]))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12 WHERE id = %s", (pasta,))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SC-PC', 'Ligne PC')", (work_center, tenant))
    for shift, start, end in (("Matin", "07:00", "15:00"), ("Soir", "15:00", "23:00"), ("Nuit", "23:00", "07:00")):
        db.execute(
            "INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, %s, %s, %s)",
            (tenant, shift, start, end),
        )
    classes = ProductClassificationService(db)
    ok(classes.set_classification(tenant_id=tenant, actor_id=actor, product_id=pasta, category="finished_good", packaging_format="packet"))
    ok(classes.set_classification(tenant_id=tenant, actor_id=actor, product_id=semoule, category="raw_material"))
    ok(classes.set_classification(tenant_id=tenant, actor_id=actor, product_id=film, category="packaging_component", packaging_kind="film"))
    orders = WorkOrderService(db)
    of_id = ok(orders.create_work_order(
        tenant_id=tenant, actor_id=actor, product_id=pasta, planned_quantity=1000, work_center_id=work_center, start_date=DAY,
    )).id
    ok(orders.start_work_order(tenant_id=tenant, actor_id=actor, work_order_id=of_id))
    return {"tenant": tenant, "actor": actor, "pasta": pasta, "semoule": semoule, "film": film,
            "work_center": work_center, "of": of_id, "day": DAY}


def fabrication_result(date: str = "04/03/2030", hours: str = "D 07 H") -> dict:
    """What the OCR container returns for a small fabrication fiche of DAY."""
    def cell(text: str) -> dict:
        return {"text": text, "confidence": 0.9, "box": [0.1, 0.1, 0.2, 0.2]}

    return {
        "form_type": "fabrication", "form_confidence": 0.8, "rotation": 0, "accept_score": 0.5,
        "header": {"date": cell(date), "team_hours": cell(hours), "line_pc": cell("x"), "conducteur": cell("Conducteur Un")},
        "blocks": [
            {"key": "production", "found": True, "rows": [{"cells": {
                "lot": cell("D0063SNL"), "start": cell("07h00"), "end": cell("14h00"),
                "sem_origin": cell("SC-SSSE"), "sem_tonnes": cell("3,25"), "water": cell("28,9"),
            }}]},
            {"key": "stops", "found": True, "rows": [{"cells": {"panne": cell("coupure"), "start": cell("12h18"), "end": cell("12h37")}}]},
            {"key": "waste_petrin", "found": True, "rows": [{"cells": {"quantity": cell("1,47"), "cause": cell("Déchet semoule")}}]},
        ],
    }
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/modules/scan/api/test_vocabulary_alias_integration.py
import pytest

from core.domain.result import Err
from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.scan_world import make_world, ok
from modules.scan.api.vocabulary_service import build_vocabulary, vocabulary_options

TENANT = "scan-vocabulary-test"


@pytest.fixture
def world(db):
    return make_world(db, TENANT)


def test_vocabulary_is_built_from_the_plants_data(db, world):
    vocabulary = build_vocabulary(db, tenant_id=TENANT, work_center_id=world["work_center"])
    assert [t.value for t in vocabulary.of("raw_material")] == [world["semoule"]]
    assert vocabulary.attr("finished_product", world["pasta"], "net_weight_grams") == 500
    assert [t.value for t in vocabulary.of("film_item")] == [world["film"]]
    assert "press" in {t.value for t in vocabulary.of("waste_production")}
    assert "finished_product_conditioning" not in {t.value for t in vocabulary.of("waste_production")}
    assert {t.value for t in vocabulary.of("line_state")} == {"running", "stopped"}
    options = vocabulary_options(vocabulary)
    assert {"value": world["semoule"], "label": "Semoule SSSE"} in options["raw_material"]


def test_learning_an_alias_and_using_it(db, world):
    aliases = ScanAliasService(db)
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="raw_material", read_text=" BSK1 ", target_value=world["semoule"])
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="raw_material", read_text="bsk1", target_value=world["semoule"])
    assert aliases.alias_map(tenant_id=TENANT) == {("raw_material", "bsk1"): world["semoule"]}
    [row] = aliases.list_aliases(tenant_id=TENANT)
    assert (row["kind"], row["raw_text_example"], row["use_count"]) == ("raw_material", "bsk1", 2)
    audits = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'scan_alias.learned'", (TENANT,)
    ).fetchone()[0]
    assert audits == 2


def test_a_learned_alias_ignores_unknown_kinds_and_blank_text(db, world):
    aliases = ScanAliasService(db)
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="nonsense", read_text="x", target_value="y")
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="raw_material", read_text=" - ", target_value="y")
    assert aliases.list_aliases(tenant_id=TENANT) == []


def test_editing_and_deleting_an_alias(db, world):
    aliases = ScanAliasService(db)
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="equipment", read_text="C2", target_value="E1")
    [row] = aliases.list_aliases(tenant_id=TENANT, kind="equipment")
    updated = ok(aliases.update_alias(tenant_id=TENANT, actor_id=world["actor"], alias_id=row["id"], target_value="E2"))
    assert updated["target_value"] == "E2"
    assert isinstance(aliases.update_alias(tenant_id=TENANT, actor_id=world["actor"], alias_id=row["id"], target_value=" "), Err)
    ok(aliases.delete_alias(tenant_id=TENANT, actor_id=world["actor"], alias_id=row["id"]))
    assert aliases.list_aliases(tenant_id=TENANT) == []
    assert aliases.delete_alias(tenant_id=TENANT, actor_id=world["actor"], alias_id=row["id"]).code == "NOT_FOUND"
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/api/test_vocabulary_alias_integration.py -q`
Expected: FAIL — services missing.

- [ ] **Step 4: Implement `vocabulary_service.py`**

```python
# backend/modules/scan/api/vocabulary_service.py
"""The names a fiche's codes are matched against, read from the modules that own them."""
from __future__ import annotations

import psycopg

from core.api.service import CoreService
from core.report_options import ReportOptionsService
from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.api.mold_service import MoldService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.waste_type_service import WasteTypeService
from modules.production.domain.production_report import DOWNTIME_MOTIFS_BY_REPORT_TYPE
from modules.scan.domain.text import team_letter
from modules.scan.domain.vocabulary import Term, Vocabulary

# The built-in waste kinds' French names, as the shift form shows them when the plant has
# not renamed one (frontend i18n production.waste.category.*).
_BUILTIN_WASTE_NAMES = {
    "raw_material": "Matière", "press": "Presse", "pouring": "Versement", "cross": "Cross",
    "kneading": "Pétrin", "product": "Produit", "packaging": "Emballage",
}
_FIXED = {
    "line_state": (Term("running", ("En marche", "Marche")), Term("stopped", ("En arrêt", "Arrêt", "Arrêté"))),
    "check_state": (
        Term("good", ("Bon", "B", "OK", "Conforme", "Oui")),
        Term("not_good", ("Non bon", "NB", "Non conforme", "NC", "Mauvais", "Non")),
    ),
}


def build_vocabulary(connection: psycopg.Connection, *, tenant_id: str, work_center_id: str | None) -> Vocabulary:
    products = CoreService(connection).list_products(tenant_id)
    classes = {c.product_id: c for c in ProductClassificationService(connection).list_classifications(tenant_id)}

    def products_where(test) -> tuple[Term, ...]:
        return tuple(
            Term(p.id, (p.name, p.sku), {"net_weight_grams": p.net_weight_grams})
            for p in products
            if (c := classes.get(p.id)) is not None and test(c)
        )

    waste = WasteTypeService(connection)
    builtins = waste.list_builtin_settings(tenant_id=tenant_id)
    customs = waste.list_types(tenant_id=tenant_id, include_inactive=False)

    def waste_terms(report_type: str) -> tuple[Term, ...]:
        # finished_product_conditioning is refused on the production side ("one place per loss").
        terms = [
            Term(b["category"], tuple(n for n in (b["name"], _BUILTIN_WASTE_NAMES.get(b["category"])) if n))
            for b in builtins
            if b["report_type"] == report_type and b["is_active"] and b["category"] != "finished_product_conditioning"
        ]
        terms += [Term(t["id"], (t["name"],)) for t in customs if t["report_type"] == report_type]
        return tuple(terms)

    equipment = EquipmentService(connection).list_equipment(tenant_id=tenant_id, work_center_id=work_center_id)
    molds = MoldService(connection).list_molds(tenant_id=tenant_id)
    teams = ReportOptionsService(connection).list_options(tenant_id=tenant_id, kind="team")
    return Vocabulary({
        "raw_material": products_where(lambda c: c.category == "raw_material" and not c.is_water and not c.is_energy),
        "regrind_item": products_where(lambda c: c.is_regrind),
        "finished_product": products_where(lambda c: c.category == "finished_good"),
        "film_item": products_where(lambda c: c.packaging_kind == "film"),
        "waste_production": waste_terms("daily"),
        "waste_packing": waste_terms("conditionnement"),
        "equipment": tuple(Term(e.id, (e.code, e.name)) for e in equipment),
        "mold": tuple(Term(m.id, (m.code, m.name)) for m in molds),
        "downtime_motif": tuple(Term(code, (code,)) for code in sorted(DOWNTIME_MOTIFS_BY_REPORT_TYPE["daily"])),
        "team": tuple(Term(o["label"], (o["label"],), {"letter": team_letter(o["label"])}) for o in teams),
        **_FIXED,
    })


def vocabulary_options(vocabulary: Vocabulary) -> dict[str, list[dict]]:
    """Every kind's values with a readable label, for the dictionary screen."""
    return {
        kind: [{"value": t.value, "label": next((n for n in t.names if n), t.value)} for t in terms]
        for kind, terms in vocabulary.terms.items()
    }
```

- [ ] **Step 5: Implement `alias_service.py`**

```python
# backend/modules/scan/api/alias_service.py
"""The plant's own writing, learned: what a code on the fiche means in the system.

An alias is learned when a user, reviewing a scan, picks a value other than the one the
scan resolved. The next scan resolves the same writing to that value first. Admins can
correct or remove one from the Dictionnaire screen.
"""
from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.scan.domain.text import normalize
from modules.scan.domain.vocabulary import KINDS

_COLUMNS = "id, kind, raw_text_normalized, raw_text_example, target_value, use_count, updated_at"
_NAMES = tuple(n.strip() for n in _COLUMNS.split(","))
_NOT_FOUND = Err("NOT_FOUND", "dictionary entry not found", "entrée du dictionnaire introuvable")


def _row(values) -> dict:
    row = dict(zip(_NAMES, values))
    row["updated_at"] = row["updated_at"].isoformat()
    return row


class ScanAliasService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def alias_map(self, *, tenant_id: str) -> dict[tuple[str, str], str]:
        rows = self._connection.execute(
            "SELECT kind, raw_text_normalized, target_value FROM scan.scan_aliases WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()
        return {(kind, key): value for kind, key, value in rows}

    def list_aliases(self, *, tenant_id: str, kind: str | None = None) -> list[dict]:
        clause, params = ("tenant_id = %s", [tenant_id]) if kind is None else ("tenant_id = %s AND kind = %s", [tenant_id, kind])
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM scan.scan_aliases WHERE {clause} ORDER BY kind, raw_text_normalized", params
        ).fetchall()
        return [_row(r) for r in rows]

    def learn(self, *, tenant_id: str, actor_id: str, kind: str, read_text: str, target_value: str) -> None:
        key = normalize(read_text)
        if kind not in KINDS or not key or not str(target_value).strip():
            return
        alias_id = self._connection.execute(
            """
            INSERT INTO scan.scan_aliases (id, tenant_id, kind, raw_text_normalized, raw_text_example, target_value, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, kind, raw_text_normalized) DO UPDATE
            SET target_value = EXCLUDED.target_value, raw_text_example = EXCLUDED.raw_text_example,
                use_count = scan.scan_aliases.use_count + 1, updated_at = NOW()
            RETURNING id
            """,
            (str(ULID()), tenant_id, kind, key, read_text.strip(), str(target_value), actor_id),
        ).fetchone()[0]
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="scan_alias.learned",
            entity_type="scan_alias", entity_id=alias_id,
            payload={"kind": kind, "raw_text": read_text.strip(), "target_value": str(target_value)},
        )

    def _read(self, tenant_id: str, alias_id: str) -> dict | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM scan.scan_aliases WHERE id = %s AND tenant_id = %s", (alias_id, tenant_id)
        ).fetchone()
        return _row(row) if row else None

    def update_alias(self, *, tenant_id: str, actor_id: str, alias_id: str, target_value: str) -> Result[dict]:
        before = self._read(tenant_id, alias_id)
        if before is None:
            return _NOT_FOUND
        value = (target_value or "").strip()
        if not value:
            return Err("INVALID_VALUE", "a dictionary entry needs a value", "une entrée du dictionnaire a besoin d'une valeur")
        self._connection.execute(
            "UPDATE scan.scan_aliases SET target_value = %s, updated_at = NOW() WHERE id = %s AND tenant_id = %s",
            (value, alias_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="scan_alias.updated",
            entity_type="scan_alias", entity_id=alias_id, payload={"from": before["target_value"], "to": value},
        )
        return Ok(self._read(tenant_id, alias_id))

    def delete_alias(self, *, tenant_id: str, actor_id: str, alias_id: str) -> Result[dict]:
        before = self._read(tenant_id, alias_id)
        if before is None:
            return _NOT_FOUND
        self._connection.execute("DELETE FROM scan.scan_aliases WHERE id = %s AND tenant_id = %s", (alias_id, tenant_id))
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="scan_alias.deleted",
            entity_type="scan_alias", entity_id=alias_id,
            payload={"kind": before["kind"], "raw_text": before["raw_text_example"], "target_value": before["target_value"]},
        )
        return Ok(before)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan/api/test_vocabulary_alias_integration.py -q`
Expected: PASS (not skipped).

- [ ] **Step 7: Commit**

```bash
git add backend/modules/scan/api/vocabulary_service.py backend/modules/scan/api/alias_service.py backend/modules/scan/api/scan_world.py backend/modules/scan/api/test_vocabulary_alias_integration.py
git commit -m "feat(scan): vocabulary from the plant's data and a learning alias dictionary"
```

---

### Task 9: Scan sessions and their photos

**Files:**
- Create: `backend/modules/scan/api/session_service.py`
- Test: `backend/modules/scan/api/test_session_service_integration.py`

**Interfaces:**
- Consumes: `DashboardSettingsService.list_shift_windows(tenant_id=)` → `ShiftWindow(shift, start, end)`; `WorkCenterService.list_work_centers(tenant_id=)` → `.id/.code/.name`; `ShiftReportService.list_shifts(...)`, `.get_shift(...)`; domain `Selection`, `attribute`, `header_of_page`, `line_label_of`, `page_read_from_json`, `count_rows`, `fingerprint`.
- Produces `ScanSessionService(connection)`:
  - `create_session(*, tenant_id, actor_id, kind, work_center_id, report_date, shift, default_of_id) -> Result[dict]`
  - `get_session(*, tenant_id, session_id) -> Result[dict]` (session + `pages` + `shift` + `window`)
  - `list_sessions(*, tenant_id, status=None) -> list[dict]` (each with `page_count`, without `review_state`)
  - `add_pages(*, tenant_id, actor_id, session_id, files: list[dict]) -> Result[list[dict]]` (`files`: `{filename, content_type, width, height, data_base64}`)
  - `delete_page(*, tenant_id, actor_id, session_id, page_id) -> Result[None]`
  - `reread_page(*, tenant_id, actor_id, session_id, page_id, form_hint) -> Result[dict]`
  - `discard_session(*, tenant_id, actor_id, session_id) -> Result[dict]`
  - `page_image(*, tenant_id, page_id) -> Result[tuple[bytes, str]]`
  - `shift_pages(*, tenant_id, shift_report_id) -> list[dict]`
  - Session dict keys: `id kind work_center_id report_date shift default_of_id shift_report_id status review_state created_by created_at applied_at`. Page summary keys: `id status form_type form_hint rotation width height attempts error created_at read_at attribution` (`attribution`: `{verdict, reasons, read}` or None). Shift state: `{id status team conducteur agent_fabrication machiniste aide_machiniste default_lot_number sections: {key: {status revision rows fingerprint payload}}}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/api/test_session_service_integration.py
import base64

import pytest
from psycopg.types.json import Jsonb

from core.domain.result import Err
from modules.production.api.shift_report_service import ShiftReportService
from modules.scan.api.scan_world import fabrication_result, make_world, ok
from modules.scan.api.session_service import MAX_PAGES, ScanSessionService

TENANT = "scan-session-test"
JPEG = {"filename": "a.jpg", "content_type": "image/jpeg", "width": 1200, "height": 1600,
        "data_base64": base64.b64encode(b"\xff\xd8\xff fake jpeg").decode()}


@pytest.fixture
def world(db):
    return make_world(db, TENANT)


def _session(db, world, shift="Matin"):
    return ok(ScanSessionService(db).create_session(
        tenant_id=TENANT, actor_id=world["actor"], kind="shift", work_center_id=world["work_center"],
        report_date=world["day"], shift=shift, default_of_id=world["of"],
    ))


def test_create_and_read_a_session(db, world):
    session = _session(db, world)
    assert (session["status"], session["shift"], session["default_of_id"]) == ("open", "Matin", world["of"])
    detail = ok(ScanSessionService(db).get_session(tenant_id=TENANT, session_id=session["id"]))
    assert detail["pages"] == [] and detail["shift"] is None and detail["window"] == {"start": "07:00", "end": "15:00"}
    [listed] = ScanSessionService(db).list_sessions(tenant_id=TENANT)
    assert listed["page_count"] == 0 and "review_state" not in listed


def test_only_known_shifts_and_shift_fiches(db, world):
    service = ScanSessionService(db)
    common = dict(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], default_of_id=None)
    assert service.create_session(kind="shift", shift="Brunch", **common).code == "UNKNOWN_SHIFT"
    assert service.create_session(kind="qc", shift="Matin", **common).code == "NOT_SUPPORTED_YET"


def test_pages_are_queued_and_their_image_kept(db, world):
    service = ScanSessionService(db)
    session = _session(db, world)
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session["id"], files=[JPEG]))
    assert (page["status"], page["width"], page["attribution"]) == ("queued", 1200, None)
    image, content_type = ok(service.page_image(tenant_id=TENANT, page_id=page["id"]))
    assert image == b"\xff\xd8\xff fake jpeg" and content_type == "image/jpeg"
    assert service.page_image(tenant_id="another-tenant", page_id=page["id"]).code == "NOT_FOUND"


def test_upload_limits(db, world):
    service = ScanSessionService(db)
    session_id = _session(db, world)["id"]
    add = lambda files: service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=files)  # noqa: E731
    assert add([{**JPEG, "content_type": "image/heic"}]).code == "UNSUPPORTED_IMAGE"
    assert add([{**JPEG, "data_base64": "not base64!"}]).code == "UNSUPPORTED_IMAGE"
    big = base64.b64encode(b"0" * (8 * 1024 * 1024 + 1)).decode()
    assert add([{**JPEG, "data_base64": big}]).code == "IMAGE_TOO_LARGE"
    assert add([JPEG] * (MAX_PAGES + 1)).code == "TOO_MANY_PAGES"


def test_a_read_page_is_matched_to_the_shift(db, world):
    service = ScanSessionService(db)
    session = _session(db, world)
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session["id"], files=[JPEG]))
    db.execute(
        "UPDATE scan.scan_pages SET status = 'read', form_type = 'fabrication', ocr_result = %s WHERE id = %s",
        (Jsonb(fabrication_result(hours="A 15H")), page["id"]),
    )
    [summary] = ok(service.get_session(tenant_id=TENANT, session_id=session["id"]))["pages"]
    assert summary["attribution"]["verdict"] == "other_shift" and summary["attribution"]["reasons"] == ["hours"]


def test_delete_reread_and_discard(db, world):
    service = ScanSessionService(db)
    session_id = _session(db, world)["id"]
    [first, second] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=[JPEG, JPEG]))
    ok(service.delete_page(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, page_id=first["id"]))
    db.execute("UPDATE scan.scan_pages SET status = 'failed', attempts = 3, error = 'down' WHERE id = %s", (second["id"],))
    reread = ok(service.reread_page(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, page_id=second["id"], form_hint="conditionnement"))
    assert (reread["status"], reread["attempts"], reread["error"], reread["form_hint"]) == ("queued", 0, None, "conditionnement")
    assert service.reread_page(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, page_id=second["id"], form_hint="menu").code == "INVALID_VALUE"
    ok(service.discard_session(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id))
    refused = service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=[JPEG])
    assert isinstance(refused, Err) and refused.code == "SESSION_CLOSED"


def test_the_shift_state_shows_existing_sections(db, world):
    reports = ShiftReportService(db)
    shift_id = ok(reports.open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))["id"]
    ok(reports.save_section(tenant_id=TENANT, actor_id=world["actor"], shift_report_id=shift_id, section_key="stops",
                            payload={"stops": [{"started_at": "2030-03-04T08:00", "note": "x"}]}))
    session = _session(db, world)
    shift = ok(ScanSessionService(db).get_session(tenant_id=TENANT, session_id=session["id"]))["shift"]
    assert shift["id"] == shift_id
    assert (shift["sections"]["stops"]["status"], shift["sections"]["stops"]["rows"]) == ("draft", 1)
    assert shift["sections"]["runs"]["rows"] == 0 and len(shift["sections"]["stops"]["fingerprint"]) == 16


def test_audit_rows_for_session_changes(db, world):
    service = ScanSessionService(db)
    session_id = _session(db, world)["id"]
    ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=[JPEG]))
    actions = {r[0] for r in db.execute("SELECT action FROM core.audit_log WHERE tenant_id = %s", (TENANT,)).fetchall()}
    assert {"scan_session.created", "scan_session.pages_added"} <= actions
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/api/test_session_service_integration.py -q`
Expected: FAIL — `session_service` missing.

- [ ] **Step 3: Implement the session part of `session_service.py`**

```python
# backend/modules/scan/api/session_service.py
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
from psycopg.types.json import Jsonb
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan/api/test_session_service_integration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/scan/api/session_service.py backend/modules/scan/api/test_session_service_integration.py
git commit -m "feat(scan): scan sessions, photo upload and the shift they fill"
```

---

### Task 10: The proposal endpoint's service and the review autosave

**Files:**
- Modify: `backend/modules/scan/api/session_service.py` (add `_context`, `_build`, `proposal`, `save_review`)
- Test: `backend/modules/scan/api/test_proposal_service_integration.py`

**Interfaces:**
- Consumes: Task 8 (`build_vocabulary`, `ScanAliasService.alias_map`), Task 7 (`build_proposal`), `WorkOrderService.list_work_orders(tenant_id)`.
- Produces: `ScanSessionService.proposal(*, tenant_id, session_id) -> Result[dict]` → `{"proposal", "shift", "review_state"}`; `ScanSessionService.save_review(*, tenant_id, session_id, review_state: dict) -> Result[None]`; private `_build(tenant_id, session, shift) -> Result[dict]` reused by apply. `review_state["include_pages"]` (list of page ids) is honoured by the proposal.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/api/test_proposal_service_integration.py
import base64

import pytest
from psycopg.types.json import Jsonb

from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.scan_world import fabrication_result, make_world, ok
from modules.scan.api.session_service import ScanSessionService

TENANT = "scan-proposal-test"
JPEG = {"filename": "a.jpg", "content_type": "image/jpeg", "data_base64": base64.b64encode(b"\xff\xd8 x").decode()}


@pytest.fixture
def world(db):
    return make_world(db, TENANT)


def _session_with_page(db, world, result):
    service = ScanSessionService(db)
    session = ok(service.create_session(
        tenant_id=TENANT, actor_id=world["actor"], kind="shift", work_center_id=world["work_center"],
        report_date=world["day"], shift="Matin", default_of_id=world["of"],
    ))
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session["id"], files=[JPEG]))
    db.execute(
        "UPDATE scan.scan_pages SET status = 'read', form_type = %s, ocr_result = %s WHERE id = %s",
        (result["form_type"], Jsonb(result), page["id"]),
    )
    return service, session["id"], page["id"]


def test_the_proposal_uses_the_plants_names_and_the_default_of(db, world):
    service, session_id, _ = _session_with_page(db, world, fabrication_result())
    body = ok(service.proposal(tenant_id=TENANT, session_id=session_id))
    proposal = body["proposal"]
    [run] = proposal["sections"]["runs"]["runs"]
    assert (run["of_id"], run["lot_number"], run["production_minutes"]) == (world["of"], "D0063SNL", 420)
    [versement] = proposal["sections"]["runs"]["versements"]
    assert (versement["product_id"], versement["quantity"]) == (world["semoule"], 3.25)
    assert proposal["header"]["conducteur"] == "Conducteur Un"
    assert body["shift"] is None and body["review_state"] == {}


def test_a_learned_alias_is_used_by_the_next_proposal(db, world):
    service, session_id, _ = _session_with_page(db, world, fabrication_result())
    ScanAliasService(db).learn(tenant_id=TENANT, actor_id=world["actor"], kind="waste_production", read_text="Déchet semoule", target_value="raw_material")
    [line] = ok(service.proposal(tenant_id=TENANT, session_id=session_id))["proposal"]["sections"]["waste_production"]["waste_lines"]
    assert line["category"] == "raw_material"


def test_an_other_shift_page_is_included_through_the_review_state(db, world):
    service, session_id, page_id = _session_with_page(db, world, fabrication_result(hours="A 15H"))
    assert ok(service.proposal(tenant_id=TENANT, session_id=session_id))["proposal"]["sections"] == {}
    ok(service.save_review(tenant_id=TENANT, session_id=session_id, review_state={"include_pages": [page_id]}))
    body = ok(service.proposal(tenant_id=TENANT, session_id=session_id))
    assert "runs" in body["proposal"]["sections"] and body["review_state"] == {"include_pages": [page_id]}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/api/test_proposal_service_integration.py -q`
Expected: FAIL — `AttributeError: 'ScanSessionService' object has no attribute 'proposal'`.

- [ ] **Step 3: Implement**

Add these imports to `session_service.py`:

```python
from modules.production.api.service import WorkOrderService
from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.vocabulary_service import build_vocabulary
from modules.scan.domain.draft import ProposalContext
from modules.scan.domain.proposal import build_proposal
```

and these methods to `ScanSessionService` (after `shift_pages`):

```python
    # ---- proposal and review -----------------------------------------------

    def _context(self, tenant_id: str, session: dict, shift: dict | None) -> ProposalContext | None:
        window = self._window(tenant_id, session["shift"])
        if window is None:
            return None
        default_product = None
        if session["default_of_id"]:
            orders = WorkOrderService(self._connection).list_work_orders(tenant_id)
            order = next((o for o in orders if o.id == session["default_of_id"]), None)
            default_product = order.product_id if order else None
        return ProposalContext(
            report_date=datetime.date.fromisoformat(session["report_date"]),
            shift_start=window.start,
            shift_end=window.end,
            team=shift["team"] if shift else None,
            default_of_id=session["default_of_id"],
            default_product_id=default_product,
            vocabulary=build_vocabulary(self._connection, tenant_id=tenant_id, work_center_id=session["work_center_id"]),
            aliases=ScanAliasService(self._connection).alias_map(tenant_id=tenant_id),
        )

    def _build(self, tenant_id: str, session: dict, shift: dict | None) -> Result[dict]:
        ctx = self._context(tenant_id, session, shift)
        selection = self._selection(tenant_id, session)
        if ctx is None or selection is None:
            return Err("UNKNOWN_SHIFT", f"{session['shift']!r} is no longer one of the plant's shifts",
                       f"{session['shift']!r} ne fait plus partie des shifts de l'usine")
        pages = [
            page_read_from_json(p["id"], p["ocr_result"])
            for p in self._pages(tenant_id, session["id"])
            if p["status"] == "read" and p["ocr_result"]
        ]
        include = set((session["review_state"] or {}).get("include_pages") or [])
        return Ok(build_proposal(pages, ctx, selection, include))

    def proposal(self, *, tenant_id: str, session_id: str) -> Result[dict]:
        session = self._session_row(tenant_id, session_id)
        if session is None:
            return _SESSION_NOT_FOUND
        shift = self._shift_state(tenant_id, session)
        built = self._build(tenant_id, session, shift)
        if isinstance(built, Err):
            return built
        return Ok({"proposal": built.value, "shift": shift, "review_state": session["review_state"]})

    def save_review(self, *, tenant_id: str, session_id: str, review_state: dict) -> Result[None]:
        """The review in progress, autosaved while the user works.

        Not audited: it is a working copy saved every few seconds, like a form draft in the
        browser; what the review decides is audited when it is applied.
        """
        found = self._open_session(tenant_id, session_id)
        if isinstance(found, Err):
            return found
        self._connection.execute(
            "UPDATE scan.scan_sessions SET review_state = %s, updated_at = NOW() WHERE id = %s AND tenant_id = %s",
            (Jsonb(review_state), session_id, tenant_id),
        )
        return Ok(None)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan/api -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/scan/api/session_service.py backend/modules/scan/api/test_proposal_service_integration.py
git commit -m "feat(scan): build the proposal for a session and autosave its review"
```

---

### Task 11: Applying a reviewed scan to the shift report

**Files:**
- Modify: `backend/modules/scan/api/session_service.py` (add `apply`)
- Test: `backend/modules/scan/api/test_apply_integration.py`

**Interfaces:**
- Consumes: `ShiftReportService.open_shift / update_header / save_section(..., reason=)`; domain `APPLY_ORDER`, `stale_sections`, `strip_private`, `final_values`, `outcomes`, `aliases_to_learn`; `ScanAliasService.learn`.
- Produces: `ScanSessionService.apply(*, tenant_id, actor_id, session_id, header: dict, sections: dict, fingerprints: dict, allowed_sections: set[str]) -> Result[dict]` → `{"shift_report_id", "sections_written"}`. Error codes: `NOTHING_TO_APPLY`, `INVALID_SECTION`, `FORBIDDEN_SECTION`, `SHIFT_VALIDATED`, `SECTION_CHANGED`, `SESSION_CLOSED`, and any `save_section` code with its message prefixed by the section key.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/api/test_apply_integration.py
import base64

import pytest
from psycopg.types.json import Jsonb

from modules.production.api.shift_report_service import ShiftReportService
from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.scan_world import fabrication_result, make_world, ok
from modules.scan.api.session_service import ScanSessionService
from modules.scan.domain.review import APPLY_ORDER

TENANT = "scan-apply-test"
ALL = set(APPLY_ORDER)
JPEG = {"filename": "a.jpg", "content_type": "image/jpeg", "data_base64": base64.b64encode(b"\xff\xd8 x").decode()}


@pytest.fixture
def world(db):
    return make_world(db, TENANT)


def _reviewed(db, world):
    """A session with one read fabrication page, and the review a user would send."""
    service = ScanSessionService(db)
    session_id = ok(service.create_session(
        tenant_id=TENANT, actor_id=world["actor"], kind="shift", work_center_id=world["work_center"],
        report_date=world["day"], shift="Matin", default_of_id=world["of"],
    ))["id"]
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=[JPEG]))
    db.execute("UPDATE scan.scan_pages SET status = 'read', form_type = 'fabrication', ocr_result = %s WHERE id = %s",
               (Jsonb(fabrication_result()), page["id"]))
    body = ok(service.proposal(tenant_id=TENANT, session_id=session_id))
    sections = body["proposal"]["sections"]
    sections["waste_production"]["waste_lines"][0]["category"] = "raw_material"  # the user picks the kind
    fingerprints = {k: v["fingerprint"] for k, v in (body["shift"] or {}).get("sections", {}).items()}
    return service, session_id, body["proposal"]["header"], sections, fingerprints


def _apply(service, world, session_id, header, sections, fingerprints, allowed=ALL):
    return service.apply(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, header=header,
                         sections=sections, fingerprints=fingerprints, allowed_sections=allowed)


def test_apply_writes_drafts_and_closes_the_session(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    result = ok(_apply(service, world, session_id, header, sections, fingerprints))
    assert result["sections_written"] == ["runs", "waste_production", "stops"]
    shift = ok(ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=result["shift_report_id"]))
    states = {s["key"]: s for s in shift["sections"]}
    assert states["runs"]["status"] == "draft" and states["runs"]["payload"]["runs"][0]["lot_number"] == "D0063SNL"
    assert states["stops"]["payload"]["stops"][0]["note"] == "coupure"
    assert shift["conducteur"] == "Conducteur Un"
    session = ok(service.get_session(tenant_id=TENANT, session_id=session_id))
    assert (session["status"], session["shift_report_id"]) == ("applied", result["shift_report_id"])
    assert db.execute("SELECT count(*) FROM scan.scan_field_outcomes WHERE session_id = %s", (session_id,)).fetchone()[0] > 0
    assert db.execute("SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'scan_session.applied'", (TENANT,)).fetchone()[0] == 1


def test_apply_learns_the_codes_the_user_corrected(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    ok(_apply(service, world, session_id, header, sections, fingerprints))
    assert ScanAliasService(db).alias_map(tenant_id=TENANT)[("waste_production", "dechet semoule")] == "raw_material"


def test_a_section_the_save_refuses_names_itself(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    sections["waste_production"]["waste_lines"][0]["category"] = None
    refused = _apply(service, world, session_id, header, sections, fingerprints)
    assert refused.code == "INVALID_VALUE" and refused.message.startswith("waste_production:")


def test_apply_refuses_a_section_changed_since_review(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    reports = ShiftReportService(db)
    shift_id = ok(reports.open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))["id"]
    ok(reports.save_section(tenant_id=TENANT, actor_id=world["actor"], shift_report_id=shift_id, section_key="stops",
                            payload={"stops": [{"started_at": "2030-03-04T08:00", "note": "typed by the team"}]}))
    refused = _apply(service, world, session_id, header, sections, fingerprints)
    assert refused.code == "SECTION_CHANGED" and "stops" in refused.message


def test_apply_never_writes_a_validated_shift(db, world):
    service, session_id, header, sections, _ = _reviewed(db, world)
    shift_id = ok(ShiftReportService(db).open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))["id"]
    db.execute("UPDATE production.shift_reports SET status = 'validated' WHERE id = %s", (shift_id,))
    assert _apply(service, world, session_id, header, sections, {}).code == "SHIFT_VALIDATED"


def test_apply_needs_each_sections_right(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    refused = _apply(service, world, session_id, header, sections, fingerprints, allowed={"runs", "stops"})
    assert refused.code == "FORBIDDEN_SECTION" and "waste_production" in refused.message


def test_a_submitted_section_is_replaced_with_a_revision(db, world):
    service, session_id, header, sections, _ = _reviewed(db, world)
    reports = ShiftReportService(db)
    shift_id = ok(reports.open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))["id"]
    ok(reports.save_section(tenant_id=TENANT, actor_id=world["actor"], shift_report_id=shift_id, section_key="stops",
                            payload={"stops": [{"started_at": "2030-03-04T08:00", "note": "old"}]}))
    ok(reports.submit_section(tenant_id=TENANT, actor_id=world["actor"], shift_report_id=shift_id, section_key="stops"))
    fingerprints = {k: v["fingerprint"] for k, v in ok(service.proposal(tenant_id=TENANT, session_id=session_id))["shift"]["sections"].items()}
    ok(_apply(service, world, session_id, header, {"stops": sections["stops"]}, fingerprints))
    stops = next(s for s in ok(reports.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"] if s["key"] == "stops")
    assert (stops["status"], stops["revised_after_submit"], stops["payload"]["stops"][0]["note"]) == ("submitted", True, "coupure")


def test_nothing_to_apply(db, world):
    service, session_id, header, _, _ = _reviewed(db, world)
    assert _apply(service, world, session_id, header, {}, {}).code == "NOTHING_TO_APPLY"
    assert _apply(service, world, session_id, header, {"energy": {}}, {}).code == "INVALID_SECTION"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/api/test_apply_integration.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'apply'`.

- [ ] **Step 3: Implement**

Add to the imports of `session_service.py`:

```python
from modules.scan.domain.review import (
    APPLY_ORDER, aliases_to_learn, count_rows, final_values, fingerprint, outcomes, stale_sections, strip_private,
)
```

(replacing the earlier `count_rows, fingerprint` import), add the constants:

```python
HEADER_FIELDS = ("team", "conducteur", "agent_fabrication", "machiniste", "aide_machiniste")
APPLY_REASON = "Import depuis photos"
```

and the method:

```python
    # ---- apply -------------------------------------------------------------

    def apply(
        self, *, tenant_id: str, actor_id: str, session_id: str, header: dict, sections: dict,
        fingerprints: dict, allowed_sections: set[str],
    ) -> Result[dict]:
        """Write the reviewed sections into the shift report as drafts, all or nothing.

        The caller commits on Ok and rolls back on Err, so a section save_section refuses
        leaves nothing written.
        """
        found = self._open_session(tenant_id, session_id)
        if isinstance(found, Err):
            return found
        session = found.value
        if not sections:
            return Err("NOTHING_TO_APPLY", "no section was chosen to write", "aucune section n'a été choisie")
        unknown = sorted(k for k in sections if k not in APPLY_ORDER)
        if unknown:
            return Err("INVALID_SECTION", f"these sections cannot be imported: {', '.join(unknown)}",
                       f"ces sections ne peuvent pas être importées : {', '.join(unknown)}")
        refused = sorted(k for k in sections if k not in allowed_sections)
        if refused:
            return Err("FORBIDDEN_SECTION", f"you may not edit: {', '.join(refused)}", f"vous ne pouvez pas modifier : {', '.join(refused)}")
        shift = self._shift_state(tenant_id, session)
        if shift is not None and shift["status"] == "validated":
            return Err("SHIFT_VALIDATED", "this shift is validated and its stock posted; it must be returned before it can change",
                       "ce shift est validé et son stock passé ; il doit être renvoyé avant toute modification")
        stale = stale_sections(list(sections), shift["sections"] if shift else None, fingerprints)
        if stale:
            return Err("SECTION_CHANGED", f"changed since the review was loaded: {', '.join(stale)}",
                       f"modifiées depuis le chargement de la vérification : {', '.join(stale)}")
        built = self._build(tenant_id, session, shift)
        if isinstance(built, Err):
            return built

        reports = ShiftReportService(self._connection)
        header_fields = {k: header[k] for k in HEADER_FIELDS if header.get(k) not in (None, "")}
        if shift is None:
            opened = reports.open_shift(
                tenant_id=tenant_id, actor_id=actor_id, work_center_id=session["work_center_id"],
                report_date=datetime.date.fromisoformat(session["report_date"]), shift=session["shift"],
                team=header_fields.get("team"),
            )
            if isinstance(opened, Err):
                return opened
            shift_id = opened.value["id"]
        else:
            shift_id = shift["id"]
        if header_fields:
            updated = reports.update_header(tenant_id=tenant_id, actor_id=actor_id, shift_report_id=shift_id, fields=header_fields)
            if isinstance(updated, Err):
                return updated
        written = []
        for key in APPLY_ORDER:
            if key not in sections:
                continue
            saved = reports.save_section(
                tenant_id=tenant_id, actor_id=actor_id, shift_report_id=shift_id, section_key=key,
                payload=strip_private(sections[key]), reason=APPLY_REASON,
            )
            if isinstance(saved, Err):
                return Err(saved.code, f"{key}: {saved.message}", f"{key} : {saved.message_fr or saved.message}")
            written.append(key)

        finals = final_values(sections, header)
        aliases = ScanAliasService(self._connection)
        for kind, read_text, value in aliases_to_learn(built.value["coded"], finals):
            aliases.learn(tenant_id=tenant_id, actor_id=actor_id, kind=kind, read_text=read_text, target_value=value)
        for row in outcomes(built.value, finals):
            self._connection.execute(
                """
                INSERT INTO scan.scan_field_outcomes
                    (id, tenant_id, session_id, page_id, field_path, read_text, confidence, proposed_value, final_value, flag, changed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, session_id, row["page_id"], row["field_path"], row["read_text"], row["confidence"],
                 row["proposed_value"], row["final_value"], row["flag"], row["changed"]),
            )
        self._connection.execute(
            "UPDATE scan.scan_sessions SET status = 'applied', shift_report_id = %s, applied_by = %s, applied_at = NOW(), "
            "updated_at = NOW() WHERE id = %s AND tenant_id = %s",
            (shift_id, actor_id, session_id, tenant_id),
        )
        self._audit(tenant_id, actor_id, "scan_session.applied", session_id,
                    {"shift_report_id": shift_id, "sections_written": written, "header": sorted(header_fields)})
        return Ok({"shift_report_id": shift_id, "sections_written": written})
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/scan/api/session_service.py backend/modules/scan/api/test_apply_integration.py
git commit -m "feat(scan): apply a reviewed scan as shift report drafts"
```

---

### Task 12: The `/scan` router

**Files:**
- Create: `backend/modules/scan/api/router.py`
- Modify: `backend/app/main.py` (import + `app.include_router(scan_router)` after `maintenance_router`)
- Test: `backend/modules/scan/api/test_router_integration.py`

**Interfaces:**
- Consumes: Tasks 8–11; `core.tenancy` (`TenantContext`, `require_permission`, `require_session`, `user_has_permission`); `core.db.get_connection`; `core.domain.result.err_detail`.
- Produces the HTTP API (all under `/scan`): `POST /sessions` (201), `GET /sessions?status=`, `GET /sessions/{id}`, `POST /sessions/{id}/pages` (201; body `{files: [{filename, content_type, width, height, data_base64}]}`), `DELETE /sessions/{id}/pages/{page_id}`, `POST /sessions/{id}/pages/{page_id}/reread` (`{form_hint}`), `GET /pages/{page_id}/image`, `GET /sessions/{id}/proposal`, `PUT /sessions/{id}/review` (`{review_state}`), `POST /sessions/{id}/apply` (`{header, sections, fingerprints}`), `POST /sessions/{id}/discard`, `GET /shifts/{shift_report_id}/pages`, `GET /aliases?kind=`, `PATCH /aliases/{id}` (`{target_value}`), `DELETE /aliases/{id}`, `GET /vocabulary?work_center_id=`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/api/test_router_integration.py
"""The scan endpoints over HTTP: rights, error shapes, and the image round trip."""
from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.scan.api import router as router_module  # noqa: E402
from modules.scan.api.scan_world import make_world  # noqa: E402

TENANT = "scan-router-test"
IMAGE = b"\xff\xd8\xff router jpeg"


class _Connection:
    """The fixture's connection, with the transaction left to the fixture."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


@pytest.fixture
def api(db, monkeypatch):
    world = make_world(db, TENANT)
    wrapped = _Connection(db)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=world["actor"], session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (world["actor"], permission))

    return {"client": TestClient(app), "grant": grant, "world": world}


def _create(api) -> str:
    world = api["world"]
    response = api["client"].post("/scan/sessions", json={
        "work_center_id": world["work_center"], "report_date": world["day"].isoformat(), "shift": "Matin", "default_of_id": world["of"],
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_no_scan_right_no_access(api):
    assert api["client"].get("/scan/sessions").status_code == 403


def test_upload_and_fetch_the_image(api):
    api["grant"]("scan.use_scanner")
    session_id = _create(api)
    uploaded = api["client"].post(f"/scan/sessions/{session_id}/pages", json={"files": [
        {"filename": "p.jpg", "content_type": "image/jpeg", "width": 10, "height": 20, "data_base64": base64.b64encode(IMAGE).decode()},
    ]})
    assert uploaded.status_code == 201, uploaded.text
    page_id = uploaded.json()[0]["id"]
    image = api["client"].get(f"/scan/pages/{page_id}/image")
    assert image.status_code == 200 and image.content == IMAGE and image.headers["content-type"] == "image/jpeg"
    detail = api["client"].get(f"/scan/sessions/{session_id}").json()
    assert [p["status"] for p in detail["pages"]] == ["queued"]


def test_errors_carry_code_and_french_message(api):
    api["grant"]("scan.use_scanner")
    response = api["client"].post("/scan/sessions", json={
        "work_center_id": api["world"]["work_center"], "report_date": "2030-03-04", "shift": "Brunch",
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNKNOWN_SHIFT" and response.json()["detail"]["message_fr"]


def test_apply_without_the_section_right_is_forbidden(api):
    api["grant"]("scan.use_scanner", "production.shift.edit.stops")
    session_id = _create(api)
    response = api["client"].post(f"/scan/sessions/{session_id}/apply", json={"header": {}, "sections": {"runs": {"runs": []}}, "fingerprints": {}})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "FORBIDDEN_SECTION"


def test_viewers_see_a_shifts_photos_but_cannot_scan(api):
    api["grant"]("scan.view_scans")
    assert api["client"].get("/scan/shifts/nothing/pages").json() == []
    assert api["client"].get("/scan/sessions").status_code == 403


def test_alias_edits_need_the_admin_right(api):
    api["grant"]("scan.use_scanner")
    assert api["client"].get("/scan/aliases").json() == []
    assert api["client"].delete("/scan/aliases/unknown").status_code == 403
    api["grant"]("scan.admin_aliases")
    assert api["client"].delete("/scan/aliases/unknown").status_code == 404


def test_vocabulary_lists_the_kinds(api):
    api["grant"]("scan.use_scanner")
    body = api["client"].get("/scan/vocabulary", params={"work_center_id": api["world"]["work_center"]}).json()
    assert {"raw_material", "finished_product", "waste_production", "line_state"} <= set(body)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/api/test_router_integration.py -q`
Expected: FAIL — `modules.scan.api.router` missing.

- [ ] **Step 3: Implement `router.py`**

```python
# backend/modules/scan/api/router.py
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, require_session, user_has_permission
from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.session_service import ScanSessionService
from modules.scan.api.vocabulary_service import build_vocabulary, vocabulary_options
from modules.scan.domain.review import APPLY_ORDER

router = APIRouter(prefix="/scan", tags=["scan"])

_STATUS_BY_CODE = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "FORBIDDEN_SECTION": status.HTTP_403_FORBIDDEN,
    "SHIFT_VALIDATED": status.HTTP_409_CONFLICT,
    "SECTION_CHANGED": status.HTTP_409_CONFLICT,
    "SESSION_CLOSED": status.HTTP_409_CONFLICT,
}


class CreateSessionRequest(BaseModel):
    kind: str = "shift"
    work_center_id: str
    report_date: datetime.date
    shift: str
    default_of_id: str | None = None


class PageUpload(BaseModel):
    filename: str | None = None
    content_type: str
    width: int | None = None
    height: int | None = None
    data_base64: str


class UploadPagesRequest(BaseModel):
    files: list[PageUpload]


class RereadRequest(BaseModel):
    form_hint: str | None = None


class ReviewRequest(BaseModel):
    review_state: dict


class ApplyRequest(BaseModel):
    header: dict = Field(default_factory=dict)
    sections: dict = Field(default_factory=dict)
    fingerprints: dict = Field(default_factory=dict)


class AliasUpdateRequest(BaseModel):
    target_value: str


def _forbidden(permission: str) -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        {"code": "FORBIDDEN", "message": f"missing permission: {permission}", "message_fr": f"permission manquante : {permission}"},
    )


def _scanner_or_viewer(tenant: TenantContext = Depends(require_session)) -> TenantContext:
    """The photos behind a shift are open to whoever scans and to whoever only views them."""
    with get_connection() as connection:
        if not any(user_has_permission(connection, user_id=tenant.user_id, permission=p) for p in ("scan.use_scanner", "scan.view_scans")):
            raise _forbidden("scan.view_scans")
    return tenant


def _result(connection, result):
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    connection.commit()
    return result.value


USE = require_permission("scan.use_scanner")


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(body: CreateSessionRequest, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).create_session(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, kind=body.kind, work_center_id=body.work_center_id,
            report_date=body.report_date, shift=body.shift, default_of_id=body.default_of_id,
        ))


@router.get("/sessions")
def list_sessions(status_filter: str | None = Query(default=None, alias="status"), tenant: TenantContext = Depends(USE)) -> list[dict]:
    with get_connection() as connection:
        return ScanSessionService(connection).list_sessions(tenant_id=tenant.tenant_id, status=status_filter)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).get_session(tenant_id=tenant.tenant_id, session_id=session_id))


@router.post("/sessions/{session_id}/pages", status_code=status.HTTP_201_CREATED)
def add_pages(session_id: str, body: UploadPagesRequest, tenant: TenantContext = Depends(USE)) -> list[dict]:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).add_pages(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id,
            files=[upload.model_dump() for upload in body.files],
        ))


@router.delete("/sessions/{session_id}/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_page(session_id: str, page_id: str, tenant: TenantContext = Depends(USE)) -> Response:
    with get_connection() as connection:
        _result(connection, ScanSessionService(connection).delete_page(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id, page_id=page_id,
        ))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/pages/{page_id}/reread")
def reread_page(session_id: str, page_id: str, body: RereadRequest, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).reread_page(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id, page_id=page_id, form_hint=body.form_hint,
        ))


@router.get("/pages/{page_id}/image")
def page_image(page_id: str, tenant: TenantContext = Depends(_scanner_or_viewer)) -> Response:
    with get_connection() as connection:
        image, content_type = _result(connection, ScanSessionService(connection).page_image(tenant_id=tenant.tenant_id, page_id=page_id))
    return Response(content=image, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/sessions/{session_id}/proposal")
def proposal(session_id: str, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).proposal(tenant_id=tenant.tenant_id, session_id=session_id))


@router.put("/sessions/{session_id}/review", status_code=status.HTTP_204_NO_CONTENT)
def save_review(session_id: str, body: ReviewRequest, tenant: TenantContext = Depends(USE)) -> Response:
    with get_connection() as connection:
        _result(connection, ScanSessionService(connection).save_review(
            tenant_id=tenant.tenant_id, session_id=session_id, review_state=body.review_state,
        ))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/apply")
def apply(session_id: str, body: ApplyRequest, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        # The production module's own per-section edit rights (declared in its module.json).
        allowed = {
            key for key in APPLY_ORDER
            if user_has_permission(connection, user_id=tenant.user_id, permission=f"production.shift.edit.{key}")
        }
        return _result(connection, ScanSessionService(connection).apply(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id, header=body.header,
            sections=body.sections, fingerprints=body.fingerprints, allowed_sections=allowed,
        ))


@router.post("/sessions/{session_id}/discard")
def discard(session_id: str, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).discard_session(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id,
        ))


@router.get("/shifts/{shift_report_id}/pages")
def shift_pages(shift_report_id: str, tenant: TenantContext = Depends(_scanner_or_viewer)) -> list[dict]:
    with get_connection() as connection:
        return ScanSessionService(connection).shift_pages(tenant_id=tenant.tenant_id, shift_report_id=shift_report_id)


@router.get("/aliases")
def list_aliases(kind: str | None = None, tenant: TenantContext = Depends(USE)) -> list[dict]:
    with get_connection() as connection:
        return ScanAliasService(connection).list_aliases(tenant_id=tenant.tenant_id, kind=kind)


@router.patch("/aliases/{alias_id}")
def update_alias(alias_id: str, body: AliasUpdateRequest, tenant: TenantContext = Depends(require_permission("scan.admin_aliases"))) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanAliasService(connection).update_alias(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, alias_id=alias_id, target_value=body.target_value,
        ))


@router.delete("/aliases/{alias_id}")
def delete_alias(alias_id: str, tenant: TenantContext = Depends(require_permission("scan.admin_aliases"))) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanAliasService(connection).delete_alias(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, alias_id=alias_id,
        ))


@router.get("/vocabulary")
def vocabulary(work_center_id: str | None = None, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return vocabulary_options(build_vocabulary(connection, tenant_id=tenant.tenant_id, work_center_id=work_center_id))
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, beside the other module imports add
`from modules.scan.api.router import router as scan_router`
and after `app.include_router(maintenance_router)` add `app.include_router(scan_router)`.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan -q`
Expected: PASS (the router tests need `httpx` from `requirements-dev.txt`; they skip without it — install it rather than accept the skip).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/scan/api/router.py backend/modules/scan/api/test_router_integration.py backend/app/main.py
git commit -m "feat(scan): /scan HTTP API"
```

---

### Task 13: OCR client, the reading queue and the worker thread

**Files:**
- Create: `backend/modules/scan/api/ocr_client.py`, `backend/modules/scan/api/reader.py`
- Modify: `backend/worker/main.py`
- Test: `backend/modules/scan/api/test_reader_integration.py`

**Interfaces:**
- Produces: `OcrUnavailable(Exception)`; `OcrClient(base_url, timeout=180).read(image: bytes, form_hint: str | None) -> dict`; `reader.MAX_ATTEMPTS = 3`; `read_next_page(connection, read: Callable[[bytes, str | None], dict]) -> tuple[str, str] | None` (page id and outcome `read` | `unrecognized` | `retry` | `failed`, None when the queue is empty); `requeue_stale_reads(connection) -> int`; worker `run_scan_reader(ocr_url)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/scan/api/test_reader_integration.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/scan/api/test_reader_integration.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement `ocr_client.py`**

```python
# backend/modules/scan/api/ocr_client.py
"""The call to the OCR container (compose service `ocr`): one photo in, the cells it read out."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class OcrUnavailable(Exception):
    """The container did not answer with a reading: down, restarting, too slow, or broken."""


class OcrClient:
    def __init__(self, base_url: str, timeout: float = 180) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def read(self, image: bytes, form_hint: str | None) -> dict:
        query = f"?{urllib.parse.urlencode({'form_hint': form_hint})}" if form_hint else ""
        request = urllib.request.Request(
            f"{self._base_url}/read{query}", data=image, method="POST", headers={"Content-Type": "application/octet-stream"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as error:
            raise OcrUnavailable(str(getattr(error, "reason", error))) from error
```

- [ ] **Step 4: Implement `reader.py`**

```python
# backend/modules/scan/api/reader.py
"""One step of the reading queue, run by the worker.

A page is taken with FOR UPDATE SKIP LOCKED and marked `reading` in its own committed
transaction before the (slow) OCR call, so two workers never read the same photo and
a crash mid-read leaves a page the next start puts back in the queue. A failed call
puts the page back; its third failed pickup marks it `failed` for the user to retry.
These are system transitions, not a user's action, so they are not audited.
"""
from __future__ import annotations

from typing import Callable

import psycopg
from psycopg.types.json import Jsonb

MAX_ATTEMPTS = 3


def requeue_stale_reads(connection: psycopg.Connection) -> int:
    count = connection.execute("UPDATE scan.scan_pages SET status = 'queued' WHERE status = 'reading'").rowcount
    connection.commit()
    return count


def read_next_page(connection: psycopg.Connection, read: Callable[[bytes, str | None], dict]) -> tuple[str, str] | None:
    row = connection.execute(
        "SELECT id, image, form_hint FROM scan.scan_pages WHERE status = 'queued' "
        "ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED"
    ).fetchone()
    if row is None:
        connection.rollback()
        return None
    page_id, image, form_hint = row
    connection.execute("UPDATE scan.scan_pages SET status = 'reading', attempts = attempts + 1 WHERE id = %s", (page_id,))
    connection.commit()
    try:
        result = read(bytes(image), form_hint)
    except Exception as error:  # the container's failure is the page's retry, never the loop's end
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
```

- [ ] **Step 5: Start the reader in the worker**

In `backend/worker/main.py` add the imports

```python
from modules.scan.api.ocr_client import OcrClient
from modules.scan.api.reader import read_next_page, requeue_stale_reads
```

the constants

```python
SCAN_READER_IDLE_SECONDS = 2
SCAN_READER_RETRY_SECONDS = 15
```

the loop (after `run_replenishment`)

```python
def run_scan_reader(ocr_url: str) -> None:
    """Has the OCR container read the queued photos, one at a time, in their own thread
    so a slow page never holds up the event consumers."""
    client = OcrClient(ocr_url)
    print("Scan reader started", flush=True)
    with get_connection() as db_connection:
        requeued = requeue_stale_reads(db_connection)
    if requeued:
        print(f"Scan reader: put {requeued} interrupted page(s) back in the queue", flush=True)
    while True:
        try:
            with get_connection() as db_connection:
                step = read_next_page(db_connection, client.read)
        except Exception as error:  # retried next tick, never kills the thread
            print(f"Scan reader failed: {error}", flush=True)
            step = ("", "retry")
        if step is None:
            time.sleep(SCAN_READER_IDLE_SECONDS)
        elif step[1] in ("retry", "failed"):
            time.sleep(SCAN_READER_RETRY_SECONDS)
```

and in `run()`, before `event_consumers.consume_forever(rabbitmq_url)`:

```python
    ocr_url = os.environ.get("OCR_URL")
    if ocr_url:
        threading.Thread(target=run_scan_reader, args=(ocr_url,), daemon=True).start()
    else:
        print("OCR_URL not set: scanned photos stay queued until it is", flush=True)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/scan -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/scan/api/ocr_client.py backend/modules/scan/api/reader.py backend/modules/scan/api/test_reader_integration.py backend/worker/main.py
git commit -m "feat(scan): read queued photos through the OCR container in the worker"
```

### Task 14: OCR probe on the example photos (decision gate, throwaway)

Before building the container, find out what RapidOCR really reads on these fiches on a CPU. Nothing from this task is kept except `ocr/README.md` (findings + pinned versions).

**Files:**
- Create: `ocr/README.md`
- Scratch only (never committed): a venv and a script in the session scratchpad; the photos in a local folder outside the repo.

- [ ] **Step 1: Put the example photos outside the repo**

Copy the client's three photos (the conversation's `images/1.png` conditionnement, `2.png` fabrication, `3.png` bobines) to `%USERPROFILE%\sonalim-ocr-fixtures\` as `conditionnement.png`, `fabrication.png`, `bobines.png`. Add the blank fiches there too when the user brings them (`blank_fabrication.png`, …). This folder is `OCR_FIXTURES_DIR` from now on. **Never copy it into the repo** (workers' names).

- [ ] **Step 2: Install RapidOCR in a scratch venv**

```bash
python -m venv "$SCRATCH/ocr-probe"
"$SCRATCH/ocr-probe/Scripts/python" -m pip install rapidocr onnxruntime opencv-python-headless numpy
"$SCRATCH/ocr-probe/Scripts/python" -m pip freeze > "$SCRATCH/ocr-probe/freeze.txt"
```

(`$SCRATCH` = the session scratchpad directory.)

- [ ] **Step 3: Dump every text box at each rotation**

```python
# $SCRATCH/probe.py  -- run: "$SCRATCH/ocr-probe/Scripts/python" "$SCRATCH/probe.py"
import json, os, sys, time
import cv2
from rapidocr import RapidOCR

folder = os.path.expandvars(r"%USERPROFILE%\sonalim-ocr-fixtures")
engine = RapidOCR(params={"Global.text_score": 0.0})
rotations = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
for name in ("fabrication", "conditionnement", "bobines"):
    image = cv2.imread(os.path.join(folder, f"{name}.png"))
    for degrees, code in rotations.items():
        rotated = image if code is None else cv2.rotate(image, code)
        started = time.time()
        result = engine(rotated)
        boxes = [] if result.boxes is None else [
            {"text": t, "score": round(float(s), 3), "box": [float(v) for v in b.reshape(-1)]}
            for b, t, s in zip(result.boxes, result.txts, result.scores)
        ]
        print(name, degrees, f"{time.time() - started:.1f}s", len(boxes), "boxes", file=sys.stderr)
        with open(os.path.join(os.environ["SCRATCH"], f"probe_{name}_{degrees}.json"), "w", encoding="utf-8") as out:
            json.dump(boxes, out, ensure_ascii=False, indent=1)
```

If the installed `rapidocr` exposes a different call/result API, adapt the script (and later only `ocr/app/engine.py`) — record the API actually used.

- [ ] **Step 4: Judge the result against these questions and write `ocr/README.md`**

For each photo at its upright rotation: (1) is the printed title read? (2) are the grey band titles and column headers read (list which)? (3) which handwritten values come out right (lot, semoule tonnes, % eau, humidité, waste kg, stop times, silo %)? (4) seconds per photo? (5) does the rotation with the most title/band hits equal the upright one for the sideways bobines photo? Try also `params={"Det.limit_side_len": 1600}` (or the version's equivalent) if small handwriting is missed, and note the time cost.

`ocr/README.md` content: the pinned versions from `freeze.txt` (rapidocr, onnxruntime, opencv-python-headless, numpy), the call API, the detection parameters chosen, the answers to (1)–(5), and how to rerun the probe.

- [ ] **Step 5: Decision gate — stop and report to the user if either is true**

- the printed titles/bands are not read on the upright photos (the anchor approach cannot locate blocks), or
- fewer than half of the handwritten numbers in question (3) come out right even at the larger detection size.

Otherwise continue with Task 15. Report the answers to (1)–(5) to the user either way.

- [ ] **Step 6: Commit**

```bash
git add ocr/README.md
git commit -m "docs(ocr): probe results for RapidOCR on the example fiches"
```

---

### Task 15: Locating a fiche's blocks and cells (pure logic + templates)

**Files:**
- Create: `ocr/app/__init__.py` (empty), `ocr/app/templates.py`, `ocr/app/locate.py`, `ocr/templates/fabrication.json`, `ocr/templates/conditionnement.json`, `ocr/templates/bobines.json`, `ocr/tests/__init__.py` (empty), `ocr/tests/test_locate.py`, `ocr/requirements-dev.txt`

**Interfaces:**
- Produces: `templates.Column(key, headers, x)`, `templates.Block(key, anchors, columns, layout="table", exclude=(), x_range=(0.0, 1.0))`, `templates.HeaderField(key, anchors, kind, exclude=())`, `templates.Template(form_type, titles, markers, header, blocks, boundaries=())`, `templates.load_templates(directory) -> list[Template]`; `locate.TextBox(text, score, x0, y0, x1, y1)`, `locate.normalize`, `locate.has_phrase(norm_text, phrase)`, `locate.anchor_hits(boxes, templates) -> int`, `locate.classify(boxes, templates, hint=None) -> tuple[Template | None, float]`, `locate.extract(template, boxes, width, height) -> dict` (`{"header": {key: cell}, "blocks": [{"key", "found", "rows": [{"cells": {key: cell}}]}], "checkbox_regions": {key: (x0, y0, x1, y1)}}`, cell = `{"text", "confidence", "box": [x0, y0, x1, y1]}` in pixels).

- [ ] **Step 1: Write the failing tests (synthetic boxes, no image, no model)**

```python
# ocr/tests/test_locate.py
from pathlib import Path

from app.locate import TextBox, anchor_hits, classify, extract
from app.templates import load_templates

TEMPLATES = load_templates(Path(__file__).resolve().parents[1] / "templates")


def box(text, x0, y0, x1, y1, score=0.9):
    return TextBox(text, score, x0, y0, x1, y1)


# A conditionnement fiche, upright, 1000 px wide.
CONDITIONNEMENT = [
    box("FICHE CONDITIONNEMENT PAR EQUIPE", 250, 40, 750, 70),
    box("Date de création : 17 Juillet 2023", 800, 20, 990, 35),
    box("Ligne:", 20, 100, 70, 120), box("PC", 80, 100, 100, 120), box("PL", 160, 100, 180, 120),
    box("Date :", 300, 100, 350, 120), box("07/09/26", 360, 100, 450, 120),
    box("Equipe :", 600, 100, 660, 120), box("D 07H à 14H", 670, 100, 800, 120),
    box("Machiniste", 20, 140, 100, 160), box("Machiniste Trois", 110, 140, 260, 160),
    box("Aide machiniste:", 330, 140, 450, 160), box("Aide Quatre", 460, 140, 560, 160),
    box("CONDITIONNEMENT", 400, 300, 600, 320),
    box("Format", 20, 330, 80, 345), box("N° lot", 100, 330, 160, 345), box("Date de fab", 180, 330, 260, 345),
    box("Type de conditi", 280, 330, 360, 345), box("Type film", 380, 330, 440, 345), box("Qté du cartons", 460, 330, 540, 345),
    box("Qté bobine", 560, 330, 620, 345), box("Qté scotch", 640, 330, 700, 345), box("Qté ruban", 720, 330, 780, 345),
    box("Vermicelles", 20, 360, 90, 380), box("D6249SNL", 100, 360, 170, 380), box("07-0926", 180, 360, 250, 380),
    box("(500g)", 290, 360, 340, 380), box("Active", 385, 360, 430, 380),
    box("VERIFICATION D'ETAT DE PAQUET", 350, 420, 650, 440),
    box("DECHET PATES OU INTRANTS", 380, 600, 620, 620),
    box("Heure", 20, 630, 60, 645), box("Type de déchet", 100, 630, 200, 645), box("Qté (kg)", 260, 630, 320, 645), box("Cause", 400, 630, 460, 645),
    box("07H14", 20, 660, 60, 680), box("Produits finis", 100, 660, 200, 680), box("02,46kg", 260, 660, 320, 680),
    box("Nettoyage de la Machine", 400, 660, 560, 680),
    box("Films Déchet C1", 100, 692, 200, 712), box("0,35Kg", 260, 692, 320, 712), box("Réglage de Machine", 400, 692, 540, 712),
    box("ARRET MACHINE", 420, 800, 580, 820),
]


def _block(result, key):
    return next(b for b in result["blocks"] if b["key"] == key)


def test_the_form_is_classified_by_its_title_and_markers():
    template, confidence = classify(CONDITIONNEMENT, TEMPLATES)
    assert template.form_type == "conditionnement" and confidence > 0.5
    assert classify([box("nothing printed", 0, 0, 10, 10)], TEMPLATES) == (None, 0.0)
    assert classify([], TEMPLATES, hint="bobines")[0].form_type == "bobines"


def test_anchor_hits_count_printed_landmarks():
    assert anchor_hits(CONDITIONNEMENT, TEMPLATES) >= 4
    assert anchor_hits([box("D6249SNL", 0, 0, 10, 10)], TEMPLATES) == 0


def test_header_fields_are_read_right_of_their_label():
    template, _ = classify(CONDITIONNEMENT, TEMPLATES)
    header = extract(template, CONDITIONNEMENT, 1000, 900)["header"]
    assert header["date"]["text"] == "07/09/26"
    assert header["team_hours"]["text"] == "D 07H à 14H"
    assert header["machiniste"]["text"] == "Machiniste Trois"
    assert header["aide_machiniste"]["text"] == "Aide Quatre"


def test_checkbox_regions_sit_right_of_pc_and_pl():
    template, _ = classify(CONDITIONNEMENT, TEMPLATES)
    regions = extract(template, CONDITIONNEMENT, 1000, 900)["checkbox_regions"]
    assert regions["line_pc"][0] == 100 and regions["line_pl"][0] == 180


def test_table_rows_land_in_their_columns():
    template, _ = classify(CONDITIONNEMENT, TEMPLATES)
    result = extract(template, CONDITIONNEMENT, 1000, 900)
    [packing] = _block(result, "packing")["rows"]
    cells = {k: v["text"] for k, v in packing["cells"].items()}
    assert cells == {"format": "Vermicelles", "lot": "D6249SNL", "fab_date": "07-0926", "pack_type": "(500g)", "film_type": "Active"}
    waste = _block(result, "waste")["rows"]
    assert [{k: v["text"] for k, v in r["cells"].items()} for r in waste] == [
        {"time": "07H14", "type": "Produits finis", "quantity": "02,46kg", "cause": "Nettoyage de la Machine"},
        {"type": "Films Déchet C1", "quantity": "0,35Kg", "cause": "Réglage de Machine"},
    ]
    assert _block(result, "packet_checks") == {"key": "packet_checks", "found": True, "rows": []}
    assert _block(result, "silo_start")["found"] is False


def test_a_partial_photo_yields_only_its_blocks():
    partial = [b for b in CONDITIONNEMENT if b.y0 >= 590]
    template, _ = classify(partial, TEMPLATES)
    assert template.form_type == "conditionnement"
    result = extract(template, partial, 1000, 900)
    assert len(_block(result, "waste")["rows"]) == 2 and _block(result, "packing")["found"] is False
```

`ocr/requirements-dev.txt`:

```
pytest==8.4.1
```

- [ ] **Step 2: Run to verify failure**

Run (from `ocr/`, with a venv holding `requirements-dev.txt`): `python -m pytest tests/test_locate.py -q`
Expected: FAIL — `ModuleNotFoundError: app.locate`.

- [ ] **Step 3: Implement `templates.py`**

```python
# ocr/app/templates.py
"""A fiche's printed layout, as data: its title, the landmarks only it has, the header
labels, and each block's band title and column headers (left to right).

`x` is a column's nominal centre as a fraction of the block's width, used only for a
column whose printed header was not read. Calibrate against a blank fiche.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Column:
    key: str
    headers: tuple[str, ...]
    x: float = 0.5


@dataclass(frozen=True)
class Block:
    key: str
    anchors: tuple[str, ...]
    columns: tuple[Column, ...]
    layout: str = "table"  # table | labels
    exclude: tuple[str, ...] = ()
    x_range: tuple[float, float] = (0.0, 1.0)


@dataclass(frozen=True)
class HeaderField:
    key: str
    anchors: tuple[str, ...]
    kind: str = "right_of"  # right_of | checkbox
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Template:
    form_type: str
    titles: tuple[str, ...]
    markers: tuple[str, ...]
    header: tuple[HeaderField, ...]
    blocks: tuple[Block, ...]
    boundaries: tuple[str, ...] = ()


def _template(data: dict) -> Template:
    return Template(
        form_type=data["form_type"],
        titles=tuple(data["titles"]),
        markers=tuple(data.get("markers", ())),
        header=tuple(
            HeaderField(f["key"], tuple(f["anchors"]), f.get("kind", "right_of"), tuple(f.get("exclude", ())))
            for f in data.get("header", ())
        ),
        blocks=tuple(
            Block(
                key=b["key"],
                anchors=tuple(b["anchors"]),
                columns=tuple(Column(c["key"], tuple(c["headers"]), float(c.get("x", 0.5))) for c in b["columns"]),
                layout=b.get("layout", "table"),
                exclude=tuple(b.get("exclude", ())),
                x_range=tuple(b.get("x_range", (0.0, 1.0))),
            )
            for b in data["blocks"]
        ),
        boundaries=tuple(data.get("boundaries", ())),
    )


def load_templates(directory: Path) -> list[Template]:
    return [_template(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(Path(directory).glob("*.json"))]
```

- [ ] **Step 4: Implement `locate.py`**

```python
# ocr/app/locate.py
"""Finding a fiche's printed landmarks among the OCR's text boxes, and the handwriting in each cell.

Pure: text boxes in, cells out. A fiche is a fixed printed form, so its title, band
titles and column headers are printed text the engine reads reliably; they locate each
block and its columns, and every handwritten box goes to the cell it falls in. Each
block is located on its own, which is what lets a partial photo yield the blocks it holds.
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass

from app.templates import Block, Template


@dataclass(frozen=True)
class TextBox:
    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)

    @property
    def norm(self) -> str:
        return normalize(self.text)


def normalize(text: str | None) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def has_phrase(norm_text: str, phrase: str) -> bool:
    wanted = normalize(phrase)
    return bool(wanted) and re.search(rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])", norm_text) is not None


def _find(boxes, phrases, exclude=()) -> list[TextBox]:
    return [
        b for b in boxes
        if any(has_phrase(b.norm, p) for p in phrases) and not any(has_phrase(b.norm, e) for e in exclude)
    ]


def anchor_hits(boxes: list[TextBox], templates: list[Template]) -> int:
    """How many boxes read as a printed landmark of some fiche: the orientation score."""
    phrases = {p for t in templates for p in (*t.titles, *t.markers, *(a for b in t.blocks for a in b.anchors))}
    return sum(1 for b in boxes if any(has_phrase(b.norm, p) for p in phrases))


def classify(boxes: list[TextBox], templates: list[Template], hint: str | None = None) -> tuple[Template | None, float]:
    if hint:
        chosen = next((t for t in templates if t.form_type == hint), None)
        return (chosen, 1.0) if chosen else (None, 0.0)
    best, best_score = None, 0
    for template in templates:
        score = 3 * bool(_find(boxes, template.titles)) + sum(1 for m in template.markers if _find(boxes, (m,)))
        if score > best_score:
            best, best_score = template, score
    if best is None:
        return None, 0.0
    return best, round(best_score / (3 + len(best.markers)), 2)


def _same_line(a: TextBox, b: TextBox) -> bool:
    return min(a.y1, b.y1) - max(a.y0, b.y0) > 0.5 * min(a.height, b.height)


def _cell(boxes: list[TextBox]) -> dict:
    ordered = sorted(boxes, key=lambda b: b.x0)
    return {
        "text": " ".join(b.text.strip() for b in ordered if b.text.strip()),
        "confidence": round(min(b.score for b in ordered), 3),
        "box": [min(b.x0 for b in ordered), min(b.y0 for b in ordered), max(b.x1 for b in ordered), max(b.y1 for b in ordered)],
    }


def _inline_value(anchor: TextBox) -> str:
    """"Date : 07/09/26" read as one box: what follows the label."""
    text = anchor.text
    if ":" in text:
        return text.split(":", 1)[1].strip()
    return ""


def _extract_header(template: Template, boxes: list[TextBox]) -> tuple[dict, dict]:
    anchors: dict[str, TextBox | None] = {}
    for field in template.header:
        hits = _find(boxes, field.anchors, field.exclude)
        anchors[field.key] = min(hits, key=lambda b: (b.y0, b.x0)) if hits else None
    labels = [b for b in anchors.values() if b is not None] + _find(boxes, template.titles)
    cells: dict[str, dict] = {}
    regions: dict[str, tuple[float, float, float, float]] = {}
    for field in template.header:
        anchor = anchors[field.key]
        if anchor is None:
            continue
        if field.kind == "checkbox":
            regions[field.key] = (anchor.x1, anchor.y0, anchor.x1 + 1.6 * anchor.height, anchor.y1)
            continue
        stop = min((b.x0 for b in labels if b is not anchor and b.x0 > anchor.x1 and _same_line(b, anchor)), default=float("inf"))
        values = [b for b in boxes if b not in labels and _same_line(b, anchor) and anchor.x1 <= b.cx < stop]
        inline = _inline_value(anchor)
        parts = ([TextBox(inline, anchor.score, anchor.x0, anchor.y0, anchor.x1, anchor.y1)] if inline else []) + values
        if parts:
            cells[field.key] = _cell(parts)
    return cells, regions


def _span(block: Block, left: float, right: float) -> tuple[float, float]:
    width = right - left
    return left + block.x_range[0] * width, left + block.x_range[1] * width


def _bounds(template: Template, boxes: list[TextBox], height: float, left: float, right: float) -> dict[str, tuple[TextBox, float]]:
    found: dict[str, TextBox] = {}
    for block in template.blocks:
        lo, hi = _span(block, left, right)
        hits = [b for b in _find(boxes, block.anchors, block.exclude) if lo <= b.cx <= hi]
        if hits:
            found[block.key] = min(hits, key=lambda b: b.y0)
    stops = list(found.values()) + _find(boxes, template.boundaries)
    bounds = {}
    for block in template.blocks:
        if block.key not in found:
            continue
        anchor = found[block.key]
        lo, hi = _span(block, left, right)
        below = [s.y0 for s in stops if s is not anchor and s.y0 > anchor.cy and lo <= s.cx <= hi]
        bounds[block.key] = (anchor, min(below, default=height))
    return bounds


def _rows(boxes: list[TextBox]) -> list[list[TextBox]]:
    if not boxes:
        return []
    typical = statistics.median(b.height for b in boxes)
    rows: list[list[TextBox]] = []
    current: list[TextBox] = []
    for box in sorted(boxes, key=lambda b: b.cy):
        if current and box.cy - statistics.fmean(b.cy for b in current) > typical / 2:
            rows.append(current)
            current = []
        current.append(box)
    rows.append(current)
    return rows


def _centers(block: Block, hits: dict[str, TextBox], lo: float, hi: float) -> dict[str, float]:
    known = [(c.x, hits[c.key].cx) for c in block.columns if c.key in hits]
    if len(known) >= 2 and known[-1][0] != known[0][0]:
        (f0, p0), (f1, p1) = known[0], known[-1]
        scale = (p1 - p0) / (f1 - f0)
        offset = p0 - scale * f0
    elif known:
        scale = hi - lo
        offset = known[0][1] - scale * known[0][0]
    else:
        scale, offset = hi - lo, lo
    return {c.key: hits[c.key].cx if c.key in hits else offset + scale * c.x for c in block.columns}


def _table(block: Block, anchor: TextBox, bottom: float, boxes: list[TextBox], lo: float, hi: float) -> list[dict]:
    region = [b for b in boxes if anchor.y0 <= b.cy < bottom and lo <= b.cx <= hi and b is not anchor]
    hits: dict[str, TextBox] = {}
    previous = lo - 1
    for column in block.columns:
        candidates = sorted((b for b in _find(region, column.headers) if b.cx > previous and b not in hits.values()), key=lambda b: b.cx)
        if candidates:
            hits[column.key] = candidates[0]
            previous = candidates[0].cx
    printed = set(hits.values())
    header_bottom = max((b.y1 for b in printed), default=anchor.y1)
    centers = sorted(_centers(block, hits, lo, hi).items(), key=lambda kv: kv[1])
    data = [b for b in region if b not in printed and b.cy > header_bottom]
    rows = []
    for row in _rows(data):
        cells: dict[str, list[TextBox]] = {}
        for box in row:
            key = min(centers, key=lambda kv: abs(kv[1] - box.cx))[0]
            cells.setdefault(key, []).append(box)
        rows.append({key: _cell(parts) for key, parts in cells.items()})
    return rows


def _labels(block: Block, anchor: TextBox, bottom: float, boxes: list[TextBox], lo: float, hi: float) -> list[dict]:
    region = [b for b in boxes if anchor.y1 <= b.cy < bottom and lo <= b.cx <= hi]
    printed = _find(region, [h for c in block.columns for h in c.headers])
    row = {}
    for column in block.columns:
        hits = _find(region, column.headers)
        if not hits:
            continue
        label = min(hits, key=lambda b: b.y0)
        values = [b for b in region if b not in printed and _same_line(b, label) and b.cx > label.x1]
        if values:
            row[column.key] = _cell(values)
    return [row] if row else []


def extract(template: Template, boxes: list[TextBox], width: float, height: float) -> dict:
    left = min((b.x0 for b in boxes), default=0.0)
    right = max((b.x1 for b in boxes), default=float(width))
    header, regions = _extract_header(template, boxes)
    bounds = _bounds(template, boxes, height, left, right)
    blocks = []
    for block in template.blocks:
        if block.key not in bounds:
            blocks.append({"key": block.key, "found": False, "rows": []})
            continue
        anchor, bottom = bounds[block.key]
        lo, hi = _span(block, left, right)
        rows = (_labels if block.layout == "labels" else _table)(block, anchor, bottom, boxes, lo, hi)
        blocks.append({"key": block.key, "found": True, "rows": [{"cells": r} for r in rows]})
    return {"header": header, "blocks": blocks, "checkbox_regions": regions}
```

- [ ] **Step 5: Write the templates**

The column `x` values are first estimates from the example photos; Task 16 Step 6 calibrates them.

`ocr/templates/conditionnement.json`:

```json
{
  "form_type": "conditionnement",
  "titles": ["fiche conditionnement par equipe", "fiche conditionnement"],
  "markers": ["verification d etat de paquet", "dechet pates ou intrants", "arret machine"],
  "boundaries": ["elabore par", "valide par"],
  "header": [
    {"key": "date", "anchors": ["date"], "exclude": ["creation", "mise a jour", "fab"]},
    {"key": "team_hours", "anchors": ["equipe"], "exclude": ["fiche"]},
    {"key": "line_pc", "anchors": ["pc"], "kind": "checkbox"},
    {"key": "line_pl", "anchors": ["pl"], "kind": "checkbox"},
    {"key": "machiniste", "anchors": ["machiniste"], "exclude": ["aide"]},
    {"key": "aide_machiniste", "anchors": ["aide machiniste"]}
  ],
  "blocks": [
    {"key": "silo_start", "anchors": ["debut production"], "columns": [
      {"key": "format", "headers": ["format"], "x": 0.12}, {"key": "lot", "headers": ["n du lot", "lot"], "x": 0.37},
      {"key": "level", "headers": ["quantite"], "x": 0.62}, {"key": "line_state", "headers": ["etat de la ligne"], "x": 0.87}]},
    {"key": "silo_end", "anchors": ["fin production"], "columns": [
      {"key": "format", "headers": ["format"], "x": 0.12}, {"key": "lot", "headers": ["n du lot", "lot"], "x": 0.37},
      {"key": "level", "headers": ["quantite"], "x": 0.62}, {"key": "line_state", "headers": ["etat de la ligne"], "x": 0.87}]},
    {"key": "packing", "anchors": ["conditionnement"], "exclude": ["fiche"], "columns": [
      {"key": "format", "headers": ["format"], "x": 0.06}, {"key": "lot", "headers": ["n lot", "lot"], "x": 0.17},
      {"key": "fab_date", "headers": ["date de fab"], "x": 0.29}, {"key": "pack_type", "headers": ["type de conditi", "type de condit"], "x": 0.41},
      {"key": "film_type", "headers": ["type film"], "x": 0.53}, {"key": "cartons", "headers": ["qte du cartons", "cartons"], "x": 0.64},
      {"key": "bobine", "headers": ["qte bobine", "bobine"], "x": 0.75}, {"key": "scotch", "headers": ["qte scotch", "scotch"], "x": 0.85},
      {"key": "ruban", "headers": ["qte ruban", "ruban"], "x": 0.95}]},
    {"key": "packet_checks", "anchors": ["verification d etat de paquet", "etat de paquet"], "columns": [
      {"key": "time", "headers": ["heure"], "x": 0.06}, {"key": "film", "headers": ["film"], "x": 0.19},
      {"key": "weight", "headers": ["pds paquet"], "x": 0.32}, {"key": "long_weld", "headers": ["soudure longi", "soudure long"], "x": 0.45},
      {"key": "vert_weld", "headers": ["soudure vert"], "x": 0.58}, {"key": "date_print", "headers": ["imp date"], "x": 0.71},
      {"key": "observation", "headers": ["observation"], "x": 0.88}]},
    {"key": "waste", "anchors": ["dechet pates ou intrants", "dechet pates"], "columns": [
      {"key": "time", "headers": ["heure"], "x": 0.05}, {"key": "type", "headers": ["type de dechet"], "x": 0.18},
      {"key": "quantity", "headers": ["qte kg", "qte"], "x": 0.33}, {"key": "cause", "headers": ["cause"], "x": 0.7}]},
    {"key": "stops", "anchors": ["arret machine"], "columns": [
      {"key": "panne", "headers": ["panne"], "x": 0.2}, {"key": "start", "headers": ["heure d"], "x": 0.43},
      {"key": "end", "headers": ["heure f"], "x": 0.53}, {"key": "action", "headers": ["action corrective"], "x": 0.8}]}
  ]
}
```

`ocr/templates/fabrication.json`:

```json
{
  "form_type": "fabrication",
  "titles": ["fiche fabrication par equipe", "fiche fabrication"],
  "markers": ["pates non conforme", "lavage des moules", "presence personnel", "arret de la production"],
  "boundaries": ["pates non conforme", "etat de silo", "elabore par", "valide par"],
  "header": [
    {"key": "date", "anchors": ["date"], "exclude": ["creation", "mise a jour"]},
    {"key": "team_hours", "anchors": ["equipe"], "exclude": ["fiche"]},
    {"key": "line_pc", "anchors": ["pc"], "kind": "checkbox"},
    {"key": "line_pl", "anchors": ["pl"], "kind": "checkbox"},
    {"key": "conducteur", "anchors": ["conducteur ligne", "conducteur"]},
    {"key": "agent_fabrication", "anchors": ["agent de fabrication"]}
  ],
  "blocks": [
    {"key": "production", "anchors": ["production"], "exclude": ["arret de la production", "debut production", "fin production", "demarrage", "fiche"], "columns": [
      {"key": "lot", "headers": ["n lot"], "x": 0.03}, {"key": "product", "headers": ["produit"], "x": 0.1},
      {"key": "start", "headers": ["hd prod"], "x": 0.16}, {"key": "end", "headers": ["hf prod"], "x": 0.21},
      {"key": "sem_origin", "headers": ["origine"], "x": 0.29}, {"key": "sem_lot", "headers": ["lot"], "x": 0.38},
      {"key": "sem_bags", "headers": ["qte sac"], "x": 0.45}, {"key": "sem_tonnes", "headers": ["qte t"], "x": 0.5},
      {"key": "broy_lot", "headers": ["lot"], "x": 0.62}, {"key": "broy_percent", "headers": ["%"], "x": 0.72},
      {"key": "broy_bags", "headers": ["qte sac"], "x": 0.78}, {"key": "broy_kg", "headers": ["qte kg"], "x": 0.84},
      {"key": "water", "headers": ["eau"], "x": 0.91}, {"key": "humidity", "headers": ["humidite"], "x": 0.97}]},
    {"key": "waste_petrin", "anchors": ["dechet petrin"], "x_range": [0.0, 0.66], "columns": [
      {"key": "time", "headers": ["heure"], "x": 0.08}, {"key": "format", "headers": ["format"], "x": 0.22},
      {"key": "lot", "headers": ["n lot", "lot"], "x": 0.38}, {"key": "quantity", "headers": ["qte kg", "qte"], "x": 0.52},
      {"key": "cause", "headers": ["cause"], "x": 0.8}]},
    {"key": "waste_finished", "anchors": ["produit fini"], "x_range": [0.0, 0.66], "columns": [
      {"key": "time", "headers": ["heure"], "x": 0.08}, {"key": "format", "headers": ["format"], "x": 0.22},
      {"key": "lot", "headers": ["n lot", "lot"], "x": 0.38}, {"key": "quantity", "headers": ["qte kg", "qte"], "x": 0.52},
      {"key": "cause", "headers": ["cause"], "x": 0.8}]},
    {"key": "mold_washes", "anchors": ["lavage des moules"], "x_range": [0.66, 1.0], "columns": [
      {"key": "mold", "headers": ["n moule"], "x": 0.2}, {"key": "time", "headers": ["heure"], "x": 0.5},
      {"key": "state", "headers": ["etat"], "x": 0.83}]},
    {"key": "staffing", "anchors": ["presence personnel"], "layout": "labels", "x_range": [0.66, 1.0], "columns": [
      {"key": "control_room", "headers": ["salle de controle"]}, {"key": "petrin", "headers": ["petrin"]},
      {"key": "semoule", "headers": ["semoule"]}, {"key": "broyage", "headers": ["broyage"]}]},
    {"key": "stops", "anchors": ["arret de la production"], "columns": [
      {"key": "panne", "headers": ["panne"], "x": 0.25}, {"key": "start", "headers": ["heure d"], "x": 0.52},
      {"key": "end", "headers": ["heure f"], "x": 0.6}, {"key": "action", "headers": ["action corrective"], "x": 0.83}]},
    {"key": "silo_start", "anchors": ["debut production"], "columns": [
      {"key": "format", "headers": ["format"], "x": 0.12}, {"key": "lot", "headers": ["n du lot", "lot"], "x": 0.37},
      {"key": "level", "headers": ["quantite"], "x": 0.62}, {"key": "line_state", "headers": ["etat de la ligne"], "x": 0.87}]},
    {"key": "silo_end", "anchors": ["fin production"], "columns": [
      {"key": "format", "headers": ["format"], "x": 0.12}, {"key": "lot", "headers": ["n du lot", "lot"], "x": 0.37},
      {"key": "level", "headers": ["quantite"], "x": 0.62}, {"key": "line_state", "headers": ["etat de la ligne"], "x": 0.87}]}
  ]
}
```

`ocr/templates/bobines.json` (phase 1 only needs the type and the first row's date/team/hours):

```json
{
  "form_type": "bobines",
  "titles": ["fiche changement bobines", "changement bobines"],
  "markers": ["type bobine", "pds bobi", "pds cyl"],
  "boundaries": ["elabore par", "valide par"],
  "header": [],
  "blocks": [
    {"key": "changes", "anchors": ["type bobine"], "columns": [
      {"key": "date", "headers": ["date"], "x": 0.03}, {"key": "team", "headers": ["eq"], "x": 0.08},
      {"key": "hours", "headers": ["h travail"], "x": 0.13}, {"key": "machine", "headers": ["n machine"], "x": 0.19},
      {"key": "counter", "headers": ["d compteur"], "x": 0.25}, {"key": "format", "headers": ["format"], "x": 0.32},
      {"key": "reel_type", "headers": ["type bobine"], "x": 0.39}, {"key": "internal_lot", "headers": ["n lot int", "lot int"], "x": 0.45},
      {"key": "start", "headers": ["h d"], "x": 0.5}, {"key": "end", "headers": ["h f"], "x": 0.55},
      {"key": "reel_weight", "headers": ["pds bobi"], "x": 0.61}, {"key": "core_weight", "headers": ["pds cyl"], "x": 0.67},
      {"key": "waste", "headers": ["dechets"], "x": 0.73}, {"key": "remain_weight", "headers": ["poids"], "x": 0.78},
      {"key": "remain_conf", "headers": ["conf"], "x": 0.83}, {"key": "remain_nonconf", "headers": ["non conf"], "x": 0.88},
      {"key": "machinist", "headers": ["machiniste"], "x": 0.95}]}
  ]
}
```

- [ ] **Step 6: Run the tests**

Run (from `ocr/`): `python -m pytest tests/test_locate.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ocr/app/__init__.py ocr/app/templates.py ocr/app/locate.py ocr/templates ocr/tests/__init__.py ocr/tests/test_locate.py ocr/requirements-dev.txt
git commit -m "feat(ocr): locate a fiche's blocks and cells from its printed landmarks"
```

---

### Task 16: The OCR service, its image, and deployment

**Files:**
- Create: `ocr/app/engine.py`, `ocr/app/pipeline.py`, `ocr/app/main.py`, `ocr/requirements.txt`, `ocr/Dockerfile`, `ocr/.dockerignore`, `ocr/tests/test_photos.py`
- Modify: `compose.yaml`, `.github/workflows/deploy.yml`, `ocr/README.md`

**Interfaces:**
- Consumes: Task 15 (`load_templates`, `TextBox`, `anchor_hits`, `classify`, `extract`), Task 14 (pinned versions, engine API).
- Produces: `POST /read?form_hint=` (raw image body) → the OCR result contract; `GET /health`; `engine.Engine().detect(image) -> list[TextBox]`, `engine.ACCEPT_SCORE`; `pipeline.read(engine, templates, data, form_hint) -> dict`.

- [ ] **Step 1: Write the photo test (skips without fixtures)**

```python
# ocr/tests/test_photos.py
"""The example fiches end to end. The photos hold workers' names: they live outside the
repo, in OCR_FIXTURES_DIR, and this test skips when it is not set."""
import os
from pathlib import Path

import pytest

FIXTURES = os.environ.get("OCR_FIXTURES_DIR")
pytestmark = pytest.mark.skipif(not FIXTURES, reason="OCR_FIXTURES_DIR not set")

EXPECTED_TEXT = {
    "fabrication": [("production", "sem_tonnes", "3,25"), ("production", "water", "28,9"), ("production", "humidity", "9,83"),
                    ("stops", "start", "12h18"), ("silo_end", "level", "29")],
    "conditionnement": [("packing", "lot", "D6249SNL"), ("waste", "quantity", "75,28"), ("silo_end", "level", "29")],
}


@pytest.fixture(scope="module")
def reader():
    from app.engine import Engine
    from app.pipeline import TEMPLATES, read
    engine = Engine()
    return lambda data: read(engine, TEMPLATES, data, None)


@pytest.mark.parametrize("name", ["fabrication", "conditionnement", "bobines"])
def test_form_type_and_orientation(reader, name):
    result = reader((Path(FIXTURES) / f"{name}.png").read_bytes())
    assert result["form_type"] == name
    if name == "bobines":
        assert result["rotation"] in (90, 270)
    else:
        assert result["rotation"] == 0


@pytest.mark.parametrize("name", ["fabrication", "conditionnement"])
def test_key_cells_accuracy_report(reader, name, capsys):
    result = reader((Path(FIXTURES) / f"{name}.png").read_bytes())
    blocks = {b["key"]: b for b in result["blocks"]}
    hits = 0
    for block, cell, expected in EXPECTED_TEXT[name]:
        texts = [r["cells"].get(cell, {}).get("text", "") for r in blocks.get(block, {"rows": []})["rows"]]
        found = any(expected.replace(" ", "") in t.replace(" ", "") for t in texts)
        hits += found
        print(f"{name}.{block}.{cell}: expected {expected!r}, read {texts!r} -> {'OK' if found else 'MISS'}")
    print(f"{name}: {hits}/{len(EXPECTED_TEXT[name])} key cells read")
```

- [ ] **Step 2: Implement `engine.py`** (the only file that knows RapidOCR's API — adapt to what Task 14 recorded)

```python
# ocr/app/engine.py
"""RapidOCR behind one method: an image in, text boxes out (pixels of that image)."""
from __future__ import annotations

import numpy as np
from rapidocr import RapidOCR

from app.locate import TextBox

# RapidOCR's own default text_score: the engine's cut for accepting a reading. The engine
# runs with no cut so the backend sees weak readings too, and flags those under this one.
ACCEPT_SCORE = 0.5


class Engine:
    def __init__(self) -> None:
        # Detection size and other parameters: the values chosen in Task 14 (see README.md).
        self._ocr = RapidOCR(params={"Global.text_score": 0.0})

    def detect(self, image: np.ndarray) -> list[TextBox]:
        result = self._ocr(image)
        if result.boxes is None:
            return []
        boxes = []
        for points, text, score in zip(result.boxes, result.txts, result.scores):
            xs, ys = points[:, 0], points[:, 1]
            boxes.append(TextBox(str(text), float(score), float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())))
        return boxes
```

- [ ] **Step 3: Implement `pipeline.py`**

```python
# ocr/app/pipeline.py
"""One photo to the OCR result the backend reads: upright it, type it, locate its cells."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.engine import ACCEPT_SCORE
from app.locate import anchor_hits, classify, extract
from app.templates import load_templates

TEMPLATES = load_templates(Path(__file__).resolve().parents[1] / "templates")
_ROTATIONS = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
_ORIENTATION_SIDE = 960
# Enough printed landmarks read on the photo as taken: no need to try the other rotations.
_UPRIGHT_ENOUGH = 3


def _rotate(image: np.ndarray, degrees: int) -> np.ndarray:
    code = _ROTATIONS[degrees]
    return image if code is None else cv2.rotate(image, code)


def _shrink(image: np.ndarray) -> np.ndarray:
    scale = _ORIENTATION_SIDE / max(image.shape[:2])
    return image if scale >= 1 else cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _orientation(engine, image: np.ndarray) -> int:
    """The clockwise rotation under which the most printed landmarks are read."""
    small = _shrink(image)
    best, best_hits = 0, -1
    for degrees in _ROTATIONS:
        hits = anchor_hits(engine.detect(_rotate(small, degrees)), TEMPLATES)
        if hits > best_hits:
            best, best_hits = degrees, hits
        if degrees == 0 and hits >= _UPRIGHT_ENOUGH:
            break
    return best


def _ink(gray: np.ndarray, region: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = (int(round(v)) for v in region)
    crop = gray[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)]
    if crop.size == 0:
        return 0.0
    _, dark = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return float(dark.mean()) / 255


def _ticks(gray: np.ndarray, regions: dict) -> dict:
    """PC / PL: the box with more ink than the other is the one ticked."""
    if "line_pc" not in regions or "line_pl" not in regions:
        return {}
    pc, pl = _ink(gray, regions["line_pc"]), _ink(gray, regions["line_pl"])
    if pc == pl:
        return {}
    ticked = "line_pc" if pc > pl else "line_pl"
    confidence = round(abs(pc - pl) / max(pc + pl, 1e-6), 3)
    return {ticked: {"text": "x", "confidence": confidence, "box": list(regions[ticked])}}


def _fractions(cell: dict, width: int, height: int) -> dict:
    x0, y0, x1, y1 = cell["box"]
    return {**cell, "box": [round(x0 / width, 4), round(y0 / height, 4), round(x1 / width, 4), round(y1 / height, 4)]}


def _empty(rotation: int) -> dict:
    return {"form_type": None, "form_confidence": 0.0, "rotation": rotation, "accept_score": ACCEPT_SCORE, "header": {}, "blocks": []}


def read(engine, templates, data: bytes, form_hint: str | None) -> dict:
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return _empty(0)
    rotation = _orientation(engine, image)
    upright = _rotate(image, rotation)
    height, width = upright.shape[:2]
    boxes = engine.detect(upright)
    template, confidence = classify(boxes, templates, form_hint)
    if template is None:
        return _empty(rotation)
    found = extract(template, boxes, width, height)
    header = {**found["header"], **_ticks(cv2.cvtColor(upright, cv2.COLOR_BGR2GRAY), found["checkbox_regions"])}
    return {
        "form_type": template.form_type,
        "form_confidence": confidence,
        "rotation": rotation,
        "accept_score": ACCEPT_SCORE,
        "header": {key: _fractions(cell, width, height) for key, cell in header.items()},
        "blocks": [
            {**block, "rows": [{"cells": {k: _fractions(c, width, height) for k, c in row["cells"].items()}} for row in block["rows"]]}
            for block in found["blocks"]
        ],
    }
```

- [ ] **Step 4: Implement `main.py`**

```python
# ocr/app/main.py
"""The OCR container's HTTP face. No database, no tenant, no secret: an image in, cells out.

One photo is read at a time -- the server has 4 CPUs and the ERP beside it -- so
requests queue on a lock rather than running side by side.
"""
from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.engine import Engine
from app.pipeline import TEMPLATES, read

app = FastAPI(title="Sonalim OCR")
_lock = threading.Lock()
_engine: Engine | None = None


def _read(data: bytes, form_hint: str | None) -> dict:
    global _engine
    with _lock:
        if _engine is None:
            _engine = Engine()
        return read(_engine, TEMPLATES, data, form_hint)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/read")
async def read_photo(request: Request, form_hint: str | None = None) -> dict:
    data = await request.body()
    if not data:
        raise HTTPException(400, "empty body")
    return await run_in_threadpool(_read, data, form_hint)
```

- [ ] **Step 5: Image and dependencies**

`ocr/requirements.txt` — the exact versions from Task 14's `freeze.txt` for `rapidocr`, `onnxruntime`, `opencv-python-headless`, `numpy`, plus:

```
fastapi==0.116.1
uvicorn==0.35.0
```

`ocr/.dockerignore`:

```
tests
**/__pycache__
.venv
```

`ocr/Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
# Fetch the models while building, so the running container never needs the internet.
RUN python -c "from app.engine import Engine; Engine()"

EXPOSE 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
```

- [ ] **Step 6: Run the photo test and calibrate the templates**

Run (from `ocr/`, venv with `requirements.txt` + `requirements-dev.txt`):
`$env:OCR_FIXTURES_DIR="$env:USERPROFILE\sonalim-ocr-fixtures"; python -m pytest tests -q -s`
Expected: `test_locate.py` PASS; `test_form_type_and_orientation` PASS for the three photos; the accuracy report printed. Where a block is not found or cells land in the wrong column, adjust that template's `anchors`, `exclude`, `x_range` and column `x` (never the code for one photo) and rerun until the form types and orientations pass and the report is as good as the probe allowed. Record the final key-cell score in `ocr/README.md`. When the blank fiches arrive, repeat this step with them.

- [ ] **Step 7: Build and run the image locally**

```bash
docker build -t erpsonalim-ocr:local ocr
docker run --rm -d -p 8100:8100 --memory=1536m --cpus=2 --name ocr-local erpsonalim-ocr:local
curl -s -X POST --data-binary @"$USERPROFILE/sonalim-ocr-fixtures/conditionnement.png" -H "Content-Type: application/octet-stream" http://localhost:8100/read | python -c "import json,sys; r=json.load(sys.stdin); print(r['form_type'], r['rotation'], [b['key'] for b in r['blocks'] if b['found']])"
docker stop ocr-local
```

Expected: `conditionnement 0 [...found blocks...]`, within the memory cap (watch `docker stats`), and the time per photo noted in `ocr/README.md`.

- [ ] **Step 8: Wire it into compose and the deploy**

`compose.yaml` — new service (after `worker`):

```yaml
  ocr:
    image: ghcr.io/smarttoolsagro/erpsonalim-ocr:${IMAGE_TAG:-latest}
    restart: unless-stopped
    # CPU-only server shared with the ERP: one photo at a time, capped.
    mem_limit: 1536m
    cpus: 2
    environment:
      OMP_NUM_THREADS: "2"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8100/health')"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 30s
```

and in both `app` and `worker` `environment:` add `OCR_URL: ${OCR_URL:-http://ocr:8100}`.

`.github/workflows/deploy.yml` — add `OCR_IMAGE: ghcr.io/smarttoolsagro/erpsonalim-ocr` under `env:`, a build step after the frontend one:

```yaml
      - name: Build and push OCR image
        uses: docker/build-push-action@v6
        with:
          context: ./ocr
          push: true
          tags: |
            ${{ env.OCR_IMAGE }}:latest
            ${{ env.OCR_IMAGE }}:${{ github.sha }}
```

and in the deploy script replace the two compose lines with:

```
            docker compose pull app worker web ocr
            docker compose up -d app worker web ocr
```

- [ ] **Step 9: Commit**

```bash
git add ocr compose.yaml .github/workflows/deploy.yml
git commit -m "feat(ocr): RapidOCR service in its own capped container, built and deployed with the app"
```

### Task 17: Frontend API, image preparation and the screen's words

**Files:**
- Create: `frontend/src/features/scan/scanApi.ts`, `frontend/src/features/scan/imagePrep.ts`, `frontend/src/features/scan/scanText.ts`

**Interfaces:**
- Consumes: `apiFetch`, `apiErrorFromResponse`, `networkError` (`lib/api.ts`); shift types from `features/production/shift/shiftApi.ts`; `L`, `Label` from `shiftText.ts`.
- Produces: the types and calls below (used by every later frontend task), `prepareImage(file) -> Promise<PageUpload>`, and the label maps `S`, `REASONS`, `VERDICT_REASONS`, `FORM_LABELS`, `PAGE_STATUS`, `SESSION_STATUS`, `SECTION_STATUS`, `SHIFT_STATUS`, `KIND_LABELS`.

- [ ] **Step 1: Write `scanApi.ts`**

```ts
// frontend/src/features/scan/scanApi.ts
import { apiErrorFromResponse, apiFetch, networkError } from "../../lib/api";
import type { GridRow } from "../production/shift/ShiftGrid";
import type { Row, SectionKey, SectionPayload, SectionStatus, ShiftStatus } from "../production/shift/shiftApi";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type PageStatus = "queued" | "reading" | "read" | "unrecognized" | "failed";
export type FormType = "fabrication" | "conditionnement" | "bobines";
export type Verdict = "this_shift" | "other_shift" | "unknown";
export type SessionStatus = "open" | "applied" | "discarded";
export type Choice = "replace" | "keep";

export interface ReadHeader {
  date: string | null;
  team: string | null;
  hours_from: string | null;
  line: string | null;
}

export interface ScanPage {
  id: string;
  status: PageStatus;
  form_type: FormType | null;
  form_hint: FormType | null;
  rotation: number;
  width: number | null;
  height: number | null;
  attempts: number;
  error: string | null;
  created_at: string;
  read_at: string | null;
  attribution: { verdict: Verdict; reasons: string[]; read: ReadHeader } | null;
}

export interface ShiftSectionState {
  status: SectionStatus;
  revision: number;
  rows: number;
  fingerprint: string;
  payload: SectionPayload;
}

export interface ShiftState {
  id: string;
  status: ShiftStatus;
  team: string | null;
  conducteur: string | null;
  agent_fabrication: string | null;
  machiniste: string | null;
  aide_machiniste: string | null;
  default_lot_number: string | null;
  sections: Partial<Record<SectionKey, ShiftSectionState>>;
}

/** The review being edited: the working values, per-section choices, confirmed doubts, included pages. */
export interface ReviewValues {
  header: Record<string, string | null>;
  sections: Partial<Record<SectionKey, Record<string, GridRow[] | Row>>>;
}

export interface ReviewState {
  values?: ReviewValues;
  choices?: Partial<Record<SectionKey, Choice>>;
  confirmed?: string[];
  include_pages?: string[];
  touched?: SectionKey[];
}

export interface ScanSession {
  id: string;
  kind: "shift";
  work_center_id: string;
  report_date: string;
  shift: string;
  default_of_id: string | null;
  shift_report_id: string | null;
  status: SessionStatus;
  created_by: string;
  created_at: string;
  applied_at: string | null;
  page_count?: number;
}

export interface SessionDetail extends ScanSession {
  review_state: ReviewState;
  pages: ScanPage[];
  shift: ShiftState | null;
  window: { start: string; end: string } | null;
}

export interface FlagEntry {
  reason: string;
  detail: string | null;
}

export interface SourceEntry {
  page_id: string;
  box: [number, number, number, number] | null;
  text: string;
  confidence: number;
}

export interface SetAsideEntry {
  part: string;
  row: Row;
  reason: string;
}

export interface Proposal {
  header: Record<string, string | null>;
  sections: Partial<Record<SectionKey, SectionPayload>>;
  flags: Record<string, FlagEntry[]>;
  sources: Record<string, SourceEntry[]>;
  coded: Record<string, { kind: string; read_text: string; value: string | null }>;
  set_aside: Partial<Record<SectionKey, SetAsideEntry[]>>;
  pages: Record<string, { form_type: FormType | null; verdict: Verdict; reasons: string[]; importable: boolean; included: boolean }>;
}

export interface ProposalResponse {
  proposal: Proposal;
  shift: ShiftState | null;
  review_state: ReviewState;
}

export interface ApplyBody {
  header: Record<string, string | null>;
  sections: Partial<Record<SectionKey, Record<string, Row[] | Row>>>;
  fingerprints: Partial<Record<SectionKey, string | null>>;
}

export interface PageUpload {
  filename: string;
  content_type: string;
  width: number;
  height: number;
  data_base64: string;
}

export interface ShiftPage {
  id: string;
  session_id: string;
  form_type: FormType | null;
  rotation: number;
  width: number | null;
  height: number | null;
  created_at: string;
}

export interface Alias {
  id: string;
  kind: string;
  raw_text_normalized: string;
  raw_text_example: string;
  target_value: string;
  use_count: number;
  updated_at: string;
}

export type VocabularyOptions = Record<string, { value: string; label: string }[]>;

export const SCAN_QUERY_KEY = ["scan"] as const;
export const SCAN_SESSIONS_QUERY_KEY = ["scan", "sessions"] as const;
export const SCAN_ALIASES_QUERY_KEY = ["scan", "aliases"] as const;
export const scanSessionKey = (id: string) => ["scan", "session", id] as const;
export const scanProposalPrefix = (id: string) => ["scan", "proposal", id] as const;

const base = "/scan";

export function createSession(token: string, body: { work_center_id: string; report_date: string; shift: string; default_of_id: string | null }) {
  return apiFetch<ScanSession>(`${base}/sessions`, { method: "POST", body: { kind: "shift", ...body }, token });
}

export function listSessions(token: string) {
  return apiFetch<ScanSession[]>(`${base}/sessions`, { token });
}

export function getSession(token: string, id: string) {
  return apiFetch<SessionDetail>(`${base}/sessions/${id}`, { token });
}

export function uploadPages(token: string, id: string, files: PageUpload[]) {
  return apiFetch<ScanPage[]>(`${base}/sessions/${id}/pages`, { method: "POST", body: { files }, token });
}

export function deletePage(token: string, id: string, pageId: string) {
  return apiFetch<void>(`${base}/sessions/${id}/pages/${pageId}`, { method: "DELETE", token });
}

export function rereadPage(token: string, id: string, pageId: string, formHint: FormType | null) {
  return apiFetch<ScanPage>(`${base}/sessions/${id}/pages/${pageId}/reread`, { method: "POST", body: { form_hint: formHint }, token });
}

export function getProposal(token: string, id: string) {
  return apiFetch<ProposalResponse>(`${base}/sessions/${id}/proposal`, { token });
}

export function saveReview(token: string, id: string, reviewState: ReviewState) {
  return apiFetch<void>(`${base}/sessions/${id}/review`, { method: "PUT", body: { review_state: reviewState }, token });
}

export function applySession(token: string, id: string, body: ApplyBody) {
  return apiFetch<{ shift_report_id: string; sections_written: SectionKey[] }>(`${base}/sessions/${id}/apply`, { method: "POST", body, token });
}

export function discardSession(token: string, id: string) {
  return apiFetch<ScanSession>(`${base}/sessions/${id}/discard`, { method: "POST", token });
}

export function listShiftPages(token: string, shiftReportId: string) {
  return apiFetch<ShiftPage[]>(`${base}/shifts/${shiftReportId}/pages`, { token });
}

export function listAliases(token: string) {
  return apiFetch<Alias[]>(`${base}/aliases`, { token });
}

export function updateAlias(token: string, id: string, targetValue: string) {
  return apiFetch<Alias>(`${base}/aliases/${id}`, { method: "PATCH", body: { target_value: targetValue }, token });
}

export function deleteAlias(token: string, id: string) {
  return apiFetch<Alias>(`${base}/aliases/${id}`, { method: "DELETE", token });
}

export function getVocabulary(token: string, workCenterId?: string) {
  const query = workCenterId ? `?work_center_id=${encodeURIComponent(workCenterId)}` : "";
  return apiFetch<VocabularyOptions>(`${base}/vocabulary${query}`, { token });
}

/** A photo as an object URL: an <img> cannot send the session's bearer token itself. */
export async function fetchPageImage(token: string, pageId: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${base}/pages/${pageId}/image`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return URL.createObjectURL(await response.blob());
}
```

- [ ] **Step 2: Write `imagePrep.ts`**

```ts
// frontend/src/features/scan/imagePrep.ts
import type { PageUpload } from "./scanApi";

// Big enough for handwriting, small enough for a phone on the plant's network.
const MAX_SIDE = 2400;

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** A photo made upright (EXIF), scaled down and re-encoded as JPEG before it is sent. */
export async function prepareImage(file: File): Promise<PageUpload> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((result) => (result ? resolve(result) : reject(new Error("encode"))), "image/jpeg", 0.85),
  );
  return { filename: file.name, content_type: "image/jpeg", width, height, data_base64: await toBase64(blob) };
}
```

- [ ] **Step 3: Write `scanText.ts`**

```ts
// frontend/src/features/scan/scanText.ts
import { L, type Label } from "../production/shift/shiftText";

export const S = {
  title: L("Scan paper fiches", "Scanner les fiches papier"),
  subtitle: L(
    "Photograph the shift's fiches, check what was read against the photo, then save it into the shift report as a draft.",
    "Photographiez les fiches du shift, vérifiez la lecture sur la photo, puis enregistrez-la dans la fiche de shift en brouillon.",
  ),
  noAccess: L("You do not have access to the scanner.", "Vous n'avez pas accès au scanner."),
  viewNew: L("New scan", "Nouveau scan"),
  viewHistory: L("Scans", "Scans"),
  viewDictionary: L("Dictionary", "Dictionnaire"),
  date: L("Date", "Date"),
  line: L("Line", "Ligne"),
  shift: L("Shift", "Shift"),
  workOrder: L("Work order", "OF"),
  noWorkOrder: L("No open work order on this line", "Aucun OF en cours sur cette ligne"),
  start: L("Start the scan", "Commencer le scan"),
  noReport: L("No report yet for this shift: saving the scan will open it.", "Pas encore de rapport pour ce shift : l'enregistrement du scan l'ouvrira."),
  existingReport: L("This shift already has a report", "Ce shift a déjà un rapport"),
  sectionsFilled: L("sections filled", "sections remplies"),
  validatedBlock: L(
    "This shift is validated and its stock posted. It must be returned before anything can change.",
    "Ce shift est validé et son stock passé. Il doit être renvoyé avant toute modification.",
  ),
  back: L("Back", "Retour"),
  discard: L("Discard this scan", "Abandonner ce scan"),
  discardConfirm: L("Discard this scan? The photos stay attached to nothing.", "Abandonner ce scan ? Les photos ne seront rattachées à rien."),
  failed: L("That did not work", "L'opération a échoué"),
  photos: L("Photos", "Photos"),
  photosHint: L(
    "Whole or partial pages, in any order. Each photo is read on the server, one at a time.",
    "Pages entières ou partielles, dans n'importe quel ordre. Chaque photo est lue sur le serveur, une à la fois.",
  ),
  addPhotos: L("Add photos", "Ajouter des photos"),
  takePhoto: L("Take a photo", "Prendre une photo"),
  preparing: L("Preparing photo", "Préparation de la photo"),
  uploadFailed: L("The photos could not be sent", "Les photos n'ont pas pu être envoyées"),
  unsupported: L("This photo format is not supported (use JPEG or PNG).", "Ce format de photo n'est pas pris en charge (utilisez JPEG ou PNG)."),
  remove: L("Remove", "Retirer"),
  reread: L("Read again", "Relire"),
  chooseForm: L("Pick the fiche type", "Choisir le type de fiche"),
  otherShift: L("Another shift", "Autre shift"),
  unknownShift: L("Shift not confirmed", "Shift non confirmé"),
  includeAnyway: L("Use it anyway", "Inclure quand même"),
  notImportable: L("Recognised — not imported yet", "Fiche reconnue — pas encore importée"),
  serviceDown: L("Reading service unavailable — retrying automatically", "Service de lecture indisponible — nouvel essai automatique"),
  review: L("Check what was read", "Vérifier la lecture"),
  reviewHint: L(
    "Yellow: worth a look (click it to see the photo). Red: required. Nothing is saved until you press Save.",
    "Jaune : à vérifier (cliquez pour voir la photo). Rouge : obligatoire. Rien n'est enregistré avant « Enregistrer ».",
  ),
  toCheck: L("to check", "à vérifier"),
  required: L("required", "obligatoires"),
  requiredBlocking: L("Required: the shift report refuses the section without it.", "Obligatoire : la fiche de shift refuse la section sans cette valeur."),
  requiredLater: L("Required before the team submits this section.", "Obligatoire avant que l'équipe soumette cette section."),
  applyButton: L("Save into the shift report", "Enregistrer dans la fiche de shift"),
  applyTitle: L("Save the scan into the shift report", "Enregistrer le scan dans la fiche de shift"),
  applyHint: L(
    "The sections are saved as drafts. The team then submits them as usual.",
    "Les sections sont enregistrées en brouillon. L'équipe les soumet ensuite comme d'habitude.",
  ),
  writeNew: L("Written (was empty)", "Écrite (était vide)"),
  replaceDraft: L("Replaces the rows already there", "Remplace les lignes déjà saisies"),
  replaceSubmitted: L("Replaces a submitted section — a revision is kept", "Remplace une section soumise — une révision est conservée"),
  keptExisting: L("Kept as it is — the photo is ignored", "Gardée telle quelle — la photo est ignorée"),
  blockingTitle: L("Fill these before saving:", "À remplir avant d'enregistrer :"),
  doubtsLeft: L("values still yellow — saving keeps them as read", "valeurs encore en jaune — l'enregistrement les garde telles que lues"),
  confirmSave: L("Save", "Enregistrer"),
  saving: L("Saving…", "Enregistrement…"),
  applied: L("Saved into the shift report", "Enregistré dans la fiche de shift"),
  appliedCard: L("This scan was saved into the shift report.", "Ce scan a été enregistré dans la fiche de shift."),
  discardedCard: L("This scan was discarded.", "Ce scan a été abandonné."),
  openShift: L("Open the shift report", "Ouvrir la fiche de shift"),
  existingRows: L("Already filled:", "Déjà rempli :"),
  replace: L("Replace", "Remplacer"),
  keep: L("Keep existing", "Garder l'existant"),
  keptHint: L("The section keeps what the team typed; the photo's rows are ignored.", "La section garde la saisie de l'équipe ; les lignes de la photo sont ignorées."),
  setAsideTitle: L("Put aside", "Mis de côté"),
  addBack: L("Add this line", "Ajouter cette ligne"),
  header: L("Team and names", "Équipe et noms"),
  team: L("Team", "Équipe"),
  conducteur: L("Line driver", "Conducteur ligne"),
  agent: L("Production agent", "Agent de fabrication"),
  machiniste: L("Machine operator", "Machiniste"),
  aide: L("Assistant operator", "Aide machiniste"),
  photo: L("Photo", "Photo"),
  noSource: L("Click a value to see where it was read.", "Cliquez sur une valeur pour voir où elle a été lue."),
  readAs: L("Read:", "Lu :"),
  valueIsRight: L("The value is right", "La valeur est correcte"),
  zoom: L("Zoom", "Zoom"),
  newReading: L("A new photo was read: sections you have not touched were updated.", "Une nouvelle photo a été lue : les sections non modifiées ont été mises à jour."),
  sessions: L("Scans", "Scans"),
  noSessions: L("No scan yet.", "Aucun scan pour l'instant."),
  pages: L("Photos", "Photos"),
  created: L("Started", "Commencé"),
  status: L("Status", "Statut"),
  open: L("Open", "Ouvrir"),
  kind: L("Kind", "Type"),
  written: L("Written", "Écrit"),
  value: L("Value", "Valeur"),
  uses: L("Uses", "Utilisations"),
  updated: L("Updated", "Modifié"),
  edit: L("Edit", "Modifier"),
  delete: L("Delete", "Supprimer"),
  save: L("Save", "Enregistrer"),
  cancel: L("Cancel", "Annuler"),
  noAliases: L("The dictionary fills itself as you correct scans.", "Le dictionnaire se remplit au fil des corrections."),
  dictionaryHint: L(
    "What the plant writes on its fiches, and the value it stands for — learned from the corrections made while checking scans.",
    "Ce que l'usine écrit sur ses fiches, et la valeur correspondante — appris des corrections faites en vérifiant les scans.",
  ),
  importFromPhotos: L("Import from photos", "Importer depuis des photos"),
  paperPages: L("Paper fiches", "Fiches papier"),
  all: L("All", "Tous"),
  clearFilters: L("Clear filters", "Effacer les filtres"),
} satisfies Record<string, Label>;

export const REASONS: Record<string, Label> = {
  low_confidence: L("The reading is uncertain.", "La lecture est incertaine."),
  unreadable: L("The handwriting could not be read as a value of this kind.", "L'écriture n'a pas pu être lue comme une valeur de ce type."),
  lookalike: L("Some characters were read as digits (O as 0, l as 1).", "Certains caractères ont été lus comme des chiffres (O pour 0, l pour 1)."),
  lot_format: L("This does not look like a lot number.", "Cela ne ressemble pas à un numéro de lot."),
  unresolved: L("Not in the dictionary yet: pick the right value, it will be remembered.", "Pas encore dans le dictionnaire : choisissez la bonne valeur, elle sera retenue."),
  ambiguous: L("Several values match what was read.", "Plusieurs valeurs correspondent à la lecture."),
  partial_match: L("Matched on part of the name only.", "Correspondance sur une partie du nom seulement."),
  conflicting: L("Two photos give different readings.", "Deux photos donnent des lectures différentes."),
  rows_disagree: L("Photos of this table show different numbers of lines.", "Les photos de ce tableau montrent des nombres de lignes différents."),
  lot_date: L("The lot's date is not the shift's date.", "La date du lot n'est pas celle du shift."),
  lot_team: L("The lot's team letter is not the shift's team.", "La lettre d'équipe du lot n'est pas celle du shift."),
  team_mismatch: L("The team written is not the shift's team.", "L'équipe écrite n'est pas celle du shift."),
  short_lot: L("Completed from a longer lot on the same fiches.", "Complété à partir d'un lot plus long sur les mêmes fiches."),
  inferred_stop: L("Worked out from a start time written in the text.", "Déduit d'une heure de démarrage écrite dans le texte."),
  split_stop: L("Split from a line holding several intervals.", "Séparé d'une ligne contenant plusieurs intervalles."),
  fab_date: L("The production date written is not the shift's date.", "La date de fabrication écrite n'est pas celle du shift."),
  format_mismatch: L("The packing format written does not match the product's weight.", "Le format écrit ne correspond pas au poids du produit."),
  of_product: L("The product written is not the work order's product.", "Le produit écrit n'est pas celui de l'OF."),
  same_loss: L(
    "Probably the loss already listed on the packing fiche (same lot): kept aside so it is not counted twice.",
    "Probablement la perte déjà notée sur la fiche conditionnement (même lot) : mise de côté pour ne pas la compter deux fois.",
  ),
};

export const VERDICT_REASONS: Record<string, Label> = {
  date: L("another date", "autre date"),
  hours: L("other hours", "autres heures"),
  line: L("other line", "autre ligne"),
};

export const FORM_LABELS: Record<string, Label> = {
  fabrication: L("Production fiche", "Fiche fabrication"),
  conditionnement: L("Packing fiche", "Fiche conditionnement"),
  bobines: L("Reel changes", "Changement bobines"),
};

export const PAGE_STATUS: Record<string, Label> = {
  queued: L("Waiting", "En file"),
  reading: L("Reading…", "Lecture…"),
  read: L("Read", "Lue"),
  unrecognized: L("Not recognised", "Non reconnue"),
  failed: L("Failed", "Échec"),
};

export const SESSION_STATUS: Record<string, Label> = {
  open: L("In progress", "En cours"),
  applied: L("Saved", "Enregistré"),
  discarded: L("Discarded", "Abandonné"),
};

export const SECTION_STATUS: Record<string, Label> = {
  empty: L("empty", "vide"),
  draft: L("draft", "brouillon"),
  submitted: L("submitted", "soumise"),
  nothing_to_report: L("nothing to report", "rien à signaler"),
  returned: L("returned", "renvoyée"),
};

export const SHIFT_STATUS: Record<string, Label> = {
  open: L("in progress", "en cours"),
  submitted: L("submitted", "soumis"),
  validated: L("validated", "validé"),
  returned: L("returned", "renvoyé"),
};

export const KIND_LABELS: Record<string, Label> = {
  raw_material: L("Raw material", "Matière première"),
  regrind_item: L("Rebroyat item", "Article rebroyat"),
  finished_product: L("Finished product", "Produit fini"),
  film_item: L("Film", "Film"),
  waste_production: L("Production waste", "Déchet production"),
  waste_packing: L("Packing waste", "Déchet conditionnement"),
  equipment: L("Machine", "Machine"),
  mold: L("Mold", "Moule"),
  downtime_motif: L("Stop reason", "Motif d'arrêt"),
  line_state: L("Line state", "État de la ligne"),
  check_state: L("Check result", "Résultat de contrôle"),
  team: L("Team", "Équipe"),
  person: L("Name", "Nom"),
};
```

- [ ] **Step 4: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/scan/scanApi.ts frontend/src/features/scan/imagePrep.ts frontend/src/features/scan/scanText.ts
git commit -m "feat(scan): frontend API, photo preparation and labels"
```

---

### Task 18: The review model (pure, tested)

**Files:**
- Create: `frontend/src/features/scan/reviewModel.ts`
- Test: `frontend/src/features/scan/reviewModel.test.ts`

**Interfaces:**
- Consumes: `SectionDef`, `Column` (`sectionConfig.ts`), `isBlankRow`, `GridRow` (`ShiftGrid.tsx`), Task 17 types.
- Produces: `APPLY_ORDER`, `fieldPath(section, part, ref, field)`, `sectionNotice(section)`, `rowRef(row)`, `isEmpty(value)`, `isBlocking(section, part, field)`, `valuesFromProposal(proposal) -> ReviewValues`, `mergeProposal(current, proposal, touched) -> ReviewValues`, `valuesByPath(values) -> Map<string, unknown>`, `sameValue(a, b)`, `openDoubts(proposal, values, confirmed, sections) -> string[]`, `missingRequired(values, defs, sections) -> Missing[]`, `sectionsToWrite(values, choices, shift) -> SectionKey[]`, `applyBody(values, sections, shift) -> ApplyBody`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/features/scan/reviewModel.test.ts
import { describe, expect, it } from "vitest";
import { SECTIONS } from "../production/shift/sectionConfig";
import type { Proposal, ShiftState } from "./scanApi";
import {
  applyBody, mergeProposal, missingRequired, openDoubts, sectionsToWrite, valuesFromProposal,
} from "./reviewModel";

const proposal: Proposal = {
  header: { team: "Equipe D", conducteur: "Conducteur Un" },
  sections: {
    runs: { runs: [{ _scan_ref: "R1", of_id: null, lot_number: "D6249SNL", water_percentage: 28.9 }], versements: [] },
    packing: { rows: [{ _scan_ref: "K1", product_id: null, carton_quantity: 1 }] },
    stops: { stops: [{ _scan_ref: "S1", started_at: "2026-09-07T12:18", note: "coupure" }] },
  },
  flags: {
    "runs/runs/R1/lot_number": [{ reason: "lot_date", detail: "2026-09-06" }],
    "packing/rows/K1/carton_quantity": [{ reason: "lookalike", detail: null }],
    "stops/stops/S1/note": [{ reason: "low_confidence", detail: null }],
    "runs/-/-/-": [{ reason: "rows_disagree", detail: null }],
  },
  sources: {},
  coded: {},
  set_aside: {},
  pages: {},
};

const shiftWithStops: ShiftState = {
  id: "SH", status: "open", team: null, conducteur: null, agent_fabrication: null, machiniste: null, aide_machiniste: null,
  default_lot_number: null,
  sections: { stops: { status: "submitted", revision: 1, rows: 2, fingerprint: "fp-stops", payload: {} } },
};

describe("reviewModel", () => {
  it("keys every row by its scan reference", () => {
    const values = valuesFromProposal(proposal);
    expect((values.sections.runs!.runs as { _key: string }[])[0]._key).toBe("R1");
    expect(values.header.team).toBe("Equipe D");
  });

  it("keeps touched sections and typed names when a new photo is read", () => {
    const current = valuesFromProposal(proposal);
    (current.sections.stops!.stops as Record<string, unknown>[])[0].note = "typed";
    current.header.conducteur = "Racine";
    const merged = mergeProposal(current, proposal, new Set(["stops"]));
    expect((merged.sections.stops!.stops as Record<string, unknown>[])[0].note).toBe("typed");
    expect(merged.header.conducteur).toBe("Racine");
  });

  it("counts a doubt until the value is changed or confirmed, only in written sections", () => {
    const values = valuesFromProposal(proposal);
    expect(openDoubts(proposal, values, new Set(), ["runs", "packing"]).sort()).toEqual([
      "packing/rows/K1/carton_quantity", "runs/runs/R1/lot_number",
    ]);
    (values.sections.packing!.rows as Record<string, unknown>[])[0].carton_quantity = 2;
    expect(openDoubts(proposal, values, new Set(["runs/runs/R1/lot_number"]), ["runs", "packing"])).toEqual([]);
  });

  it("tells blocking required values from those needed at submit", () => {
    const missing = missingRequired(valuesFromProposal(proposal), SECTIONS, ["runs", "packing"]);
    expect(missing.map((m) => [m.section, m.column.key, m.blocking])).toEqual([
      ["runs", "of_id", true],
      ["packing", "product_id", false],
    ]);
  });

  it("writes a section already filled only when replace is chosen", () => {
    const values = valuesFromProposal(proposal);
    expect(sectionsToWrite(values, {}, shiftWithStops)).toEqual(["runs", "packing"]);
    expect(sectionsToWrite(values, { stops: "replace" }, shiftWithStops)).toEqual(["runs", "stops", "packing"]);
  });

  it("builds the apply body without client keys or blank rows", () => {
    const values = valuesFromProposal(proposal);
    (values.sections.stops!.stops as Record<string, unknown>[]).push({ _key: "blank", _fresh: true });
    const body = applyBody(values, ["stops"], shiftWithStops);
    expect(body.sections.stops).toEqual({ stops: [{ _scan_ref: "S1", started_at: "2026-09-07T12:18", note: "coupure" }] });
    expect(body.fingerprints).toEqual({ stops: "fp-stops" });
    expect(body.header.team).toBe("Equipe D");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `frontend/`): `npx vitest run src/features/scan/reviewModel.test.ts`
Expected: FAIL — cannot resolve `./reviewModel`.

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/scan/reviewModel.ts
/**
 * The review's rules, kept free of React so they can be tested: which cells are still in
 * doubt, which required values are missing (and whether the save would refuse the
 * section without them), which sections will be written, and the body sent on apply.
 */
import type { Column, SectionDef } from "../production/shift/sectionConfig";
import { isBlankRow, type GridRow } from "../production/shift/ShiftGrid";
import type { Row, SectionKey } from "../production/shift/shiftApi";
import type { ApplyBody, Choice, Proposal, ReviewValues, ShiftState } from "./scanApi";

export const APPLY_ORDER: readonly SectionKey[] = [
  "runs", "waste_production", "stops", "silo", "staffing", "packing", "packet_checks", "waste_packing",
];

// Values save_section refuses a section without; the other required columns are only needed at submit.
const BLOCKING = new Set([
  "runs.runs.of_id", "stops.stops.started_at", "waste_production.waste_lines.category",
  "waste_packing.waste_lines.category", "silo.states.side", "silo.states.phase",
]);
const CLIENT_KEYS = new Set(["_key", "_fresh", "_auto"]);

export const fieldPath = (section: string, part: string, ref: string, field: string) => `${section}/${part}/${ref}/${field}`;
export const sectionNotice = (section: string) => fieldPath(section, "-", "-", "-");
export const rowRef = (row: Row) => (typeof row._scan_ref === "string" ? row._scan_ref : "-");
export const isEmpty = (value: unknown) => value === null || value === undefined || value === "";
export const isBlocking = (section: string, part: string, field: string) => BLOCKING.has(`${section}.${part}.${field}`);
export const sameValue = (a: unknown, b: unknown) => (isEmpty(a) && isEmpty(b)) || String(a) === String(b);

type PartValue = GridRow[] | Row;

export function valuesFromProposal(proposal: Proposal): ReviewValues {
  const sections: ReviewValues["sections"] = {};
  for (const [key, parts] of Object.entries(proposal.sections) as [SectionKey, Record<string, unknown>][]) {
    const out: Record<string, PartValue> = {};
    for (const [part, value] of Object.entries(parts)) {
      out[part] = Array.isArray(value)
        ? (value as Row[]).map((row) => ({ ...row, _key: String(row._scan_ref) }))
        : { ...((value ?? {}) as Row) };
    }
    sections[key] = out;
  }
  return { header: { ...proposal.header }, sections };
}

/** A new proposal (another photo read) refreshes what the user has not touched. */
export function mergeProposal(current: ReviewValues, proposal: Proposal, touched: ReadonlySet<SectionKey>): ReviewValues {
  const fresh = valuesFromProposal(proposal);
  const sections = { ...fresh.sections };
  for (const key of touched) if (current.sections[key]) sections[key] = current.sections[key];
  const header = { ...fresh.header };
  for (const [field, value] of Object.entries(current.header)) if (!isEmpty(value)) header[field] = value;
  return { header, sections };
}

export function valuesByPath(values: ReviewValues): Map<string, unknown> {
  const out = new Map<string, unknown>();
  for (const [field, value] of Object.entries(values.header)) out.set(fieldPath("header", "-", "-", field), value);
  for (const [section, parts] of Object.entries(values.sections)) {
    for (const [part, value] of Object.entries(parts ?? {})) {
      const rows = Array.isArray(value) ? value : [value as Row];
      for (const row of rows) {
        const ref = Array.isArray(value) ? rowRef(row) : "-";
        for (const [key, cell] of Object.entries(row)) if (!key.startsWith("_")) out.set(fieldPath(section, part, ref, key), cell);
      }
    }
  }
  return out;
}

/** Doubts still standing: flagged, still the value read, and not confirmed -- in the sections being written. */
export function openDoubts(
  proposal: Proposal, values: ReviewValues, confirmed: ReadonlySet<string>, sections: readonly SectionKey[],
): string[] {
  const proposed = valuesByPath(valuesFromProposal(proposal));
  const current = valuesByPath(values);
  return Object.keys(proposal.flags).filter((path) => {
    const section = path.split("/", 1)[0];
    if (path.endsWith("/-/-/-") || confirmed.has(path)) return false;
    if (section !== "header" && !sections.includes(section as SectionKey)) return false;
    return current.has(path) && sameValue(current.get(path), proposed.get(path));
  });
}

export interface Missing {
  section: SectionKey;
  part: string;
  ref: string;
  column: Column;
  blocking: boolean;
}

export function missingRequired(values: ReviewValues, defs: readonly SectionDef[], sections: readonly SectionKey[]): Missing[] {
  const out: Missing[] = [];
  for (const def of defs) {
    if (!sections.includes(def.key)) continue;
    for (const part of def.parts) {
      const value = values.sections[def.key]?.[part.payloadKey];
      if (value === undefined) continue;
      const rows = part.shape === "rows" ? (value as GridRow[]).filter((row) => !isBlankRow(row)) : [value as Row];
      for (const row of rows) {
        for (const column of part.columns) {
          if (column.required && isEmpty(row[column.key])) {
            out.push({ section: def.key, part: part.payloadKey, ref: rowRef(row), column, blocking: isBlocking(def.key, part.payloadKey, column.key) });
          }
        }
      }
    }
  }
  return out;
}

export function sectionsToWrite(
  values: ReviewValues, choices: Partial<Record<SectionKey, Choice>>, shift: ShiftState | null,
): SectionKey[] {
  return APPLY_ORDER.filter(
    (key) => values.sections[key] !== undefined && ((shift?.sections[key]?.rows ?? 0) === 0 || choices[key] === "replace"),
  );
}

const clean = (row: GridRow): Row => Object.fromEntries(Object.entries(row).filter(([key]) => !CLIENT_KEYS.has(key)));

export function applyBody(values: ReviewValues, sections: readonly SectionKey[], shift: ShiftState | null): ApplyBody {
  const out: ApplyBody["sections"] = {};
  for (const key of sections) {
    const parts = values.sections[key] ?? {};
    out[key] = Object.fromEntries(
      Object.entries(parts).map(([part, value]) => [
        part,
        Array.isArray(value) ? value.filter((row) => !isBlankRow(row)).map(clean) : value,
      ]),
    );
  }
  return {
    header: values.header,
    sections: out,
    fingerprints: Object.fromEntries(sections.map((key) => [key, shift?.sections[key]?.fingerprint ?? null])),
  };
}
```

- [ ] **Step 4: Run the tests and type-check**

Run: `npx vitest run src/features/scan/reviewModel.test.ts` then `npx tsc -b --force`
Expected: PASS; no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/scan/reviewModel.ts frontend/src/features/scan/reviewModel.test.ts
git commit -m "feat(scan): review rules (doubts, required values, sections written, apply body)"
```

---

### Task 19: Cell highlighting in the shift grids

**Files:**
- Modify: `frontend/src/features/production/shift/ShiftGrid.tsx` (props of `ShiftGrid`, the body `<td>`)
- Modify: `frontend/src/features/production/shift/SectionCard.tsx` (`Part`)

**Interfaces:**
- Produces: `export interface CellDecor { tone: "doubt" | "required"; title?: string }`, `export const DECOR_CLASS: Record<CellDecor["tone"], string>`; new optional props on `ShiftGrid` and `Part`: `decorate?: (row: Row, key: string) => CellDecor | undefined` and `onCellFocus?: (row: Row, key: string) => void`. The shift form passes neither and renders exactly as before.

- [ ] **Step 1: Add the types and class map to `ShiftGrid.tsx`** (after `export type OptionMap …`)

```ts
/** How a cell is marked by a screen reviewing values it did not type (the paper scan). */
export interface CellDecor {
  tone: "doubt" | "required";
  title?: string;
}

export const DECOR_CLASS: Record<CellDecor["tone"], string> = {
  doubt: "bg-warning-soft ring-1 ring-inset ring-warning/60",
  required: "ring-1 ring-inset ring-destructive",
};
```

- [ ] **Step 2: Accept the props in `ShiftGrid`**

Add to the destructured props `decorate,` and `onCellFocus,` and to the props type:

```ts
  /** Marks a cell (the scan review's yellow doubts and red required values). */
  decorate?: (row: Row, key: string) => CellDecor | undefined;
  /** Called when a cell takes focus (the scan review shows where the value was read). */
  onCellFocus?: (row: Row, key: string) => void;
```

- [ ] **Step 3: Apply them to the body cells**

Replace the body cells block

```tsx
                    {columns.map((column, columnIndex) => (
                      <td
                        key={column.key}
                        className={cn("px-1 py-1", columnIndex === 0 && cn("bg-background border-r border-border/70", pin, firstLeft))}
                      >
```

with

```tsx
                    {columns.map((column, columnIndex) => {
                      const decor = decorate?.(row, column.key);
                      return (
                      <td
                        key={column.key}
                        title={decor?.title}
                        onFocusCapture={onCellFocus ? () => onCellFocus(row, column.key) : undefined}
                        className={cn(
                          "px-1 py-1",
                          columnIndex === 0 && cn("bg-background border-r border-border/70", pin, firstLeft),
                          decor && DECOR_CLASS[decor.tone],
                        )}
                      >
```

and close it by replacing the matching `</td>\n                    ))}` with `</td>\n                      );\n                    })}`.

- [ ] **Step 4: Pass them through `Part` in `SectionCard.tsx`**

Import `DECOR_CLASS` and `type CellDecor` from `./ShiftGrid`. Add to `Part`'s props and type:

```ts
  decorate?: (row: Row, key: string) => CellDecor | undefined;
  onCellFocus?: (row: Row, key: string) => void;
```

In the `single` branch wrap each field so it is marked too:

```tsx
          {part.columns.map((column) => {
            const decor = decorate?.(value as Row, column.key);
            return (
              <div
                key={column.key}
                title={decor?.title}
                onFocusCapture={onCellFocus ? () => onCellFocus(value as Row, column.key) : undefined}
                className={cn("space-y-1 rounded-md p-1", decor && DECOR_CLASS[decor.tone])}
              >
                <FieldLabel htmlFor={`${idPrefix}-${column.key}`} className="text-xs text-muted-foreground">
                  {label(column.label)}
                </FieldLabel>
                <Cell
                  column={column}
                  value={(value as Row)[column.key]}
                  onChange={(next) => onChange({ ...(value as Row), [column.key]: next })}
                  options={options}
                  disabled={disabled}
                  idPrefix={idPrefix}
                />
              </div>
            );
          })}
```

(import `cn` from `../../../lib/utils` if `SectionCard.tsx` does not already), and pass `decorate={decorate}` and `onCellFocus={onCellFocus}` to the `<ShiftGrid …>` in the `rows` branch.

- [ ] **Step 5: Type-check and confirm the shift form is unchanged**

Run: `npx tsc -b --force` — no errors. Open Production → Fiche de shift in the browser (demo login `demo@sonalim-erp.local` / `demo1234`, see the "Verify frontend changes" memory): tables render and edit exactly as before, no highlighted cell.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/production/shift/ShiftGrid.tsx frontend/src/features/production/shift/SectionCard.tsx
git commit -m "feat(shift): optional per-cell marking and focus hooks on the section grids"
```

---

### Task 20: The Scanner tab, starting a scan, and the scans list

**Files:**
- Create: `frontend/src/features/scan/ScanTab.tsx`, `frontend/src/features/scan/ScanStart.tsx`, `frontend/src/features/scan/ScanSessionsTable.tsx`
- Modify: `frontend/src/features/production/ProductionPage.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.en.ts`, `frontend/src/lib/i18n.fr.ts`

**Interfaces:**
- Consumes: Task 17; `useShiftReferenceData` (`workCenters`, `windows`), `listWorkOrders`, `listShiftReports`, `SHIFT_REPORTS_QUERY_KEY`; `FilterTabs`, `useColumnFilters`, `useTableColumns`, `ColumnFilterRow`, `ColumnVisibilityMenu`, `ResizableTableHead`.
- Produces: `ScanTab` (route `/production?tab=scan`, `&session=<id>` opens a scan; `&line=&date=&shift=` preselect a new one); `ScanWorkspace` is imported from Task 21 (create it in Task 21; until then `ScanTab` renders a placeholder `null` for a session — replace in Task 21).

- [ ] **Step 1: Write `ScanStart.tsx`**

```tsx
// frontend/src/features/scan/ScanStart.tsx
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ScanLine } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label as FieldLabel } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { listWorkOrders } from "../production/api";
import { listShiftReports, SHIFT_REPORTS_QUERY_KEY } from "../production/shift/shiftApi";
import { useLabel } from "../production/shift/shiftText";
import { useShiftReferenceData } from "../production/shift/useShiftReferenceData";
import { createSession, SCAN_SESSIONS_QUERY_KEY } from "./scanApi";
import { S, SHIFT_STATUS } from "./scanText";

const today = () => new Date().toISOString().slice(0, 10);
const DONE = new Set(["submitted", "nothing_to_report", "draft"]);

export function ScanStart({ onCreated }: { onCreated: (sessionId: string) => void }) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const reference = useShiftReferenceData(true);
  const [date, setDate] = useState(() => params.get("date") || today());
  const [line, setLine] = useState(() => params.get("line") ?? "");
  const [shift, setShift] = useState(() => params.get("shift") ?? "");
  const [ofId, setOfId] = useState("");

  useEffect(() => {
    if (!line && reference.workCenters.length) setLine(reference.workCenters[0].id);
  }, [line, reference.workCenters]);
  useEffect(() => {
    if (!shift && reference.windows.length) setShift(reference.windows[0].shift);
  }, [shift, reference.windows]);

  const orders = useQuery({ queryKey: ["production", "shift", "orders"], queryFn: () => listWorkOrders(token) });
  const lineOrders = useMemo(
    () => (orders.data ?? []).filter((o) => o.status === "ongoing" && !o.is_regrind && o.work_center_id === line),
    [orders.data, line],
  );
  useEffect(() => {
    if (!lineOrders.some((o) => o.id === ofId)) setOfId(lineOrders[0]?.id ?? "");
  }, [lineOrders, ofId]);

  const reports = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "find", date, line],
    queryFn: () => listShiftReports(token, { report_date: date, work_center_id: line }),
    enabled: !!line,
  });
  const report = reports.data?.find((s) => s.shift.trim().toLowerCase() === shift.trim().toLowerCase());
  const validated = report?.status === "validated";
  const filled = report?.sections.filter((s) => DONE.has(s.status)).length ?? 0;

  const create = useMutation({
    mutationFn: () => createSession(token, { work_center_id: line, report_date: date, shift, default_of_id: ofId || null }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: SCAN_SESSIONS_QUERY_KEY });
      onCreated(created.id);
    },
    onError: (error) => toast.error(label(S.failed), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Card>
      <CardContent className="space-y-4 py-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1">
            <FieldLabel htmlFor="scan-date">{label(S.date)}</FieldLabel>
            <Input id="scan-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="space-y-1">
            <FieldLabel htmlFor="scan-line">{label(S.line)}</FieldLabel>
            <Select id="scan-line" value={line} onChange={(e) => setLine(e.target.value)}>
              {reference.workCenters.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <FieldLabel htmlFor="scan-shift">{label(S.shift)}</FieldLabel>
            <Select id="scan-shift" value={shift} onChange={(e) => setShift(e.target.value)}>
              {reference.windows.map((w) => (
                <option key={w.shift} value={w.shift}>{`${w.shift} (${w.start_time.slice(0, 5)}–${w.end_time.slice(0, 5)})`}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <FieldLabel htmlFor="scan-of">{label(S.workOrder)}</FieldLabel>
            <Select id="scan-of" value={ofId} onChange={(e) => setOfId(e.target.value)} disabled={lineOrders.length === 0}>
              {lineOrders.length === 0 && <option value="">{label(S.noWorkOrder)}</option>}
              {lineOrders.map((o) => (
                <option key={o.id} value={o.id}>{o.reference}</option>
              ))}
            </Select>
          </div>
        </div>

        {report ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>{label(S.existingReport)}</span>
            <Badge variant={validated ? "destructive" : "primary"}>{label(SHIFT_STATUS[report.status])}</Badge>
            <span className="text-muted-foreground">{`${filled}/${report.sections.length} ${label(S.sectionsFilled)}`}</span>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{label(S.noReport)}</p>
        )}
        {validated && (
          <p className="flex items-start gap-2 rounded-md bg-destructive-soft px-3 py-2 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            {label(S.validatedBlock)}
          </p>
        )}

        <Button onClick={() => create.mutate()} disabled={!line || !shift || validated || create.isPending}>
          <ScanLine className="h-4 w-4" />
          {label(S.start)}
        </Button>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Write `ScanSessionsTable.tsx`**

```tsx
// frontend/src/features/scan/ScanSessionsTable.tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScanLine } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { useLabel } from "../production/shift/shiftText";
import { useShiftReferenceData } from "../production/shift/useShiftReferenceData";
import { listSessions, SCAN_SESSIONS_QUERY_KEY, type ScanSession, type SessionStatus } from "./scanApi";
import { S, SESSION_STATUS } from "./scanText";

type StatusFilter = "all" | SessionStatus;
const STATUS_VARIANT = { open: "warning", applied: "success", discarded: "default" } as const;

export function ScanSessionsTable({ onOpen }: { onOpen: (sessionId: string) => void }) {
  const { session } = useAuth();
  const label = useLabel();
  const reference = useShiftReferenceData(true);
  const lineName = (id: string) => reference.workCenters.find((w) => w.id === id)?.name ?? "—";
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const { data: sessions = [], isLoading } = useQuery({ queryKey: SCAN_SESSIONS_QUERY_KEY, queryFn: () => listSessions(session!.token) });

  const filterFields: FilterField<ScanSession>[] = [
    { key: "date", kind: "text", getValue: (s) => s.report_date },
    { key: "line", kind: "text", getValue: (s) => lineName(s.work_center_id) },
    { key: "shift", kind: "text", getValue: (s) => s.shift },
    { key: "pages", kind: "range", getValue: (s) => s.page_count ?? 0 },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const rows = columnFilters.apply(statusFilter === "all" ? sessions : sessions.filter((s) => s.status === statusFilter));

  const columns: ColumnDef<ScanSession>[] = [
    {
      key: "date", header: label(S.date), defaultWidth: 130, cell: (s) => s.report_date, sortValue: (s) => s.report_date,
      filterCell: { type: "text", value: columnFilters.text.date ?? "", onChange: (v) => columnFilters.setTextValue("date", v), placeholder: label(S.date) },
    },
    {
      key: "line", header: label(S.line), defaultWidth: 160, cell: (s) => lineName(s.work_center_id),
      filterCell: { type: "text", value: columnFilters.text.line ?? "", onChange: (v) => columnFilters.setTextValue("line", v), placeholder: label(S.line) },
    },
    {
      key: "shift", header: label(S.shift), defaultWidth: 120, cell: (s) => s.shift, sortValue: (s) => s.shift,
      filterCell: { type: "text", value: columnFilters.text.shift ?? "", onChange: (v) => columnFilters.setTextValue("shift", v), placeholder: label(S.shift) },
    },
    {
      key: "status", header: label(S.status), defaultWidth: 130,
      cell: (s) => <Badge variant={STATUS_VARIANT[s.status]}>{label(SESSION_STATUS[s.status])}</Badge>,
    },
    {
      key: "pages", header: label(S.pages), defaultWidth: 100, cell: (s) => s.page_count ?? 0, sortValue: (s) => s.page_count ?? 0,
      filterCell: {
        type: "range", min: columnFilters.range.pages?.min ?? "", max: columnFilters.range.pages?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("pages", "min", v), onMaxChange: (v) => columnFilters.setRangeValue("pages", "max", v),
      },
    },
    { key: "created", header: label(S.created), defaultWidth: 170, cell: (s) => new Date(s.created_at).toLocaleString(), sortValue: (s) => s.created_at },
    {
      key: "action", header: "", defaultWidth: 110, alwaysVisible: true, cellClassName: "text-right",
      cell: (s) => <Button size="sm" variant="outline" onClick={() => onOpen(s.id)}>{label(S.open)}</Button>,
    },
  ];
  const table = useTableColumns("scan.sessions", columns);
  const sorted = table.sortRows(rows);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <CardTitle>{label(S.sessions)}</CardTitle>
          <FilterTabs
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: "all", label: label(S.all) },
              { value: "open", label: label(SESSION_STATUS.open) },
              { value: "applied", label: label(SESSION_STATUS.applied) },
              { value: "discarded", label: label(SESSION_STATUS.discarded) },
            ]}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>{label(S.clearFilters)}</Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <Table colWidths={table.colWidths}>
          <TableHeader>
            <TableRow>
              {table.visibleColumns.map((column) => (
                <ResizableTableHead
                  key={column.key}
                  width={table.getWidth(column.key)}
                  onResize={(width) => table.setWidth(column.key, width)}
                  sortDirection={table.sortDirectionFor(column.key)}
                  onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                >
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
          </TableHeader>
          <TableBody>
            {isLoading && <TableLoadingRow colSpan={table.visibleColumns.length} />}
            {!isLoading && sorted.length === 0 && (
              <TableRow>
                <TableCell colSpan={table.visibleColumns.length} className="p-0">
                  <EmptyState icon={<ScanLine className="h-5 w-5" />} title={label(S.noSessions)} description="" />
                </TableCell>
              </TableRow>
            )}
            {sorted.map((row) => (
              <TableRow key={row.id}>
                {table.visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>{column.cell(row)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: Write `ScanTab.tsx`**

```tsx
// frontend/src/features/scan/ScanTab.tsx
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Lock, ScanLine } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { Card, CardContent } from "../../components/ui/card";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { useLabel } from "../production/shift/shiftText";
import { AliasesTable } from "./AliasesTable";
import { ScanSessionsTable } from "./ScanSessionsTable";
import { ScanStart } from "./ScanStart";
import { ScanWorkspace } from "./ScanWorkspace";
import { S } from "./scanText";

type View = "new" | "history" | "dictionary";

export function ScanTab() {
  const { hasPermission } = useAuth();
  const label = useLabel();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<View>("new");
  const sessionId = params.get("session");

  if (!hasPermission("scan.use_scanner")) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 py-8 text-sm text-muted-foreground">
          <Lock className="mt-0.5 h-4 w-4 shrink-0" />
          {label(S.noAccess)}
        </CardContent>
      </Card>
    );
  }
  const open = (id: string) => setParams({ tab: "scan", session: id });
  if (sessionId) return <ScanWorkspace sessionId={sessionId} onBack={() => setParams({ tab: "scan" })} />;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <ScanLine className="h-5 w-5 text-primary" />
          {label(S.title)}
        </h2>
        <p className="text-sm text-muted-foreground">{label(S.subtitle)}</p>
      </div>
      <FilterTabs
        value={view}
        onChange={setView}
        options={[
          { value: "new", label: label(S.viewNew) },
          { value: "history", label: label(S.viewHistory) },
          { value: "dictionary", label: label(S.viewDictionary) },
        ]}
      />
      {view === "new" && <ScanStart onCreated={open} />}
      {view === "history" && <ScanSessionsTable onOpen={open} />}
      {view === "dictionary" && <AliasesTable />}
    </div>
  );
}
```

(`AliasesTable` and `ScanWorkspace` are created in Tasks 21 and 23; commit this task together with Task 21 if `tsc` must pass at each commit, or create one-line stubs `export function AliasesTable() { return null; }` and `export function ScanWorkspace(_: { sessionId: string; onBack: () => void }) { return null; }` that those tasks replace.)

- [ ] **Step 4: Register the tab**

`frontend/src/features/production/ProductionPage.tsx`: add `ScanLine` to the lucide import, `import { ScanTab } from "../scan/ScanTab";`, and after the `shift-report` entry of `TABS`:

```ts
  { value: "scan", labelKey: "production.tabs.scan", icon: ScanLine, Component: ScanTab },
```

`frontend/src/routes/Sidebar.tsx`: add `ScanLine,` to the lucide import list and after the `shift-report` entry of `PRODUCTION_TABS`:

```ts
  { tab: "scan", labelKey: "production.tabs.scan", icon: ScanLine },
```

`frontend/src/lib/i18n.en.ts` after `"production.tabs.shiftReport"`: `"production.tabs.scan": "Scan fiches",`
`frontend/src/lib/i18n.fr.ts` after `"production.tabs.shiftReport"`: `"production.tabs.scan": "Scanner les fiches",`

- [ ] **Step 5: Type-check**

Run: `npx tsc -b --force` — no errors (with the stubs from Step 3 if Tasks 21/23 are not done yet).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/scan frontend/src/features/production/ProductionPage.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.en.ts frontend/src/lib/i18n.fr.ts
git commit -m "feat(scan): Scanner tab — start a scan for a line, date, shift and OF; list scans"
```

---

### Task 21: The scan workspace and the photos panel

**Files:**
- Create: `frontend/src/features/scan/ScanWorkspace.tsx`, `frontend/src/features/scan/PhotosPanel.tsx`, `frontend/src/features/scan/PageImage.tsx`

**Interfaces:**
- Consumes: Tasks 17–18; `AppLoader`, `Skeleton`.
- Produces: `ScanWorkspace({ sessionId, onBack })`; `PhotosPanel({ session, disabled, included, onInclude })`; `usePageImage(pageId)`, `useUpright(url, rotation) -> string | null`, `PageImage({ pageId, rotation, className, alt })`. The workspace owns the `ReviewState` (single owner, debounced autosave) and hands `review` / `updateReview` to the review panel (Task 22).

- [ ] **Step 1: Write `PageImage.tsx`**

```tsx
// frontend/src/features/scan/PageImage.tsx
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { Skeleton } from "../../components/ui/skeleton";
import { fetchPageImage } from "./scanApi";

export function usePageImage(pageId: string | undefined) {
  const { session } = useAuth();
  return useQuery({
    queryKey: ["scan", "page-image", pageId],
    queryFn: () => fetchPageImage(session!.token, pageId!),
    enabled: !!pageId,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
  });
}

/** The photo turned the way the OCR read it, so boxes (fractions of the upright page) line up. */
export function useUpright(url: string | undefined, rotation: number): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!url) return;
    if (!rotation) {
      setSrc(url);
      return;
    }
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      const sideways = rotation % 180 !== 0;
      canvas.width = sideways ? image.height : image.width;
      canvas.height = sideways ? image.width : image.height;
      const context = canvas.getContext("2d")!;
      context.translate(canvas.width / 2, canvas.height / 2);
      context.rotate((rotation * Math.PI) / 180);
      context.drawImage(image, -image.width / 2, -image.height / 2);
      setSrc(canvas.toDataURL("image/jpeg", 0.85));
    };
    image.src = url;
  }, [url, rotation]);
  return src;
}

export function PageImage({ pageId, rotation, className, alt }: { pageId: string; rotation: number; className?: string; alt: string }) {
  const image = usePageImage(pageId);
  const src = useUpright(image.data, rotation);
  return src ? <img src={src} alt={alt} className={className} /> : <Skeleton className={className} />;
}
```

- [ ] **Step 2: Write `PhotosPanel.tsx`**

```tsx
// frontend/src/features/scan/PhotosPanel.tsx
import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Camera, ImagePlus, RotateCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Checkbox } from "../../components/ui/checkbox";
import { Select } from "../../components/ui/select";
import { useLabel } from "../production/shift/shiftText";
import { prepareImage } from "./imagePrep";
import { PageImage } from "./PageImage";
import {
  deletePage, rereadPage, scanProposalPrefix, scanSessionKey, uploadPages,
  type FormType, type PageUpload, type ScanPage, type SessionDetail,
} from "./scanApi";
import { FORM_LABELS, PAGE_STATUS, S, VERDICT_REASONS } from "./scanText";

const STATUS_VARIANT = { queued: "default", reading: "primary", read: "success", unrecognized: "warning", failed: "destructive" } as const;

export function PhotosPanel({
  session, disabled, included, onInclude,
}: { session: SessionDetail; disabled: boolean; included: ReadonlySet<string>; onInclude: (pageId: string, on: boolean) => void }) {
  const { session: auth } = useAuth();
  const token = auth!.token;
  const label = useLabel();
  const queryClient = useQueryClient();
  const pickRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const [preparing, setPreparing] = useState(0);
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: scanSessionKey(session.id) });
    queryClient.invalidateQueries({ queryKey: scanProposalPrefix(session.id) });
  };
  const fail = (error: unknown, fallback = S.failed) =>
    toast.error(label(fallback), { description: error instanceof ApiError ? error.message : label(S.unsupported) });

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const prepared: PageUpload[] = [];
      for (const [index, file] of files.entries()) {
        setPreparing(index + 1);
        prepared.push(await prepareImage(file));
      }
      return uploadPages(token, session.id, prepared);
    },
    onSettled: () => setPreparing(0),
    onSuccess: refresh,
    onError: (error) => fail(error, S.uploadFailed),
  });
  const remove = useMutation({ mutationFn: (pageId: string) => deletePage(token, session.id, pageId), onSuccess: refresh, onError: (e) => fail(e) });
  const reread = useMutation({
    mutationFn: ({ pageId, hint }: { pageId: string; hint: FormType | null }) => rereadPage(token, session.id, pageId, hint),
    onSuccess: refresh,
    onError: (e) => fail(e),
  });
  const pick = (files: FileList | null) => {
    if (files && files.length) upload.mutate(Array.from(files));
  };
  const serviceDown = session.pages.some((p) => p.status === "queued" && p.attempts > 0);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>{label(S.photos)}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{label(S.photosHint)}</p>
          </div>
          {!disabled && (
            <div className="flex gap-2">
              <input ref={pickRef} type="file" accept="image/*" multiple hidden onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
              <input ref={cameraRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
              <Button variant="outline" onClick={() => cameraRef.current?.click()} disabled={upload.isPending}>
                <Camera className="h-4 w-4" />
                {label(S.takePhoto)}
              </Button>
              <Button onClick={() => pickRef.current?.click()} disabled={upload.isPending}>
                <ImagePlus className="h-4 w-4" />
                {preparing ? `${label(S.preparing)} ${preparing}…` : label(S.addPhotos)}
              </Button>
            </div>
          )}
        </div>
        {serviceDown && <p className="text-sm text-warning">{label(S.serviceDown)}</p>}
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {session.pages.map((page) => (
          <PageCard
            key={page.id}
            page={page}
            disabled={disabled}
            included={included.has(page.id)}
            onInclude={(on) => onInclude(page.id, on)}
            onRemove={() => remove.mutate(page.id)}
            onReread={(hint) => reread.mutate({ pageId: page.id, hint })}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function PageCard({
  page, disabled, included, onInclude, onRemove, onReread,
}: {
  page: ScanPage; disabled: boolean; included: boolean; onInclude: (on: boolean) => void; onRemove: () => void; onReread: (hint: FormType | null) => void;
}) {
  const label = useLabel();
  const [hint, setHint] = useState<FormType | "">(page.form_hint ?? "");
  const verdict = page.attribution?.verdict;
  const importable = page.form_type === "fabrication" || page.form_type === "conditionnement";
  return (
    <div className="space-y-2 rounded-lg border border-border p-2">
      <PageImage pageId={page.id} rotation={page.rotation} alt={label(S.photo)} className="h-40 w-full rounded-md object-contain bg-muted" />
      <div className="flex flex-wrap gap-1">
        <Badge variant={STATUS_VARIANT[page.status]}>{label(PAGE_STATUS[page.status])}</Badge>
        {page.form_type && <Badge variant="outline">{label(FORM_LABELS[page.form_type])}</Badge>}
        {page.form_type === "bobines" && <Badge variant="warning">{label(S.notImportable)}</Badge>}
        {verdict === "unknown" && <Badge variant="warning">{label(S.unknownShift)}</Badge>}
      </div>
      {verdict === "other_shift" && (
        <div className="space-y-1 text-xs">
          <p className="text-destructive">
            {label(S.otherShift)} — {page.attribution!.reasons.map((r) => label(VERDICT_REASONS[r] ?? S.otherShift)).join(", ")}
          </p>
          {importable && !disabled && (
            <label className="flex items-center gap-2">
              <Checkbox checked={included} onCheckedChange={(on) => onInclude(on === true)} />
              {label(S.includeAnyway)}
            </label>
          )}
        </div>
      )}
      {!disabled && (page.status === "failed" || page.status === "unrecognized") && (
        <div className="flex gap-1">
          <Select className="h-8 text-xs" value={hint} onChange={(e) => setHint(e.target.value as FormType | "")}>
            <option value="">{label(S.chooseForm)}</option>
            {(["fabrication", "conditionnement", "bobines"] as const).map((form) => (
              <option key={form} value={form}>{label(FORM_LABELS[form])}</option>
            ))}
          </Select>
          <Button size="sm" variant="outline" onClick={() => onReread(hint || null)}>
            <RotateCw className="h-3.5 w-3.5" />
            {label(S.reread)}
          </Button>
        </div>
      )}
      {!disabled && (
        <Button size="sm" variant="ghost" className="w-full text-muted-foreground" onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
          {label(S.remove)}
        </Button>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Write `ScanWorkspace.tsx`**

```tsx
// frontend/src/features/scan/ScanWorkspace.tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { AppLoader } from "../../components/patterns/AppLoader";
import { useLabel } from "../production/shift/shiftText";
import { useShiftReferenceData } from "../production/shift/useShiftReferenceData";
import { PhotosPanel } from "./PhotosPanel";
import { ReviewPanel } from "./ReviewPanel";
import {
  discardSession, getSession, saveReview, SCAN_SESSIONS_QUERY_KEY, scanProposalPrefix, scanSessionKey,
  type ReviewState, type SessionDetail,
} from "./scanApi";
import { S, SESSION_STATUS, SHIFT_STATUS } from "./scanText";

const AUTOSAVE_MS = 1200;

export function ScanWorkspace({ sessionId, onBack }: { sessionId: string; onBack: () => void }) {
  const { session } = useAuth();
  const label = useLabel();
  const detail = useQuery({
    queryKey: scanSessionKey(sessionId),
    queryFn: () => getSession(session!.token, sessionId),
    refetchInterval: (query) =>
      query.state.data?.pages.some((p) => p.status === "queued" || p.status === "reading") ? 2000 : false,
  });
  if (detail.isLoading) return <AppLoader label={label(S.title)} />;
  if (!detail.data) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-muted-foreground">{label(S.failed)}</CardContent>
      </Card>
    );
  }
  return <Workspace session={detail.data} onBack={onBack} />;
}

function Workspace({ session, onBack }: { session: SessionDetail; onBack: () => void }) {
  const { session: auth } = useAuth();
  const token = auth!.token;
  const label = useLabel();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const reference = useShiftReferenceData(true);
  const [review, setReview] = useState<ReviewState>(() => session.review_state ?? {});
  const dirty = useRef(false);

  const updateReview = useCallback((change: (current: ReviewState) => ReviewState) => {
    dirty.current = true;
    setReview(change);
  }, []);
  const autosave = useMutation({ mutationFn: (state: ReviewState) => saveReview(token, session.id, state) });
  useEffect(() => {
    if (!dirty.current || session.status !== "open") return;
    const timer = window.setTimeout(() => autosave.mutate(review), AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [review]);

  const included = new Set(review.include_pages ?? []);
  const setIncluded = async (pageId: string, on: boolean) => {
    const pages = new Set(review.include_pages ?? []);
    if (on) pages.add(pageId);
    else pages.delete(pageId);
    const next = { ...review, include_pages: [...pages] };
    setReview(next);
    await saveReview(token, session.id, next);  // the proposal reads it from the server
    queryClient.invalidateQueries({ queryKey: scanProposalPrefix(session.id) });
  };

  const discard = useMutation({
    mutationFn: () => discardSession(token, session.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SCAN_SESSIONS_QUERY_KEY });
      onBack();
    },
    onError: (error) => toast.error(label(S.failed), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const lineName = reference.workCenters.find((w) => w.id === session.work_center_id)?.name ?? "—";
  const validated = session.shift?.status === "validated";
  const open = session.status === "open";
  const shiftLink = `/production?tab=shift-report&line=${encodeURIComponent(session.work_center_id)}&date=${session.report_date}&shift=${encodeURIComponent(session.shift)}`;

  return (
    <div className="space-y-5">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 py-3">
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            {label(S.back)}
          </Button>
          <span className="font-medium">{`${lineName} · ${session.report_date} · ${session.shift}`}</span>
          {session.window && <span className="text-sm text-muted-foreground">{`${session.window.start}–${session.window.end}`}</span>}
          <Badge variant={open ? "warning" : "default"}>{label(SESSION_STATUS[session.status])}</Badge>
          {session.shift && <Badge variant={validated ? "destructive" : "primary"}>{label(SHIFT_STATUS[session.shift.status])}</Badge>}
          <div className="ml-auto flex gap-2">
            {session.shift_report_id && (
              <Button variant="outline" size="sm" onClick={() => navigate(shiftLink)}>{label(S.openShift)}</Button>
            )}
            {open && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => window.confirm(label(S.discardConfirm)) && discard.mutate()}
                disabled={discard.isPending}
              >
                <XCircle className="h-4 w-4" />
                {label(S.discard)}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {validated && open && (
        <p className="flex items-start gap-2 rounded-md bg-destructive-soft px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {label(S.validatedBlock)}
        </p>
      )}
      {session.status === "applied" && (
        <p className="flex items-center gap-2 rounded-md bg-success-soft px-3 py-2 text-sm text-success">
          <CheckCircle2 className="h-4 w-4" />
          {label(S.appliedCard)}
        </p>
      )}
      {session.status === "discarded" && <p className="text-sm text-muted-foreground">{label(S.discardedCard)}</p>}

      <PhotosPanel session={session} disabled={!open || validated} included={included} onInclude={setIncluded} />
      {open && !validated && session.pages.some((p) => p.status === "read") && (
        <ReviewPanel session={session} review={review} updateReview={updateReview} />
      )}
    </div>
  );
}
```

`ReviewPanel` is created in Task 22 (stub it `export function ReviewPanel(_: unknown) { return null; }` if committing before).

- [ ] **Step 4: Type-check**

Run: `npx tsc -b --force` — no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/scan
git commit -m "feat(scan): scan workspace — photos, their reading status, other-shift pages, autosaved review state"
```

---

### Task 22: The review panel and the photo viewer

**Files:**
- Create: `frontend/src/features/scan/ReviewPanel.tsx`, `frontend/src/features/scan/PhotoViewer.tsx`

**Interfaces:**
- Consumes: Tasks 17–19, 21 (`useUpright`, `usePageImage`); `SECTIONS`, `Part`, `useShiftReferenceData().buildOptions`.
- Produces: `ReviewPanel({ session, review, updateReview })`; `PhotoViewer({ page, source, flagged, onConfirm })`. `ApplyDialog` (Task 23) is opened from the review panel's bar.

- [ ] **Step 1: Write `PhotoViewer.tsx`**

```tsx
// frontend/src/features/scan/PhotoViewer.tsx
import { useState } from "react";
import { Check, ZoomIn } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { useLabel } from "../production/shift/shiftText";
import { usePageImage, useUpright } from "./PageImage";
import type { ScanPage, SourceEntry } from "./scanApi";
import { S } from "./scanText";

export function PhotoViewer({
  page, source, flagged, onConfirm,
}: { page: ScanPage | undefined; source: SourceEntry | undefined; flagged: boolean; onConfirm: () => void }) {
  const label = useLabel();
  if (!page) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">{label(S.noSource)}</CardContent>
      </Card>
    );
  }
  return <Viewer page={page} source={source} flagged={flagged} onConfirm={onConfirm} />;
}

function Viewer({ page, source, flagged, onConfirm }: { page: ScanPage; source: SourceEntry | undefined; flagged: boolean; onConfirm: () => void }) {
  const label = useLabel();
  const image = usePageImage(page.id);
  const src = useUpright(image.data, page.rotation);
  const [zoomed, setZoomed] = useState(true);
  const box = source?.box;
  const origin = box ? `${((box[0] + box[2]) / 2) * 100}% ${((box[1] + box[3]) / 2) * 100}%` : "50% 50%";
  return (
    <Card>
      <CardContent className="space-y-2 py-3">
        <div className="relative overflow-hidden rounded-md border border-border bg-muted">
          {src ? (
            <div className="relative transition-transform duration-300" style={{ transform: zoomed && box ? "scale(2.5)" : "none", transformOrigin: origin }}>
              <img src={src} alt={label(S.photo)} className="block w-full" />
              {box && (
                <div
                  className="absolute rounded-sm border-2 border-warning bg-warning/20"
                  style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }}
                />
              )}
            </div>
          ) : (
            <Skeleton className="h-72 w-full" />
          )}
        </div>
        {source && (
          <p className="text-sm">
            <span className="text-muted-foreground">{label(S.readAs)} </span>
            <span className="font-medium">{source.text}</span>
          </p>
        )}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setZoomed((z) => !z)} disabled={!box}>
            <ZoomIn className="h-3.5 w-3.5" />
            {label(S.zoom)}
          </Button>
          {flagged && (
            <Button size="sm" className={cn("ml-auto")} onClick={onConfirm}>
              <Check className="h-3.5 w-3.5" />
              {label(S.valueIsRight)}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Write `ReviewPanel.tsx`**

```tsx
// frontend/src/features/scan/ReviewPanel.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/utils";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label as FieldLabel } from "../../components/ui/label";
import { Skeleton } from "../../components/ui/skeleton";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { SECTIONS, type PartDef, type SectionDef } from "../production/shift/sectionConfig";
import { Part } from "../production/shift/SectionCard";
import { DECOR_CLASS, type CellDecor, type GridRow, type OptionMap } from "../production/shift/ShiftGrid";
import type { Row, SectionKey } from "../production/shift/shiftApi";
import { useLabel, type Label } from "../production/shift/shiftText";
import { useShiftReferenceData } from "../production/shift/useShiftReferenceData";
import { ApplyDialog } from "./ApplyDialog";
import { PhotoViewer } from "./PhotoViewer";
import {
  APPLY_ORDER, fieldPath, isBlocking, isEmpty, mergeProposal, missingRequired, openDoubts, rowRef, sameValue,
  sectionNotice, sectionsToWrite, valuesByPath, valuesFromProposal,
} from "./reviewModel";
import {
  getProposal, scanProposalPrefix, type Choice, type FlagEntry, type ReviewState, type SessionDetail, type SetAsideEntry,
  type ShiftSectionState,
} from "./scanApi";
import { REASONS, S, SECTION_STATUS } from "./scanText";

// Columns pointing at saved rows of the shift (a run, a packing row) cannot be chosen before the scan is saved.
const HIDDEN_OPTIONS = new Set(["runs", "packingRows"]);
const HEADER_FIELDS: [string, Label][] = [
  ["team", S.team], ["conducteur", S.conducteur], ["agent_fabrication", S.agent], ["machiniste", S.machiniste], ["aide_machiniste", S.aide],
];

export function ReviewPanel({
  session, review, updateReview,
}: { session: SessionDetail; review: ReviewState; updateReview: (change: (current: ReviewState) => ReviewState) => void }) {
  const { session: auth } = useAuth();
  const label = useLabel();
  const reference = useShiftReferenceData(true);
  const signature = `${session.pages.filter((p) => p.status === "read").map((p) => p.id).join(",")}|${(review.include_pages ?? []).join(",")}`;
  const query = useQuery({
    queryKey: [...scanProposalPrefix(session.id), signature],
    queryFn: () => getProposal(auth!.token, session.id),
    placeholderData: keepPreviousData,
  });
  const [active, setActive] = useState<string | null>(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const data = query.data;

  // A new reading refreshes the sections nobody touched; the first one starts (or restores) the working copy.
  const firstReading = useRef(true);
  useEffect(() => {
    if (!data) return;
    if (!firstReading.current) toast.info(label(S.newReading));
    firstReading.current = false;
    updateReview((current) => ({
      ...current,
      values: current.values ? mergeProposal(current.values, data.proposal, new Set(current.touched ?? [])) : valuesFromProposal(data.proposal),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const options = useMemo<OptionMap>(() => {
    const built = reference.buildOptions(undefined, session.work_center_id);
    // Before the scan is saved there are no saved runs or packed rows to narrow these lists by.
    return { ...built, shiftOrders: built.orders, packedProducts: built.finishedProducts };
  }, [reference.buildOptions, session.work_center_id]);
  const proposed = useMemo(() => (data ? valuesByPath(valuesFromProposal(data.proposal)) : new Map<string, unknown>()), [data]);

  if (!data || !review.values) return <Skeleton className="h-64 w-full" />;
  const { proposal, shift } = data;
  const values = review.values;
  const choices = review.choices ?? {};
  const confirmed = new Set(review.confirmed ?? []);
  const writing = sectionsToWrite(values, choices, shift);
  const doubts = openDoubts(proposal, values, confirmed, writing);
  const missing = missingRequired(values, SECTIONS, writing);

  const flagsAt = (path: string): FlagEntry[] => proposal.flags[path] ?? [];
  const isDoubt = (path: string, value: unknown) => flagsAt(path).length > 0 && !confirmed.has(path) && sameValue(value, proposed.get(path));
  const reasons = (path: string) =>
    flagsAt(path).map((f) => `${label(REASONS[f.reason] ?? S.toCheck)}${f.detail ? ` (${f.detail})` : ""}`).join(" · ");

  const setPart = (key: SectionKey, part: string, value: GridRow[] | Row) =>
    updateReview((current) => ({
      ...current,
      touched: [...new Set([...(current.touched ?? []), key])],
      values: { ...current.values!, sections: { ...current.values!.sections, [key]: { ...current.values!.sections[key], [part]: value } } },
    }));
  const setHeader = (field: string, value: string) =>
    updateReview((current) => ({ ...current, values: { ...current.values!, header: { ...current.values!.header, [field]: value || null } } }));
  const setChoice = (key: SectionKey, choice: Choice) => updateReview((current) => ({ ...current, choices: { ...current.choices, [key]: choice } }));
  const confirm = (path: string) => updateReview((current) => ({ ...current, confirmed: [...new Set([...(current.confirmed ?? []), path])] }));

  const activeSource = active ? proposal.sources[active]?.[0] : undefined;
  const activePage = session.pages.find((p) => p.id === activeSource?.page_id);
  const defs = SECTIONS.filter((def) => APPLY_ORDER.includes(def.key) && values.sections[def.key]);
  const excluded = Object.entries(proposal.pages).filter(([, p]) => p.importable && !p.included).length;

  return (
    <div className="space-y-4">
      <div className="sticky top-14 z-10 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-background/95 px-4 py-3 shadow-soft backdrop-blur">
        <div>
          <h3 className="font-semibold">{label(S.review)}</h3>
          <p className="text-xs text-muted-foreground">{label(S.reviewHint)}</p>
        </div>
        <Badge variant="warning">{`${doubts.length} ${label(S.toCheck)}`}</Badge>
        <Badge variant={missing.length ? "destructive" : "default"}>{`${missing.length} ${label(S.required)}`}</Badge>
        {excluded > 0 && <Badge variant="outline">{`${excluded} ${label(S.otherShift)}`}</Badge>}
        <Button className="ml-auto" onClick={() => setApplyOpen(true)} disabled={writing.length === 0}>
          <Save className="h-4 w-4" />
          {label(S.applyButton)}
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{label(S.header)}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {HEADER_FIELDS.map(([field, fieldLabel]) => {
                const path = fieldPath("header", "-", "-", field);
                const doubt = isDoubt(path, values.header[field]);
                return (
                  <div key={field} className={cn("space-y-1 rounded-md p-1", doubt && DECOR_CLASS.doubt)} title={doubt ? reasons(path) : undefined}>
                    <FieldLabel htmlFor={`scan-header-${field}`} className="text-xs text-muted-foreground">{label(fieldLabel)}</FieldLabel>
                    <Input
                      id={`scan-header-${field}`}
                      value={values.header[field] ?? ""}
                      onFocus={() => setActive(path)}
                      onChange={(e) => setHeader(field, e.target.value)}
                    />
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {defs.map((def) => (
            <SectionReview
              key={def.key}
              def={def}
              parts={values.sections[def.key]!}
              existing={shift?.sections[def.key]}
              choice={choices[def.key]}
              notices={flagsAt(sectionNotice(def.key))}
              setAside={(proposal.set_aside[def.key] ?? []).filter(
                (entry) => !((values.sections[def.key]?.[entry.part] as GridRow[] | undefined) ?? []).some((row) => row._scan_ref === entry.row._scan_ref),
              )}
              options={options}
              onChoice={(choice) => setChoice(def.key, choice)}
              onPart={(part, value) => setPart(def.key, part, value)}
              decorate={(part, row, key) => {
                const column = part.columns.find((c) => c.key === key);
                const path = fieldPath(def.key, part.payloadKey, part.shape === "rows" ? rowRef(row) : "-", key);
                if (column?.required && isEmpty(row[key])) {
                  return { tone: "required", title: label(isBlocking(def.key, part.payloadKey, key) ? S.requiredBlocking : S.requiredLater) };
                }
                if (isDoubt(path, row[key])) return { tone: "doubt", title: reasons(path) };
                return undefined;
              }}
              onFocus={(part, row, key) => setActive(fieldPath(def.key, part.payloadKey, part.shape === "rows" ? rowRef(row) : "-", key))}
            />
          ))}
        </div>

        <div className="lg:sticky lg:top-36 lg:self-start">
          <PhotoViewer
            page={activePage}
            source={activeSource}
            flagged={!!active && flagsAt(active).length > 0 && !confirmed.has(active)}
            onConfirm={() => active && confirm(active)}
          />
        </div>
      </div>

      <ApplyDialog
        open={applyOpen}
        onOpenChange={setApplyOpen}
        session={session}
        values={values}
        shift={shift}
        writing={writing}
        missing={missing}
        doubts={doubts.length}
      />
    </div>
  );
}

function SectionReview({
  def, parts, existing, choice, notices, setAside, options, onChoice, onPart, decorate, onFocus,
}: {
  def: SectionDef;
  parts: Record<string, GridRow[] | Row>;
  existing: ShiftSectionState | undefined;
  choice: Choice | undefined;
  notices: FlagEntry[];
  setAside: SetAsideEntry[];
  options: OptionMap;
  onChoice: (choice: Choice) => void;
  onPart: (part: string, value: GridRow[] | Row) => void;
  decorate: (part: PartDef, row: Row, key: string) => CellDecor | undefined;
  onFocus: (part: PartDef, row: Row, key: string) => void;
}) {
  const label = useLabel();
  const Icon = def.icon;
  const filled = (existing?.rows ?? 0) > 0;
  const keeping = filled && choice !== "replace";
  return (
    <Card className={cn(keeping && "opacity-70")}>
      <CardContent className="space-y-3 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Icon className="h-4 w-4 text-primary" />
          <h3 className="font-medium">{label(def.title)}</h3>
          {filled && (
            <>
              <Badge variant="warning">{`${label(S.existingRows)} ${existing!.rows} · ${label(SECTION_STATUS[existing!.status])}`}</Badge>
              <FilterTabs
                value={keeping ? "keep" : "replace"}
                onChange={(value) => onChoice(value as Choice)}
                options={[
                  { value: "keep", label: label(S.keep) },
                  { value: "replace", label: label(S.replace) },
                ]}
              />
            </>
          )}
        </div>
        {notices.map((notice) => (
          <p key={notice.reason} className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">{label(REASONS[notice.reason] ?? S.toCheck)}</p>
        ))}
        {keeping ? (
          <p className="text-sm text-muted-foreground">{label(S.keptHint)}</p>
        ) : (
          def.parts
            .filter((part) => parts[part.payloadKey] !== undefined)
            .map((part) => {
              const shown = { ...part, columns: part.columns.filter((c) => !HIDDEN_OPTIONS.has(c.options ?? "")) };
              return (
                <Part
                  key={part.payloadKey}
                  part={shown}
                  sectionKey={`scan-${def.key}`}
                  value={parts[part.payloadKey]}
                  onChange={(value) => onPart(part.payloadKey, value)}
                  options={options}
                  disabled={false}
                  decorate={(row, key) => decorate(shown, row, key)}
                  onCellFocus={(row, key) => onFocus(shown, row, key)}
                />
              );
            })
        )}
        {!keeping && setAside.length > 0 && (
          <div className="space-y-2 rounded-md border border-dashed border-warning/60 p-3">
            <p className="text-xs font-medium text-warning">{label(S.setAsideTitle)}</p>
            {setAside.map((entry) => (
              <div key={String(entry.row._scan_ref)} className="flex flex-wrap items-center gap-2 text-sm">
                <span>{`${entry.row.quantity ?? "—"} kg · ${entry.row.lot_number ?? ""} · ${entry.row.note ?? ""}`}</span>
                <span className="text-xs text-muted-foreground">{label(REASONS[entry.reason] ?? S.toCheck)}</span>
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  onClick={() => {
                    const rows = (parts[entry.part] as GridRow[] | undefined) ?? [];
                    onPart(entry.part, [...rows, { ...entry.row, _key: String(entry.row._scan_ref) }]);
                  }}
                >
                  {label(S.addBack)}
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

(Check the `Part` component's `value`/`onChange` types: it takes `GridRow[] | Row` — as used above. `ApplyDialog` comes in Task 23; stub it if committing before.)

- [ ] **Step 3: Type-check**

Run: `npx tsc -b --force` — no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/scan
git commit -m "feat(scan): review panel with yellow doubts, red required values and the photo beside the form"
```

---

### Task 23: Apply dialog, the dictionary, and the photos on the shift report

**Files:**
- Create: `frontend/src/features/scan/ApplyDialog.tsx`, `frontend/src/features/scan/AliasesTable.tsx`, `frontend/src/features/scan/ShiftPaperPages.tsx`
- Modify: `frontend/src/features/production/shift/ShiftReportTab.tsx` (title area)

**Interfaces:**
- Consumes: Tasks 17–22; `SHIFT_REPORTS_QUERY_KEY`.
- Produces: `ApplyDialog({ open, onOpenChange, session, values, shift, writing, missing, doubts })`; `AliasesTable()`; `ShiftPaperPages({ shiftReportId })`.

- [ ] **Step 1: Write `ApplyDialog.tsx`**

```tsx
// frontend/src/features/scan/ApplyDialog.tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { SECTIONS } from "../production/shift/sectionConfig";
import { SHIFT_REPORTS_QUERY_KEY, type SectionKey } from "../production/shift/shiftApi";
import { useLabel } from "../production/shift/shiftText";
import { APPLY_ORDER, applyBody, type Missing } from "./reviewModel";
import { applySession, SCAN_QUERY_KEY, type ReviewValues, type SessionDetail, type ShiftState } from "./scanApi";
import { S } from "./scanText";

export function ApplyDialog({
  open, onOpenChange, session, values, shift, writing, missing, doubts,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: SessionDetail;
  values: ReviewValues;
  shift: ShiftState | null;
  writing: SectionKey[];
  missing: Missing[];
  doubts: number;
}) {
  const { session: auth } = useAuth();
  const label = useLabel();
  const queryClient = useQueryClient();
  const blocking = missing.filter((m) => m.blocking);
  const later = missing.length - blocking.length;
  const title = (key: SectionKey) => label(SECTIONS.find((d) => d.key === key)!.title);

  const apply = useMutation({
    mutationFn: () => applySession(auth!.token, session.id, applyBody(values, writing, shift)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SCAN_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: SHIFT_REPORTS_QUERY_KEY });
      toast.success(label(S.applied));
      onOpenChange(false);
    },
    onError: (error) => toast.error(label(S.failed), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const outcome = (key: SectionKey) => {
    const existing = shift?.sections[key];
    if (!writing.includes(key)) return label(S.keptExisting);
    if (!existing || existing.rows === 0) return label(S.writeNew);
    return label(existing.status === "submitted" ? S.replaceSubmitted : S.replaceDraft);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{label(S.applyTitle)}</DialogTitle>
          <DialogDescription>{label(S.applyHint)}</DialogDescription>
        </DialogHeader>
        <ul className="space-y-1 text-sm">
          {APPLY_ORDER.filter((key) => values.sections[key]).map((key) => (
            <li key={key} className="flex justify-between gap-3">
              <span className="font-medium">{title(key)}</span>
              <span className="text-muted-foreground">{outcome(key)}</span>
            </li>
          ))}
        </ul>
        {blocking.length > 0 && (
          <div className="rounded-md bg-destructive-soft px-3 py-2 text-sm text-destructive">
            <p className="font-medium">{label(S.blockingTitle)}</p>
            <ul className="list-disc pl-5">
              {blocking.map((m) => (
                <li key={`${m.section}-${m.ref}-${m.column.key}`}>{`${title(m.section)} — ${label(m.column.label)}`}</li>
              ))}
            </ul>
          </div>
        )}
        {later > 0 && <p className="text-sm text-muted-foreground">{`${later} — ${label(S.requiredLater)}`}</p>}
        {doubts > 0 && <p className="text-sm text-warning">{`${doubts} ${label(S.doubtsLeft)}`}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>{label(S.cancel)}</Button>
          <Button onClick={() => apply.mutate()} disabled={blocking.length > 0 || writing.length === 0 || apply.isPending}>
            {apply.isPending ? label(S.saving) : label(S.confirmSave)}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Write `AliasesTable.tsx`**

```tsx
// frontend/src/features/scan/AliasesTable.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookA, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { useLabel } from "../production/shift/shiftText";
import { deleteAlias, getVocabulary, listAliases, SCAN_ALIASES_QUERY_KEY, updateAlias, type Alias } from "./scanApi";
import { KIND_LABELS, S } from "./scanText";

export function AliasesTable() {
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const queryClient = useQueryClient();
  const canEdit = hasPermission("scan.admin_aliases");
  const [kind, setKind] = useState<string>("all");
  const [editing, setEditing] = useState<Alias | null>(null);
  const [target, setTarget] = useState("");
  const { data: aliases = [], isLoading } = useQuery({ queryKey: SCAN_ALIASES_QUERY_KEY, queryFn: () => listAliases(token) });
  const vocabulary = useQuery({ queryKey: ["scan", "vocabulary", "all"], queryFn: () => getVocabulary(token) });
  const valueLabel = (alias: Alias) =>
    vocabulary.data?.[alias.kind]?.find((option) => option.value === alias.target_value)?.label ?? alias.target_value;
  const refresh = () => queryClient.invalidateQueries({ queryKey: SCAN_ALIASES_QUERY_KEY });
  const fail = (error: unknown) => toast.error(label(S.failed), { description: error instanceof ApiError ? error.message : undefined });
  const save = useMutation({
    mutationFn: () => updateAlias(token, editing!.id, target),
    onSuccess: () => { refresh(); setEditing(null); },
    onError: fail,
  });
  const remove = useMutation({ mutationFn: (id: string) => deleteAlias(token, id), onSuccess: refresh, onError: fail });

  const filterFields: FilterField<Alias>[] = [
    { key: "written", kind: "text", getValue: (a) => a.raw_text_example },
    { key: "value", kind: "text", getValue: (a) => valueLabel(a) },
    { key: "uses", kind: "range", getValue: (a) => a.use_count },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const rows = columnFilters.apply(kind === "all" ? aliases : aliases.filter((a) => a.kind === kind));
  const kinds = [...new Set(aliases.map((a) => a.kind))];

  const columns: ColumnDef<Alias>[] = [
    { key: "kind", header: label(S.kind), defaultWidth: 170, cell: (a) => <Badge variant="outline">{label(KIND_LABELS[a.kind] ?? S.kind)}</Badge> },
    {
      key: "written", header: label(S.written), defaultWidth: 200, cell: (a) => <span className="font-medium">{a.raw_text_example}</span>,
      sortValue: (a) => a.raw_text_normalized,
      filterCell: { type: "text", value: columnFilters.text.written ?? "", onChange: (v) => columnFilters.setTextValue("written", v), placeholder: label(S.written) },
    },
    {
      key: "value", header: label(S.value), defaultWidth: 240, cell: valueLabel, sortValue: valueLabel,
      filterCell: { type: "text", value: columnFilters.text.value ?? "", onChange: (v) => columnFilters.setTextValue("value", v), placeholder: label(S.value) },
    },
    {
      key: "uses", header: label(S.uses), defaultWidth: 110, cell: (a) => a.use_count, sortValue: (a) => a.use_count,
      filterCell: {
        type: "range", min: columnFilters.range.uses?.min ?? "", max: columnFilters.range.uses?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("uses", "min", v), onMaxChange: (v) => columnFilters.setRangeValue("uses", "max", v),
      },
    },
    { key: "updated", header: label(S.updated), defaultWidth: 170, cell: (a) => new Date(a.updated_at).toLocaleString(), sortValue: (a) => a.updated_at },
    {
      key: "action", header: "", defaultWidth: 180, alwaysVisible: true, cellClassName: "text-right",
      cell: (a) =>
        canEdit ? (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="outline" onClick={() => { setEditing(a); setTarget(a.target_value); }}>
              <Pencil className="h-3.5 w-3.5" />
              {label(S.edit)}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => remove.mutate(a.id)} aria-label={label(S.delete)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : null,
    },
  ];
  const table = useTableColumns("scan.aliases", columns);
  const sorted = table.sortRows(rows);
  const choices = editing ? vocabulary.data?.[editing.kind] ?? [] : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle>{label(S.viewDictionary)}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{label(S.dictionaryHint)}</p>
          </div>
          <FilterTabs
            value={kind}
            onChange={setKind}
            options={[{ value: "all", label: label(S.all) }, ...kinds.map((k) => ({ value: k, label: label(KIND_LABELS[k] ?? S.kind) }))]}
          />
          {columnFilters.isActive && <Button variant="ghost" size="sm" onClick={columnFilters.reset}>{label(S.clearFilters)}</Button>}
          <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <Table colWidths={table.colWidths}>
          <TableHeader>
            <TableRow>
              {table.visibleColumns.map((column) => (
                <ResizableTableHead
                  key={column.key}
                  width={table.getWidth(column.key)}
                  onResize={(width) => table.setWidth(column.key, width)}
                  sortDirection={table.sortDirectionFor(column.key)}
                  onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                >
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
          </TableHeader>
          <TableBody>
            {isLoading && <TableLoadingRow colSpan={table.visibleColumns.length} />}
            {!isLoading && sorted.length === 0 && (
              <TableRow>
                <TableCell colSpan={table.visibleColumns.length} className="p-0">
                  <EmptyState icon={<BookA className="h-5 w-5" />} title={label(S.noAliases)} description="" />
                </TableCell>
              </TableRow>
            )}
            {sorted.map((row) => (
              <TableRow key={row.id}>
                {table.visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>{column.cell(row)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>

      <Dialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{`${label(S.edit)} — ${editing?.raw_text_example ?? ""}`}</DialogTitle>
          </DialogHeader>
          {choices.length > 0 ? (
            <Select value={target} onChange={(e) => setTarget(e.target.value)}>
              {choices.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </Select>
          ) : (
            <Input value={target} onChange={(e) => setTarget(e.target.value)} />
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setEditing(null)}>{label(S.cancel)}</Button>
            <Button onClick={() => save.mutate()} disabled={!target.trim() || save.isPending}>{label(S.save)}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
```

- [ ] **Step 3: Write `ShiftPaperPages.tsx`**

```tsx
// frontend/src/features/scan/ShiftPaperPages.tsx
import { useQuery } from "@tanstack/react-query";
import { Images } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../../components/ui/dialog";
import { useLabel } from "../production/shift/shiftText";
import { PageImage } from "./PageImage";
import { listShiftPages } from "./scanApi";
import { FORM_LABELS, S } from "./scanText";

/** The paper fiches a shift report was filled from, for whoever checks or validates it. */
export function ShiftPaperPages({ shiftReportId }: { shiftReportId: string }) {
  const { session } = useAuth();
  const label = useLabel();
  const pages = useQuery({ queryKey: ["scan", "shift-pages", shiftReportId], queryFn: () => listShiftPages(session!.token, shiftReportId) });
  if (!pages.data?.length) return null;
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Images className="h-4 w-4" />
          {`${label(S.paperPages)} (${pages.data.length})`}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>{label(S.paperPages)}</DialogTitle>
        </DialogHeader>
        <div className="grid max-h-[75vh] gap-3 overflow-y-auto sm:grid-cols-2">
          {pages.data.map((page) => (
            <figure key={page.id} className="space-y-1">
              <PageImage pageId={page.id} rotation={page.rotation} alt={label(S.photo)} className="w-full rounded-md border border-border" />
              <figcaption className="text-xs text-muted-foreground">{page.form_type ? label(FORM_LABELS[page.form_type]) : "—"}</figcaption>
            </figure>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Add the entry points to `ShiftReportTab.tsx`**

Add imports:

```ts
import { useNavigate } from "react-router-dom";
import { ScanLine } from "lucide-react";
import { ShiftPaperPages } from "../../scan/ShiftPaperPages";
import { S as SCAN_TEXT } from "../../scan/scanText";
```

(merge `useNavigate` into the existing `react-router-dom` import and `ScanLine` into the lucide one), `const navigate = useNavigate();` next to the other hooks, and replace the title block

```tsx
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <ClipboardList className="h-5 w-5 text-primary" />
          {label(T.title)}
        </h2>
        <p className="text-sm text-muted-foreground">{label(T.subtitle)}</p>
      </div>
```

with

```tsx
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            <ClipboardList className="h-5 w-5 text-primary" />
            {label(T.title)}
          </h2>
          <p className="text-sm text-muted-foreground">{label(T.subtitle)}</p>
        </div>
        <div className="flex gap-2">
          {shift && (hasPermission("scan.view_scans") || hasPermission("scan.use_scanner")) && <ShiftPaperPages shiftReportId={shift.id} />}
          {hasPermission("scan.use_scanner") && shift?.status !== "validated" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                navigate(`/production?tab=scan&line=${encodeURIComponent(workCenterId)}&date=${date}&shift=${encodeURIComponent(shiftName)}`)
              }
            >
              <ScanLine className="h-4 w-4" />
              {label(SCAN_TEXT.importFromPhotos)}
            </Button>
          )}
        </div>
      </div>
```

- [ ] **Step 5: Type-check and run the frontend tests**

Run: `npx tsc -b --force` then `npx vitest run src/features/scan`
Expected: no errors; PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/scan frontend/src/features/production/shift/ShiftReportTab.tsx
git commit -m "feat(scan): apply dialog, the dictionary screen, and the paper fiches on the shift report"
```

---

### Task 24: End-to-end verification in the browser

**Files:** none (verification only; fix what it finds in the task that owns the code).

- [ ] **Step 1: Run everything**

Backend (from `backend/`): `.venv/Scripts/python -m pytest modules/scan modules/production -q` — PASS, and check the scan tests ran (not skipped).
OCR (from `ocr/`): `python -m pytest tests -q` with `OCR_FIXTURES_DIR` set — PASS.
Frontend (from `frontend/`): `npx tsc -b --force` and `npx vitest run` — PASS.

- [ ] **Step 2: Start the stack locally**

Run the OCR container (`docker run --rm -d -p 8100:8100 --memory=1536m --cpus=2 --name ocr-local erpsonalim-ocr:local`), then the backend API, the worker with `OCR_URL=http://localhost:8100`, and the frontend dev server, as the "Verify frontend changes" memory describes. Grant the demo user `scan.use_scanner`, `scan.view_scans`, `scan.admin_aliases` (`POST /core/users/{id}/permissions`) — new permissions are not auto-granted.

- [ ] **Step 3: Walk the golden path with the example photos**

In a private headless Chrome (never the shared Playwright session — see the "Shared worktree" memory):
1. Production → Scanner → pick line PC, 2026-09-07, the morning shift, an open OF → Commencer le scan.
2. Add the three photos. Within ~1–2 min: fabrication and conditionnement pages `Lue`, the bobines page `Autre shift — autres heures` with "Fiche reconnue — pas encore importée".
3. The review shows the sections; the run lot is yellow ("La date du lot n'est pas celle du shift (2026-09-06)"); clicking it shows the photo zoomed on the lot; "La valeur est correcte" clears it.
4. The unknown `B05I` versement is yellow; pick a raw material; the finished-product loss 75,25 appears under "Mis de côté" in Déchets conditionnement.
5. Enregistrer → the dialog lists the sections and blocks while a waste category is empty (red); fill it; save.
6. Open the shift report: the sections are drafts with the values; "Fiches papier (3)" shows the photos.
7. Start a new scan for the same shift with the same photos: `B05I` now resolves by itself (learned), and the dictionary lists it.

- [ ] **Step 4: Edge cases**

- A shift that already has typed stops: the Arrêts section shows "Déjà rempli" with *Garder l'existant* selected; saving leaves the typed stops untouched; switching to *Remplacer* replaces them.
- Type in the shift form in another tab after opening the review, then save the scan: the error names the changed section (`SECTION_CHANGED`).
- A validated shift: the start screen refuses, and "Importer depuis des photos" is hidden on it.
- Stop the OCR container while a photo is queued: the page shows the "service indisponible" line, and reads once the container is back.
- The shift form (Fiche de shift) still behaves exactly as before.

- [ ] **Step 5: Report**

Tell the user what was verified, the OCR accuracy score from `ocr/README.md`, and anything that did not work. Do not push.

