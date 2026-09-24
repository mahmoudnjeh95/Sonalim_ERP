# QC on the shift report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repoint QC's quality report from the retired legacy conditionnement report onto `production.shift_reports`, move conformity from one total per report to one line per product packed that shift, add the "Contrôle des paramètres" capture (9 instrument groups) to the QC report, and cap the Libéré dialog's releasable quantity at what QC has validated as conforming.

**Architecture:** One QC report per shift report (1:1, keyed by `shift_report_id`). A new `qc.quality_conformity_lines` table replaces the report-wide conforming/non-conforming/defect columns, one row per `shift_packing_row`. A new `qc.quality_parameters` table (JSONB fields per group, domain-validated) holds the paramètres readings. `qc.quality_follow_ups` gains a line-scoped `of_id`/`conformity_line_id` so the 40-day window still opens per product/OF. Production's `StockReleaseService` calls into a new `QualityReportService.get_validated_conforming` read, the same cross-module call direction `get_conformity_summary` already uses, and enforces the cap both in the list it returns and inside `release()` itself.

**Tech Stack:** FastAPI + psycopg (raw SQL), pytest with the `db` fixture (real Postgres, rolled back per test), React 18 + TS + TanStack Query + React Hook Form + Zod, Vitest/`tsc -b --force` for frontend verification.

**Spec:** `docs/superpowers/specs/2026-09-24-qc-shift-based-design.md`

## Global Constraints

- Modules never read each other's tables directly — QC reaches production only through a service call (mirrors today's `_resolve_conditionnement` → `ProductionReportService`); production reaches QC only through a service call (mirrors today's `get_conformity_summary` direction, reversed).
- Every new/changed migration file gets the next unused number in its module (`qc/migrations/0005...`, no gaps, never edit an applied file).
- Router errors raise `HTTPException(detail={"code", "message"})`, matching `_err_status` in `backend/modules/qc/api/router.py`.
- New/changed UI strings go through `frontend/src/lib/i18n.tsx` with both `en` and `fr` keys.
- No real QC production data exists — migrations truncate `qc.quality_reports` and children instead of converting (spec decision 7). Do not write a conversion function.
- The five process indices (`pre_dryer_index`, `humidity_percentage`, `cooling_index`, `pf_index`, `sumo_index`) are deleted, not deprecated — remove every reference, don't leave nullable dead columns "just in case."
- `StockReleaseService.release()` must enforce the QC cap server-side, not only in the read path (`get_release_list`) — a forged/stale request must still be refused.

## Review Focus

- **A shift packed by two different OFs, one with an open non-conformity and one without** — rejecting the QC report must clean up only the NC(s) linked to that shift's own conformity lines, never touch NCs from another shift or another OF. (Task 6)
- **A product packed on a validated shift whose QC report is still `draft`/`submitted`** — the Libéré dialog must show it as `pending_qc`, never as `releasable`, even though the shift itself already posted stock. (Task 11)
- **A `release()` call built from a stale/forged payload that exceeds QC-validated conforming quantity** but is still within on-hand and packed-minus-released — must be refused with a clear error, not silently allowed because the read path's cap was bypassed. (Task 11)
- **A conformity line with `non_conforming_cartons > 0` and empty `defect_details`** — refused at both `create/update_draft` and `submit_report`, per line, matching today's `MISSING_DEFECT_DETAILS` behavior just scoped to the line instead of the whole report. (Task 3, Task 4)
- **A parameter entry with a field outside its group's declared numeric range** (e.g. a percentage over 100, a negative pressure where the paper sheet only ever records positive values) — refused by `validate_parameter_entry`, not silently stored as-is. (Task 2, Task 5)

---

## File structure

New/changed files, by responsibility:

- `backend/modules/qc/migrations/0005_qc_shift_reports.sql` — schema: drop legacy columns/indexes, add `shift_report_id`, create `quality_conformity_lines`, alter `quality_follow_ups`, truncate existing QC data.
- `backend/modules/qc/migrations/0006_qc_parameters.sql` — `quality_parameters` table.
- `backend/modules/qc/domain/quality.py` — trimmed `QualityReport`/`QualityReportDetail`, new `ConformityLine`, per-line validation, `is_conforming(lines)`.
- `backend/modules/qc/domain/parameters.py` — new: the nine groups' field schemas and `validate_parameter_entry`.
- `backend/modules/qc/domain/test_quality.py` — updated for the new dataclasses/validation.
- `backend/modules/qc/domain/test_parameters.py` — new.
- `backend/modules/qc/api/quality_service.py` — `_resolve_shift` replaces `_resolve_conditionnement`; conformity-line CRUD; parameters CRUD; `get_validated_conforming`; rewritten `get_conformity_summary`/`_reports_needing_nc`/`team_conformity`/`index_trend`.
- `backend/modules/qc/api/non_conformity_service.py` — `_quantity_from_quality_report` reads the conformity line instead of the report detail.
- `backend/modules/qc/api/router.py` — request/response models and routes updated for the new shapes; `/conditionnement-reports` → `/shift-reports`; new `/quality-reports/{id}/parameters` routes.
- `backend/modules/qc/api/test_qc_flow_integration.py`, `test_team_conformity_integration.py`, `test_disposition_summary_integration.py` — ported fixtures (shift-based instead of conditionnement-based).
- `backend/modules/qc/api/test_parameters_integration.py` — new.
- `backend/modules/production/api/stock_release_service.py` — QC cap in `_list_for` and `release()`.
- `backend/modules/production/api/test_stock_release_integration.py` — new cases for the QC cap.
- `backend/scripts/seed_qc_month.py` — rewritten against shift reports.
- `frontend/src/features/qc/api.ts` — types + endpoints for the new shapes.
- `frontend/src/features/qc/QualityReportsTab.tsx` — conformity-lines table, parameters section, dropped index fields.
- `frontend/src/features/qc/QualityDashboardTab.tsx`, `frontend/src/features/analytics/TeamPerformanceTab.tsx`, `frontend/src/features/production/ValidationCenterTab.tsx`, `frontend/src/features/production/ProductionDashboardTab.tsx`, `frontend/src/features/production/board/QualityBlock.tsx` — updated to new response shapes.
- `frontend/src/features/production/board/api.ts` — `ReleaseItem.pending_qc`.
- `frontend/src/features/production/board/ReleaseStockDialog.tsx` — shows `pending_qc`.
- `frontend/src/lib/i18n.tsx` — new/changed strings (fr/en).

---

## Task 1: Schema — repoint quality_reports to shift reports, add conformity lines

**Files:**
- Create: `backend/modules/qc/migrations/0005_qc_shift_reports.sql`
- Test: manual — run the migration against the test DB and inspect via `psql`/pytest fixture in Task 3.

**Interfaces:**
- Produces: `qc.quality_reports.shift_report_id TEXT NOT NULL`, unique `(tenant_id, shift_report_id)`. `qc.quality_conformity_lines(id, tenant_id, report_id, shift_packing_row_id, of_id, product_id, conforming_cartons, non_conforming_cartons, defect_details, created_at, updated_at)`. `qc.quality_follow_ups.conformity_line_id TEXT`.

- [ ] **Step 1: Write the migration**

```sql
-- QC reports move off the retired legacy conditionnement report onto the shift
-- report the team actually files today (huge_production_migration cutover).
-- No real QC data exists yet (client decision, 2026-09-24), so this truncates
-- rather than converts.

TRUNCATE TABLE qc.nc_dispositions CASCADE;
TRUNCATE TABLE qc.non_conformities CASCADE;
TRUNCATE TABLE qc.quality_follow_ups CASCADE;
TRUNCATE TABLE qc.quality_report_details CASCADE;
TRUNCATE TABLE qc.quality_reports CASCADE;

-- ---- quality_reports: drop the legacy link and per-report of_id, add shift_report_id ----

DROP INDEX IF EXISTS qc.quality_reports_conditionnement_idx;
DROP INDEX IF EXISTS qc.quality_reports_one_per_conditionnement;
DROP INDEX IF EXISTS qc.quality_reports_of_idx;

ALTER TABLE qc.quality_reports
    DROP COLUMN IF EXISTS conditionnement_report_id,
    DROP COLUMN IF EXISTS of_id,
    ADD COLUMN shift_report_id TEXT NOT NULL;

CREATE UNIQUE INDEX quality_reports_one_per_shift_report
    ON qc.quality_reports (tenant_id, shift_report_id);

-- ---- quality_report_details: keep only the report-wide notes ----

ALTER TABLE qc.quality_report_details
    DROP COLUMN IF EXISTS pre_dryer_index,
    DROP COLUMN IF EXISTS humidity_percentage,
    DROP COLUMN IF EXISTS cooling_index,
    DROP COLUMN IF EXISTS pf_index,
    DROP COLUMN IF EXISTS sumo_index,
    DROP COLUMN IF EXISTS conforming_cartons,
    DROP COLUMN IF EXISTS non_conforming_cartons,
    DROP COLUMN IF EXISTS defect_details;

-- ---- quality_conformity_lines: one row per product packed that shift ----

CREATE TABLE qc.quality_conformity_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES qc.quality_reports (id),
    -- Opaque reference into production.shift_packing_rows -- no cross-module FK.
    shift_packing_row_id TEXT NOT NULL,
    of_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    conforming_cartons NUMERIC NOT NULL DEFAULT 0,
    non_conforming_cartons NUMERIC NOT NULL DEFAULT 0,
    defect_details TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX quality_conformity_lines_one_per_row
    ON qc.quality_conformity_lines (tenant_id, shift_packing_row_id);
CREATE INDEX quality_conformity_lines_report_idx
    ON qc.quality_conformity_lines (tenant_id, report_id);
CREATE INDEX quality_conformity_lines_of_idx
    ON qc.quality_conformity_lines (tenant_id, of_id);

-- ---- quality_follow_ups: line-scoped, so a multi-product shift opens one window per product ----

ALTER TABLE qc.quality_follow_ups
    ADD COLUMN conformity_line_id TEXT REFERENCES qc.quality_conformity_lines (id);
```

- [ ] **Step 2: Apply and sanity-check locally**

Run: `.venv/Scripts/python -m pytest modules/qc -q` from `backend/` (this fails at this point — services still reference dropped columns — that's expected until Task 2-4 land; the goal of this step is only to confirm the migration itself applies without a SQL error, which a full-suite run will surface even though later steps in that run fail on schema mismatches).

Expected: migration applies cleanly; failures after this point are `column ... does not exist` in `quality_service.py`/`non_conformity_service.py`, not a migration error. If you see a migration/SQL error itself, fix the migration before continuing.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/qc/migrations/0005_qc_shift_reports.sql
git commit -m "feat(qc): schema for shift-based quality reports and per-product conformity lines

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Schema — quality_parameters (Contrôle des paramètres)

**Files:**
- Create: `backend/modules/qc/migrations/0006_qc_parameters.sql`

**Interfaces:**
- Produces: `qc.quality_parameters(id, tenant_id, report_id, group_key, entry_label, fields JSONB, created_at)`.

- [ ] **Step 1: Write the migration**

```sql
-- The Contrôle des paramètres paper sheet: nine instrument groups, each a
-- small table of rows the QC team fills after the shift. Every group is a
-- rows-list (a free "heure" or machine number as entry_label, plus that
-- group's own fixed fields) rather than a fixed 2-3-slot snapshot, because
-- the paper sheet's row counts and times vary shift to shift.
--
-- fields is JSONB rather than one table per group: nine groups of 4-10
-- columns each is a lot of schema for data only the QC screen reads, and the
-- domain layer (modules/qc/domain/parameters.py) validates each group's
-- fixed field list and ranges just as strictly as fixed columns would.
CREATE TABLE qc.quality_parameters (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES qc.quality_reports (id),
    group_key TEXT NOT NULL CHECK (group_key IN (
        'presse', 'pompe_vide', 'sechage', 'chaudiere', 'compresseurs',
        'traitement_eau', 'chiller', 'additif', 'proprete_locaux'
    )),
    -- Free time ("07h38") for most groups; a machine/press number for
    -- presse and compresseurs; PL/PC for additif.
    entry_label TEXT,
    fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX quality_parameters_report_idx
    ON qc.quality_parameters (tenant_id, report_id);
```

- [ ] **Step 2: Apply and sanity-check**

Run: `.venv/Scripts/python -m pytest modules/qc -q` (same expectation as Task 1 Step 2 — migration must apply cleanly; downstream failures are expected until later tasks).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/qc/migrations/0006_qc_parameters.sql
git commit -m "feat(qc): schema for Contrôle des paramètres entries

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: Domain — quality.py trimmed, ConformityLine, per-line validation

**Files:**
- Modify: `backend/modules/qc/domain/quality.py`
- Modify: `backend/modules/qc/domain/test_quality.py`

**Interfaces:**
- Consumes: nothing new (pure domain).
- Produces: `QualityReport(id, shift_report_id, report_date, status, revision, team, shift, created_by, submitted_at, validated_by, validated_at, rejection_reason)` (no `of_id`, no `product_id`, no `conditionnement_report_id`). `QualityReportDetail(comments, corrective_action)`. `ConformityLine(id, report_id, shift_packing_row_id, of_id, product_id, conforming_cartons, non_conforming_cartons, defect_details)`. `validate_conformity_line(line: ConformityLine) -> Result[None]`. `is_conforming(lines: list[ConformityLine]) -> bool`.

- [ ] **Step 1: Write the failing tests**

Replace the existing `validate_quality_detail`/`is_conforming` tests in `backend/modules/qc/domain/test_quality.py` with per-line equivalents. Read the current file first (`Read backend/modules/qc/domain/test_quality.py`) to keep its other tests (transitions, follow-up window) untouched, then add/replace:

```python
from modules.qc.domain.quality import ConformityLine, is_conforming, validate_conformity_line


def _line(**overrides) -> ConformityLine:
    base = dict(
        id="line-1", report_id="report-1", shift_packing_row_id="row-1",
        of_id="of-1", product_id="product-1", conforming_cartons=10, non_conforming_cartons=0,
        defect_details=None,
    )
    base.update(overrides)
    return ConformityLine(**base)


def test_negative_conforming_cartons_is_rejected():
    result = validate_conformity_line(_line(conforming_cartons=-1))
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_non_integer_cartons_is_rejected():
    result = validate_conformity_line(_line(conforming_cartons=10.5))
    assert isinstance(result, Err)
    assert result.code == "QUANTITY_MUST_BE_INTEGER"


def test_non_conforming_cartons_requires_defect_details():
    result = validate_conformity_line(_line(non_conforming_cartons=3, defect_details=""))
    assert isinstance(result, Err)
    assert result.code == "MISSING_DEFECT_DETAILS"


def test_non_conforming_cartons_with_defect_details_is_valid():
    result = validate_conformity_line(_line(non_conforming_cartons=3, defect_details="soudure défectueuse"))
    assert isinstance(result, Ok)


def test_is_conforming_true_when_every_line_has_zero_defects():
    lines = [_line(id="a"), _line(id="b")]
    assert is_conforming(lines) is True


def test_is_conforming_false_when_any_line_has_a_defect():
    lines = [_line(id="a"), _line(id="b", non_conforming_cartons=1, defect_details="x")]
    assert is_conforming(lines) is False


def test_is_conforming_true_for_empty_lines():
    assert is_conforming([]) is True
```

(`Err`/`Ok` are already imported at the top of the test file from `core.domain.result` — confirm and reuse the existing import line rather than adding a duplicate.)

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `.venv/Scripts/python -m pytest modules/qc/domain/test_quality.py -q`
Expected: FAIL — `ImportError: cannot import name 'ConformityLine'` (or similar) since the domain module hasn't changed yet.

- [ ] **Step 3: Rewrite `backend/modules/qc/domain/quality.py`**

```python
from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from core.domain.result import Err, Ok, Result

QUALITY_REPORT_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"validated", "rejected"},
    "rejected": {"draft"},
    "validated": set(),
}

FOLLOW_UP_TRANSITIONS = {
    "open": {"in_progress", "completed"},
    "in_progress": {"completed"},
    "completed": set(),
}

DEFAULT_FOLLOW_UP_WINDOW_DAYS = 40


@dataclass(frozen=True)
class QualityReport:
    id: str
    shift_report_id: str
    report_date: datetime.date
    status: str
    revision: int
    team: str | None = None
    shift: str | None = None
    created_by: str | None = None
    submitted_at: datetime.datetime | None = None
    validated_by: str | None = None
    validated_at: datetime.datetime | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class QualityReportDetail:
    """Shift-wide notes. Conformity itself lives on ConformityLine, one per product."""

    comments: str | None = None
    corrective_action: str | None = None


@dataclass(frozen=True)
class ConformityLine:
    id: str
    report_id: str
    shift_packing_row_id: str
    of_id: str
    product_id: str
    conforming_cartons: float = 0
    non_conforming_cartons: float = 0
    defect_details: str | None = None


@dataclass(frozen=True)
class FollowUp:
    id: str
    quality_report_id: str
    of_id: str
    conformity_line_id: str | None
    window_ends_on: datetime.date
    observed_on: datetime.date
    status: str
    result: str | None = None
    observation: str | None = None
    actor_id: str | None = None


def transition_quality_report(report: QualityReport, new_status: str) -> Result[QualityReport]:
    if new_status not in QUALITY_REPORT_TRANSITIONS.get(report.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move quality report from {report.status} to {new_status}")
    return Ok(replace(report, status=new_status))


def transition_follow_up(follow_up: FollowUp, new_status: str) -> Result[FollowUp]:
    if new_status not in FOLLOW_UP_TRANSITIONS.get(follow_up.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move follow-up from {follow_up.status} to {new_status}")
    return Ok(replace(follow_up, status=new_status))


def validate_conformity_line(line: ConformityLine) -> Result[None]:
    """Check one product's conformity counts for internal sense.

    Same stance as the old report-level check: refuses impossible values, not
    disappointing ones. Judging whether a defect rate is acceptable is the
    validator's job.
    """
    for field in ("conforming_cartons", "non_conforming_cartons"):
        value = getattr(line, field)
        if value < 0:
            return Err("INVALID_QUANTITY", f"{field} cannot be negative")
        if abs(value - round(value)) > 1e-6:
            return Err("QUANTITY_MUST_BE_INTEGER", f"{field} must be a whole number of cartons")
    if line.non_conforming_cartons > 0 and not (line.defect_details or "").strip():
        return Err("MISSING_DEFECT_DETAILS", "non-conforming cartons need defect details")
    return Ok(None)


def is_conforming(lines: list[ConformityLine]) -> bool:
    return all(line.non_conforming_cartons == 0 for line in lines)


def follow_up_window_end(report_date: datetime.date, window_days: int) -> datetime.date:
    return report_date + datetime.timedelta(days=window_days)


def validate_window_days(window_days: int) -> Result[None]:
    if window_days <= 0:
        return Err("INVALID_WINDOW", "the follow-up window must be at least one day")
    if window_days > 3650:
        return Err("INVALID_WINDOW", "a follow-up window longer than ten years is almost certainly a typo")
    return Ok(None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/qc/domain/test_quality.py -q`
Expected: PASS (including the untouched transition/follow-up-window tests already in the file).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/qc/domain/quality.py backend/modules/qc/domain/test_quality.py
git commit -m "refactor(qc): conformity moves to per-product lines in the domain layer

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Domain — parameters.py (Contrôle des paramètres field schemas)

**Files:**
- Create: `backend/modules/qc/domain/parameters.py`
- Create: `backend/modules/qc/domain/test_parameters.py`

**Interfaces:**
- Produces: `PARAMETER_GROUPS: dict[str, tuple[str, ...]]` (group_key → ordered field names). `validate_parameter_entry(group_key: str, fields: dict) -> Result[None]`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import pytest

from core.domain.result import Err, Ok
from modules.qc.domain.parameters import PARAMETER_GROUPS, validate_parameter_entry


def test_every_declared_group_has_at_least_one_field():
    for group_key, fields in PARAMETER_GROUPS.items():
        assert len(fields) > 0, group_key


def test_unknown_group_is_rejected():
    result = validate_parameter_entry("not_a_group", {})
    assert isinstance(result, Err)
    assert result.code == "INVALID_GROUP"


def test_unknown_field_for_a_group_is_rejected():
    result = validate_parameter_entry("sechage", {"not_a_field": 1})
    assert isinstance(result, Err)
    assert result.code == "INVALID_FIELD"


def test_valid_fields_for_sechage_are_accepted():
    result = validate_parameter_entry("sechage", {"temperature_c": 78.4, "delta": 7.1})
    assert isinstance(result, Ok)


def test_percentage_field_out_of_range_is_rejected():
    result = validate_parameter_entry("presse", {"niveau_moulange_percent": 150})
    assert isinstance(result, Err)
    assert result.code == "INVALID_PERCENTAGE"


def test_percentage_field_in_range_is_accepted():
    result = validate_parameter_entry("presse", {"niveau_moulange_percent": 48.9})
    assert isinstance(result, Ok)


@pytest.mark.parametrize("group_key", list(PARAMETER_GROUPS))
def test_empty_fields_is_always_valid(group_key):
    """A row can be saved with only its entry_label typed so far; fields fill in as the inspector reads the gauge."""
    result = validate_parameter_entry(group_key, {})
    assert isinstance(result, Ok)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/qc/domain/test_parameters.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.qc.domain.parameters'`.

- [ ] **Step 3: Write `backend/modules/qc/domain/parameters.py`**

```python
from __future__ import annotations

from core.domain.result import Err, Ok, Result

# The nine groups of the "Contrôle des paramètres" paper sheet, each a
# repeatable rows list: entry_label is the row's own key (a free time for
# most groups, a machine/press number for presse and compresseurs, PL/PC for
# additif) and fields holds that group's own readings. Field lists come
# from the photographed sheet (2026-09-24 spec, section 1.4) -- confirm
# wording/units with the client if a reading looks misread.
PARAMETER_GROUPS: dict[str, tuple[str, ...]] = {
    "presse": ("pression", "debit_bar", "niveau_moulange_percent"),
    "pompe_vide": ("niveau_huile", "temperature_c", "niveau_vide_bar"),
    "sechage": ("temperature_c", "delta"),
    "chaudiere": (
        "t_aller_c", "p_aller_bar", "t_retour_c", "p_retour_bar", "t_digit_c",
        "signal_a_elec", "niveau_bac_exp", "niveau_bac_alim", "compteur_cuve1", "compteur_cuve2",
    ),
    "compresseurs": ("pression_bar", "temperature_c"),
    "traitement_eau": (
        "niveau_cuve1", "niveau_cuve2", "niveau_sel", "niveau_bicore", "niveau_bache", "niveau_chateau",
    ),
    "chiller": (
        "t_entree_c", "t_sortie_c", "p_entree_bar", "p_sortie_bar",
        "t_digit_entree_c", "t_digit_sortie_c", "proprete_radiateur", "observation",
    ),
    "additif": ("tableau", "niveau_tremie", "observation"),
    "proprete_locaux": (
        "lave_m", "chaud", "tri_eau", "compr", "b_eau", "presse", "pres_en_h", "sech_en_h", "silo",
    ),
}

# Fields that are always a percentage, wherever their group declares them.
_PERCENTAGE_FIELDS = {"niveau_moulange_percent"}


def validate_parameter_entry(group_key: str, fields: dict) -> Result[None]:
    """Refuse a group nobody declared, a field that group doesn't have, or an
    impossible reading -- same "refuse impossible, not disappointing" stance
    as the rest of qc's validation. An empty `fields` dict is always valid:
    a row may be saved with only its entry_label typed so far.
    """
    declared = PARAMETER_GROUPS.get(group_key)
    if declared is None:
        return Err("INVALID_GROUP", f"group must be one of {sorted(PARAMETER_GROUPS)}")

    for key, value in fields.items():
        if key not in declared:
            return Err("INVALID_FIELD", f"{key} is not a field of group {group_key}")
        if key in _PERCENTAGE_FIELDS and value is not None and not 0 <= value <= 100:
            return Err("INVALID_PERCENTAGE", f"{key} must be between 0 and 100")
    return Ok(None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/qc/domain/test_parameters.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/qc/domain/parameters.py backend/modules/qc/domain/test_parameters.py
git commit -m "feat(qc): domain validation for Contrôle des paramètres entries

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Service — QualityReportService repointed to shift reports

**Files:**
- Modify: `backend/modules/qc/api/quality_service.py`
- Modify: `backend/modules/qc/api/test_qc_flow_integration.py` (fixtures only, this task)

**Interfaces:**
- Consumes: `ShiftReportService.get_shift(tenant_id, shift_report_id) -> Result[dict]` (from `backend/modules/production/api/shift_report_service.py`, header shape includes `id, work_center_id, report_date, shift, team, status, sections`); `production.shift_packing_rows` rows read via a new small helper in `report_product.py` or a direct query inside `_resolve_shift` (see Step 3) returning `(id, of_id, product_id)` triples.
- Produces: `QualityReportService.create_report(tenant_id, actor_id, shift_report_id, conformity_lines=None) -> Result[dict]`; `update_draft(tenant_id, actor_id, report_id, lines, comments=None, corrective_action=None) -> Result[dict]`; `admin_update_report(tenant_id, actor_id, report_id, lines=None, shift_report_id=None, comments=None, corrective_action=None, reason=None) -> Result[dict]`; `list_inspectable_shift_reports(tenant_id, work_center_id=None) -> list[dict]`; `get_report(tenant_id, report_id) -> dict | None` returning `{"report": QualityReport, "detail": QualityReportDetail, "lines": list[ConformityLine]}`.

First, replace the fixtures in `test_qc_flow_integration.py` so later steps in this task have something real to run against.

- [ ] **Step 1: Rewrite the qc test fixtures to build a shift, not a conditionnement report**

Read `backend/modules/qc/api/test_qc_flow_integration.py` fully first (already read above, lines 1-120 shown; read the rest — it continues with the state-machine and NC tests that use `_quality_report`). Replace the `env`, `of`, `_packing`, `_quality_report` fixtures with a shift-based equivalent, following the pattern in `backend/modules/production/api/test_finished_goods_integration.py:21-67`:

```python
"""Integration tests for the qc module.

qc carries of_id/product_id as opaque columns via its conformity lines and
never touches production's tables directly -- these tests build a shift
report through production's own ShiftReportService and validate it, then
work with nothing but the resulting shift_report_id and packing row ids.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.qc.api.non_conformity_service import NonConformityService
from modules.qc.api.quality_service import FollowUpPolicyService, FollowUpService, QualityReportService
from modules.qc.domain.non_conformity import DispositionLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-qc"


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, quarantine, work_center, equipment = (str(ULID()) for _ in range(6))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-QC', 'Test pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'FG', 'Finished goods')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked, blocked_reason) "
        "VALUES (%s, %s, 'QUAR', 'Quarantine', TRUE, 'awaiting QC disposition')",
        (quarantine, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'TEST-WC', 'Test line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'TEST-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=1_000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )
    return {
        "actor": actor, "product": product, "location": location, "quarantine": quarantine,
        "work_center": work_center, "equipment": equipment,
    }


@pytest.fixture
def of(db, env):
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value


def _validated_shift(db, env, of, report_date=datetime.date(2026, 9, 1), shift="morning", packets_counted=200) -> str:
    """A validated shift with one packing row, ready for QC to inspect."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        report_date=report_date, shift=shift,
    ))["id"]
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
        payload={"rows": [{
            "of_id": of.id, "product_id": env["product"], "equipment_id": env["equipment"],
            "finished_product_quantity": 900, "packets_counted": packets_counted,
        }]},
    ))
    for key in SECTION_KEYS:
        if key == "packing":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1), shift="morning"):
    shift_id = _validated_shift(db, env, of, report_date=report_date, shift=shift)
    result = QualityReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id,
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value["report"]
```

Do not touch the rest of the file's test bodies yet — they'll fail after this fixture rewrite (they call the old `create_report(conditionnement_report_id=...)` signature and the old `QualityReportDetail(conforming_cartons=..., ...)`). They get fixed in Step 5 of this task, once the service itself is rewritten, so their failures are expected between here and then.

- [ ] **Step 2: Run to confirm the expected failure shape**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_qc_flow_integration.py -q`
Expected: FAIL — `TypeError: create_report() got an unexpected keyword argument 'shift_report_id'` (service hasn't changed yet). This confirms the fixture itself is wired correctly (it gets as far as calling the service) before you touch `quality_service.py`.

- [ ] **Step 3: Rewrite `QualityReportService` in `backend/modules/qc/api/quality_service.py`**

Read the full current file first (already read above in the conversation). Apply these changes:

1. Replace `_REPORT_COLUMNS`:
```python
_REPORT_COLUMNS = """
    id, shift_report_id, report_date, status, revision, team, shift, created_by,
    submitted_at, validated_by, validated_at, rejection_reason
"""
```

2. Replace `_DETAIL_COLUMNS`:
```python
_DETAIL_COLUMNS = "comments, corrective_action"
```

3. Add conformity-line columns:
```python
_LINE_COLUMNS = """
    id, report_id, shift_packing_row_id, of_id, product_id,
    conforming_cartons, non_conforming_cartons, defect_details
"""
```

4. Replace `_row_to_report`:
```python
def _row_to_report(row: tuple) -> QualityReport:
    return QualityReport(
        id=row[0], shift_report_id=row[1], report_date=row[2], status=row[3], revision=row[4],
        team=row[5], shift=row[6], created_by=row[7], submitted_at=row[8],
        validated_by=row[9], validated_at=row[10], rejection_reason=row[11],
    )
```

5. Replace `_row_to_detail`/`_detail_values`:
```python
def _row_to_detail(row: tuple) -> QualityReportDetail:
    return QualityReportDetail(comments=row[0], corrective_action=row[1])


def _detail_values(detail: QualityReportDetail) -> tuple:
    return (detail.comments, detail.corrective_action)
```

6. Add line row helpers:
```python
def _row_to_line(row: tuple) -> ConformityLine:
    return ConformityLine(
        id=row[0], report_id=row[1], shift_packing_row_id=row[2], of_id=row[3], product_id=row[4],
        conforming_cartons=float(row[5]), non_conforming_cartons=float(row[6]), defect_details=row[7],
    )
```

7. Update the `quality.py` import list to include `ConformityLine`, `is_conforming`, `validate_conformity_line` in place of `QualityReportDetail`'s old shape and `validate_quality_detail`.

8. Replace `_load_report`'s query to select from `_REPORT_COLUMNS` (unchanged shape otherwise). Add `_load_lines`:
```python
def _load_lines(self, *, tenant_id: str, report_id: str) -> list[ConformityLine]:
    rows = self._connection.execute(
        f"SELECT {_LINE_COLUMNS} FROM qc.quality_conformity_lines WHERE report_id = %s AND tenant_id = %s ORDER BY id",
        (report_id, tenant_id),
    ).fetchall()
    return [_row_to_line(row) for row in rows]
```

9. Replace `get_report`:
```python
def get_report(self, *, tenant_id: str, report_id: str) -> dict | None:
    report = self._load_report(tenant_id=tenant_id, report_id=report_id)
    if report is None:
        return None
    return {
        "report": report,
        "detail": self._load_detail(tenant_id=tenant_id, report_id=report_id),
        "lines": self._load_lines(tenant_id=tenant_id, report_id=report_id),
    }
```

10. Delete `get_conformity_summary`/`_reports_needing_nc`/`team_conformity`/`index_trend` — replaced wholesale in Task 6 (do not leave the old bodies referencing dropped columns; stub them out in this step so the file still imports, e.g. `raise NotImplementedError` temporarily, and finish them in Task 6). Simplest: leave them deleted here and let Task 6 add them back — do not ship this task with a stub if Task 6 runs immediately after in the same session; if executed by a different worker, add:
```python
def get_conformity_summary(self, *, tenant_id: str, of_id: str) -> dict:
    raise NotImplementedError("rewritten in the next task")


def team_conformity(self, *, tenant_id: str, grain: str, date_from=None, date_to=None) -> list[dict]:
    raise NotImplementedError("rewritten in the next task")


def index_trend(self, *, tenant_id: str, grain: str, date_from=None, date_to=None) -> list[dict]:
    raise NotImplementedError("rewritten in the next task")
```

11. Replace `list_reports` (drop the `finished_products_of_reports` join — a report's products now come from its own conformity lines, read by the caller via `get_report`/`_load_lines`, not stamped onto the header):
```python
def list_reports(self, *, tenant_id: str, status: str | None = None) -> list[QualityReport]:
    clauses = ["tenant_id = %s"]
    params: list[object] = [tenant_id]
    if status is not None:
        clauses.append("status = %s")
        params.append(status)
    rows = self._connection.execute(
        f"SELECT {_REPORT_COLUMNS} FROM qc.quality_reports WHERE {' AND '.join(clauses)} "
        f"ORDER BY report_date DESC, created_at DESC",
        params,
    ).fetchall()
    return [_row_to_report(row) for row in rows]
```

12. Replace `_resolve_conditionnement` with `_resolve_shift`:
```python
def _resolve_shift(self, *, tenant_id: str, shift_report_id: str) -> Result[dict]:
    """Resolve a shift report into what a quality report needs from it.

    Production is the authority on work_center/date/team/shift and on the
    packing rows a QC report inspects. qc never reads production's tables
    for this -- it asks production's own service, same cross-module call
    direction as get_conformity_summary makes into qc, just reversed.
    """
    from modules.production.api.shift_report_service import ShiftReportService

    shifts = ShiftReportService(self._connection)
    found = shifts.get_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
    if isinstance(found, Err):
        return found
    header = found.value

    packing_rows = self._connection.execute(
        """
        SELECT id, of_id, product_id FROM production.shift_packing_rows
        WHERE tenant_id = %s AND shift_report_id = %s AND product_id IS NOT NULL
        ORDER BY id
        """,
        (tenant_id, shift_report_id),
    ).fetchall()

    return Ok(
        {
            "work_center_id": header["work_center_id"],
            "report_date": datetime.date.fromisoformat(header["report_date"]),
            "shift": header["shift"],
            "team": header["team"],
            "status": header["status"],
            "packing_rows": [{"id": r[0], "of_id": r[1], "product_id": r[2]} for r in packing_rows],
        }
    )
```
(`shift_packing_rows` is read directly here rather than through a `ShiftReportService` method because that service's `get_shift` returns section payloads, not typed packing rows with stable ids — reading the table directly is the plan's own choice, flagged here rather than in the spec; if the plan's reviewer prefers a dedicated `list_packing_rows` method on `ShiftReportService` instead, add it there and call it — either satisfies the module-boundary rule since both are still "ask production," just at different granularity.)

13. Replace `list_inspectable_conditionnement_reports` with `list_inspectable_shift_reports`:
```python
def list_inspectable_shift_reports(self, *, tenant_id: str) -> list[dict]:
    """Validated shift reports with no QC report yet."""
    already_linked = {
        row[0]
        for row in self._connection.execute(
            "SELECT shift_report_id FROM qc.quality_reports WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()
    }
    from modules.production.api.shift_report_service import ShiftReportService

    shifts = ShiftReportService(self._connection).list_shifts(tenant_id=tenant_id, status="validated")
    return [
        {
            "shift_report_id": s["id"], "work_center_id": s["work_center_id"], "report_date": s["report_date"],
            "shift": s["shift"], "team": s["team"],
        }
        for s in shifts
        if s["id"] not in already_linked
    ]
```

14. Replace `create_report`:
```python
def create_report(self, *, tenant_id: str, actor_id: str, shift_report_id: str) -> Result[dict]:
    if not shift_report_id.strip():
        return Err("MISSING_SHIFT_REPORT", "a quality report must inspect a shift report")

    resolved = self._resolve_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
    if isinstance(resolved, Err):
        return resolved
    link = resolved.value

    duplicate = self._connection.execute(
        "SELECT 1 FROM qc.quality_reports WHERE tenant_id = %s AND shift_report_id = %s",
        (tenant_id, shift_report_id),
    ).fetchone()
    if duplicate is not None:
        return Err("DUPLICATE_REPORT", "a quality report already exists for this shift report")

    report_id = str(ULID())
    self._connection.execute(
        """
        INSERT INTO qc.quality_reports (id, tenant_id, shift_report_id, report_date, status, revision, team, shift, created_by)
        VALUES (%s, %s, %s, %s, 'draft', 1, %s, %s, %s)
        """,
        (report_id, tenant_id, shift_report_id, link["report_date"], link["team"], link["shift"], actor_id),
    )
    self._connection.execute(
        f"INSERT INTO qc.quality_report_details (report_id, tenant_id, {_DETAIL_COLUMNS}) VALUES (%s, %s, %s, %s)",
        (report_id, tenant_id, None, None),
    )
    for row in link["packing_rows"]:
        self._connection.execute(
            """
            INSERT INTO qc.quality_conformity_lines
                (id, tenant_id, report_id, shift_packing_row_id, of_id, product_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (str(ULID()), tenant_id, report_id, row["id"], row["of_id"], row["product_id"]),
        )
    record_audit(
        self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_report.created",
        entity_type="quality_report", entity_id=report_id,
        payload={"shift_report_id": shift_report_id, "report_date": link["report_date"].isoformat(), "line_count": len(link["packing_rows"])},
    )
    return Ok(self._read(tenant_id=tenant_id, report_id=report_id))
```

15. Replace `update_draft` to take `lines` (a list of dicts keyed by `shift_packing_row_id`) plus report-level `detail`:
```python
def update_draft(
    self, *, tenant_id: str, actor_id: str, report_id: str,
    lines: list[dict], detail: QualityReportDetail | None = None,
) -> Result[dict]:
    report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
    if report is None:
        return Err("NOT_FOUND", f"quality report {report_id} not found")
    if report.status != "draft":
        return Err("NOT_EDITABLE", f"a {report.status} quality report cannot be edited as a draft")

    updated_lines = self._apply_line_edits(tenant_id=tenant_id, report_id=report_id, edits=lines)
    if isinstance(updated_lines, Err):
        return updated_lines

    if detail is not None:
        self._write_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
    record_audit(
        self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_report.draft_updated",
        entity_type="quality_report", entity_id=report_id, payload={"line_count": len(lines)},
    )
    return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

def _apply_line_edits(self, *, tenant_id: str, report_id: str, edits: list[dict]) -> Result[None]:
    for edit in edits:
        row_id = edit["shift_packing_row_id"]
        existing = self._connection.execute(
            "SELECT id, of_id, product_id FROM qc.quality_conformity_lines "
            "WHERE tenant_id = %s AND report_id = %s AND shift_packing_row_id = %s",
            (tenant_id, report_id, row_id),
        ).fetchone()
        if existing is None:
            return Err("LINE_NOT_FOUND", f"no conformity line for packing row {row_id} on this report")
        line = ConformityLine(
            id=existing[0], report_id=report_id, shift_packing_row_id=row_id, of_id=existing[1], product_id=existing[2],
            conforming_cartons=float(edit.get("conforming_cartons", 0)),
            non_conforming_cartons=float(edit.get("non_conforming_cartons", 0)),
            defect_details=edit.get("defect_details"),
        )
        validation = validate_conformity_line(line)
        if isinstance(validation, Err):
            return validation
        self._connection.execute(
            """
            UPDATE qc.quality_conformity_lines
            SET conforming_cartons = %s, non_conforming_cartons = %s, defect_details = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (line.conforming_cartons, line.non_conforming_cartons, line.defect_details, line.id),
        )
    return Ok(None)
```

16. Replace `admin_update_report` similarly, re-linking to a different `shift_report_id` re-derives report_date/shift/team and reconciles conformity lines (insert new ones for packing rows not yet present; existing lines with a linked non-conformity are left untouched even if the new shift no longer includes that packing row — mirrors the delete-guard's spirit, do not silently orphan an NC):
```python
def admin_update_report(
    self, *, tenant_id: str, actor_id: str, report_id: str,
    lines: list[dict] | None = None, shift_report_id: str | None = None,
    detail: QualityReportDetail | None = None, reason: str | None = None,
) -> Result[dict]:
    report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
    if report is None:
        return Err("NOT_FOUND", f"quality report {report_id} not found")

    if lines is not None:
        applied = self._apply_line_edits(tenant_id=tenant_id, report_id=report_id, edits=lines)
        if isinstance(applied, Err):
            return applied

    if shift_report_id is not None:
        resolved = self._resolve_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
        if isinstance(resolved, Err):
            return resolved
        duplicate = self._connection.execute(
            "SELECT 1 FROM qc.quality_reports WHERE tenant_id = %s AND shift_report_id = %s AND id != %s",
            (tenant_id, shift_report_id, report_id),
        ).fetchone()
        if duplicate is not None:
            return Err("DUPLICATE_REPORT", "a quality report already exists for this shift report")
        link = resolved.value
        self._connection.execute(
            "UPDATE qc.quality_reports SET shift_report_id = %s, team = %s, shift = %s, report_date = %s, updated_at = NOW() WHERE id = %s",
            (shift_report_id, link["team"], link["shift"], link["report_date"], report_id),
        )
        existing_row_ids = {
            r[0] for r in self._connection.execute(
                "SELECT shift_packing_row_id FROM qc.quality_conformity_lines WHERE tenant_id = %s AND report_id = %s",
                (tenant_id, report_id),
            ).fetchall()
        }
        for row in link["packing_rows"]:
            if row["id"] not in existing_row_ids:
                self._connection.execute(
                    """
                    INSERT INTO qc.quality_conformity_lines
                        (id, tenant_id, report_id, shift_packing_row_id, of_id, product_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (str(ULID()), tenant_id, report_id, row["id"], row["of_id"], row["product_id"]),
                )

    if detail is not None:
        self._write_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)

    record_audit(
        self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_report.updated",
        entity_type="quality_report", entity_id=report_id, payload={"shift_report_id": shift_report_id, "reason": reason},
    )
    return Ok(self._read(tenant_id=tenant_id, report_id=report_id))
```

17. Replace `submit_report` to validate every line:
```python
def submit_report(self, *, tenant_id: str, actor_id: str, report_id: str) -> Result[QualityReport]:
    report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
    if report is None:
        return Err("NOT_FOUND", f"quality report {report_id} not found")

    result = transition_quality_report(report, "submitted")
    if isinstance(result, Err):
        return result

    lines = self._load_lines(tenant_id=tenant_id, report_id=report_id)
    for line in lines:
        validation = validate_conformity_line(line)
        if isinstance(validation, Err):
            return validation

    self._connection.execute(
        "UPDATE qc.quality_reports SET status = 'submitted', submitted_at = NOW(), updated_at = NOW() WHERE id = %s",
        (report_id,),
    )
    record_audit(
        self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_report.submitted",
        entity_type="quality_report", entity_id=report_id, payload={"revision": report.revision},
    )
    return Ok(self._load_report(tenant_id=tenant_id, report_id=report_id))  # type: ignore[arg-type]
```

18. Replace `validate_report` — no more `product_id` parameter (follow-up windows are per-line now, each line already knows its own `product_id`):
```python
def validate_report(self, *, tenant_id: str, actor_id: str, report_id: str, correlation_id: str) -> Result[dict]:
    """Make a quality report official and open one follow-up window per product line.

    Posts no stock -- quality only moves inventory through a non-conformity.
    """
    report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
    if report is None:
        return Err("NOT_FOUND", f"quality report {report_id} not found")

    result = transition_quality_report(report, "validated")
    if isinstance(result, Err):
        return result

    lines = self._load_lines(tenant_id=tenant_id, report_id=report_id)

    self._connection.execute(
        """
        UPDATE qc.quality_reports
        SET status = 'validated', validated_by = %s, validated_at = NOW(), rejection_reason = NULL, updated_at = NOW()
        WHERE id = %s
        """,
        (actor_id, report_id),
    )

    policies = FollowUpPolicyService(self._connection)
    opened_follow_ups = []
    for line in lines:
        window_days = policies.resolve_window_days(tenant_id=tenant_id, product_id=line.product_id)
        window_ends_on = follow_up_window_end(report.report_date, window_days)
        follow_up_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO qc.quality_follow_ups
                (id, tenant_id, quality_report_id, of_id, conformity_line_id, window_ends_on, observed_on, status, observation, actor_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
            """,
            (follow_up_id, tenant_id, report_id, line.of_id, line.id, window_ends_on, report.report_date, "opened on validation", actor_id),
        )
        opened_follow_ups.append({"follow_up_id": follow_up_id, "of_id": line.of_id, "window_ends_on": window_ends_on})

    publish_event(
        self._connection, event_type="qc.quality_report.validated", producer="qc", tenant_id=tenant_id,
        correlation_id=correlation_id,
        payload={"quality_report_id": report_id, "is_conforming": is_conforming(lines)},
    )
    record_audit(
        self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_report.validated",
        entity_type="quality_report", entity_id=report_id,
        payload={"is_conforming": is_conforming(lines), "follow_ups": len(opened_follow_ups)},
    )
    return Ok({
        "report": self._load_report(tenant_id=tenant_id, report_id=report_id),
        "lines": lines,
        "follow_ups": opened_follow_ups,
    })
```

19. Replace `reject_report`'s non-conformity cleanup query — it already filters by `quality_report_id = report_id` (unaffected by the line rewrite; leave as-is, just confirm `product_id, quantity` come from `qc.non_conformities` as today, not from the removed `quality_report_details`. No code change needed in `reject_report` itself beyond the surrounding class still compiling).

20. `delete_report`: the `attached` guard and the cascade deletes need a new line for conformity lines:
```python
self._connection.execute(
    "DELETE FROM qc.quality_follow_ups WHERE tenant_id = %s AND quality_report_id = %s",
    (tenant_id, report_id),
)
self._connection.execute(
    "DELETE FROM qc.quality_conformity_lines WHERE tenant_id = %s AND report_id = %s",
    (tenant_id, report_id),
)
self._connection.execute(
    "DELETE FROM qc.quality_report_details WHERE tenant_id = %s AND report_id = %s",
    (tenant_id, report_id),
)
self._connection.execute("DELETE FROM qc.quality_reports WHERE tenant_id = %s AND id = %s", (tenant_id, report_id))
```

21. `_write_detail`/`_read` stay structurally the same, just against the trimmed `_DETAIL_COLUMNS`/new `lines` key:
```python
def _read(self, *, tenant_id: str, report_id: str) -> dict:
    return {
        "report": self._load_report(tenant_id=tenant_id, report_id=report_id),
        "detail": self._load_detail(tenant_id=tenant_id, report_id=report_id),
        "lines": self._load_lines(tenant_id=tenant_id, report_id=report_id),
    }
```

- [ ] **Step 4: Run domain + this file's own compile check**

Run: `.venv/Scripts/python -c "import modules.qc.api.quality_service"` (from `backend/`, with the venv active) to catch import/syntax errors before running the full integration test.

Expected: no error.

- [ ] **Step 5: Fix the remaining test bodies in `test_qc_flow_integration.py`**

Read the rest of the file (past line 120) and update every call site that used the old `QualityReportDetail(conforming_cartons=..., non_conforming_cartons=..., defect_details=...)` or `create_report(conditionnement_report_id=...)` shape. Replace with, for example:

```python
def test_a_report_starts_as_a_draft_with_one_line_per_packing_row(db, env, of):
    report = _quality_report(db, env, of)
    assert report.status == "draft"

    full = _ok_or_value(QualityReportService(db).get_report(tenant_id=TENANT, report_id=report.id))
    assert len(full["lines"]) == 1
    assert full["lines"][0].of_id == of.id
    assert full["lines"][0].product_id == env["product"]


def test_submit_requires_defect_details_when_a_line_is_non_conforming(db, env, of):
    report = _quality_report(db, env, of)
    line_id = QualityReportService(db)._load_lines(tenant_id=TENANT, report_id=report.id)[0].shift_packing_row_id
    QualityReportService(db).update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{"shift_packing_row_id": line_id, "non_conforming_cartons": 3, "conforming_cartons": 17}],
    )
    result = QualityReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(result, Err)
    assert result.code == "MISSING_DEFECT_DETAILS"
```

(`_ok_or_value` — add a tiny local helper `def _ok_or_value(result): assert isinstance(result, dict) or True; return result` is unnecessary since `get_report` already returns a plain dict, not a `Result` — just call it directly: `full = QualityReportService(db).get_report(tenant_id=TENANT, report_id=report.id)`.)

Update every other test in the file the same way: replace direct detail-field assertions with lookups against `full["lines"]`, and replace any `validate_report(..., product_id=...)` call with the new no-`product_id` signature.

- [ ] **Step 6: Run the full qc flow test file**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_qc_flow_integration.py -q`
Expected: PASS. Iterate on Step 5's edits until green — this file is the safety net for the whole rewrite in this task.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/qc/api/quality_service.py backend/modules/qc/api/test_qc_flow_integration.py
git commit -m "refactor(qc): QualityReportService reads shift reports and per-product conformity lines

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Service — conformity summary, team/index analytics, and follow-up reads rewritten

**Files:**
- Modify: `backend/modules/qc/api/quality_service.py`
- Modify: `backend/modules/qc/api/test_team_conformity_integration.py`

**Interfaces:**
- Produces: `get_conformity_summary(tenant_id, of_id) -> dict` (same shape as today, minus nothing — computed across lines now); `_reports_needing_nc(tenant_id, of_id) -> list[dict]`; `team_conformity(tenant_id, grain, date_from=None, date_to=None) -> list[dict]` (same shape); `index_trend` **removed entirely** (see Global Constraints — the five indices are gone, and no reader besides qc's own dashboard used it, confirmed in the spec's Why section).
- Consumes: `qc.quality_conformity_lines`, `qc.quality_reports`.

- [ ] **Step 1: Write the failing tests**

Read `backend/modules/qc/api/test_team_conformity_integration.py` in full first, then replace its report-creation helper with one built on the new `_quality_report`-style fixture from Task 5 (import the shared pattern or duplicate the small helper locally — check whether the file already imports fixtures from `test_qc_flow_integration.py`; if so keep that import, updating call sites the same way Task 5 Step 5 did). Add:

```python
def test_conformity_summary_sums_across_every_line_of_every_of(db, env, of):
    """A shift can pack two OFs; get_conformity_summary(of_id) only counts that OF's lines."""
    other_of = _ok(WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=500,
        work_center_id=env["work_center"],
    ))
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=datetime.date(2026, 9, 2), shift="morning"))["id"]
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
        payload={"rows": [
            {"of_id": of.id, "product_id": env["product"], "equipment_id": env["equipment"], "finished_product_quantity": 500, "packets_counted": 100},
            {"of_id": other_of.id, "product_id": env["product"], "equipment_id": env["equipment"], "finished_product_quantity": 300, "packets_counted": 60},
        ]},
    ))
    for key in SECTION_KEYS:
        if key == "packing":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))

    qc = QualityReportService(db)
    report = _ok(qc.create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))["report"]
    lines = qc._load_lines(tenant_id=TENANT, report_id=report.id)
    of_line = next(l for l in lines if l.of_id == of.id)
    other_line = next(l for l in lines if l.of_id == other_of.id)
    qc.update_draft(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, lines=[
        {"shift_packing_row_id": of_line.shift_packing_row_id, "conforming_cartons": 8, "non_conforming_cartons": 0},
        {"shift_packing_row_id": other_line.shift_packing_row_id, "conforming_cartons": 5, "non_conforming_cartons": 0},
    ])
    _ok(qc.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id))
    _ok(qc.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())))

    summary = qc.get_conformity_summary(tenant_id=TENANT, of_id=of.id)
    assert summary["conforming_cartons"] == 8
    assert summary["validated_report_count"] == 1

    other_summary = qc.get_conformity_summary(tenant_id=TENANT, of_id=other_of.id)
    assert other_summary["conforming_cartons"] == 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_team_conformity_integration.py -k conformity_summary_sums -q`
Expected: FAIL — `NotImplementedError` (from Task 5 Step 3.10's stub) or `AttributeError` if the stub wasn't added.

- [ ] **Step 3: Implement the rewritten reads in `quality_service.py`**

Replace the stubs (or add fresh, if Task 5 left them deleted) with:

```python
def get_conformity_summary(self, *, tenant_id: str, of_id: str) -> dict:
    """How an OF's quality came out, summed over its validated reports' conformity lines.

    Only validated reports count -- a draft or rejected quality report is a
    claim, not a verdict.
    """
    row = self._connection.execute(
        """
        SELECT count(DISTINCT r.id), COALESCE(SUM(l.conforming_cartons), 0), COALESCE(SUM(l.non_conforming_cartons), 0)
        FROM qc.quality_conformity_lines l
        JOIN qc.quality_reports r ON r.id = l.report_id AND r.tenant_id = l.tenant_id
        WHERE l.tenant_id = %s AND l.of_id = %s AND r.status = 'validated'
        """,
        (tenant_id, of_id),
    ).fetchone()
    report_count, conforming, non_conforming = int(row[0]), float(row[1]), float(row[2])
    total = conforming + non_conforming
    return {
        "validated_report_count": report_count,
        "conforming_cartons": conforming,
        "non_conforming_cartons": non_conforming,
        "conformity_rate": (conforming / total) if total > 0 else None,
        "pending_nc_reports": self._reports_needing_nc(tenant_id=tenant_id, of_id=of_id),
    }

def _reports_needing_nc(self, *, tenant_id: str, of_id: str) -> list[dict]:
    """Validated conformity lines that logged a defect but never got an NC raised for it."""
    rows = self._connection.execute(
        """
        SELECT l.id, r.report_date, l.non_conforming_cartons
        FROM qc.quality_conformity_lines l
        JOIN qc.quality_reports r ON r.id = l.report_id AND r.tenant_id = l.tenant_id
        WHERE l.tenant_id = %s AND l.of_id = %s AND r.status = 'validated'
          AND l.non_conforming_cartons > 0
          AND NOT EXISTS (
              SELECT 1 FROM qc.non_conformities n
              WHERE n.tenant_id = l.tenant_id AND n.quality_report_id = l.report_id AND n.product_id = l.product_id
          )
        ORDER BY r.report_date DESC
        """,
        (tenant_id, of_id),
    ).fetchall()
    return [
        {"conformity_line_id": line_id, "report_date": report_date.isoformat(), "non_conforming_cartons": float(qty)}
        for line_id, report_date, qty in rows
    ]

GRAINS = ("day", "week", "month", "year")

def team_conformity(self, *, tenant_id: str, grain: str, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    if grain not in self.GRAINS:
        raise ValueError(f"grain must be one of {self.GRAINS}")
    clauses = ["r.tenant_id = %s", "r.status = 'validated'"]
    params: list[object] = [grain, tenant_id]
    if date_from is not None:
        clauses.append("r.report_date >= %s")
        params.append(date_from)
    if date_to is not None:
        clauses.append("r.report_date <= %s")
        params.append(date_to)
    rows = self._connection.execute(
        f"""
        SELECT r.team, date_trunc(%s, r.report_date)::date AS period, count(DISTINCT r.id) AS report_count,
               COALESCE(SUM(l.conforming_cartons), 0), COALESCE(SUM(l.non_conforming_cartons), 0)
        FROM qc.quality_reports r
        JOIN qc.quality_conformity_lines l ON l.report_id = r.id AND l.tenant_id = r.tenant_id
        WHERE {' AND '.join(clauses)}
        GROUP BY r.team, period
        """,
        params,
    ).fetchall()
    return [
        {"team": team, "period": period.isoformat(), "report_count": int(count), "conforming_cartons": float(c), "non_conforming_cartons": float(nc)}
        for team, period, count, c, nc in rows
    ]
```

Do not re-add `index_trend` — it's removed per the spec. Remove its import references from `quality.py` if any remain (there shouldn't be, since Task 3 already trimmed `QualityReportDetail`).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_team_conformity_integration.py -q`
Expected: PASS — fix any remaining call sites in the file that reference the old per-report detail shape or `index_trend`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/qc/api/quality_service.py backend/modules/qc/api/test_team_conformity_integration.py
git commit -m "refactor(qc): conformity summary and team analytics read per-product lines; drop index_trend

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Service — parameters CRUD

**Files:**
- Modify: `backend/modules/qc/api/quality_service.py`
- Create: `backend/modules/qc/api/test_parameters_integration.py`

**Interfaces:**
- Produces: `QualityReportService.list_parameters(tenant_id, report_id) -> list[dict]`; `save_parameter_entry(tenant_id, actor_id, report_id, group_key, entry_label, fields) -> Result[dict]`; `delete_parameter_entry(tenant_id, actor_id, report_id, entry_id) -> Result[None]`.

- [ ] **Step 1: Write the failing test**

```python
"""Contrôle des paramètres: one row per instrument-group entry on a QC report."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.qc.api.quality_service import QualityReportService
from modules.qc.api.test_qc_flow_integration import TENANT, _ok, _quality_report, env, of  # noqa: F401


def test_saving_a_parameter_entry_round_trips(db, env, of):
    report = _quality_report(db, env, of)
    saved = QualityReportService(db).save_parameter_entry(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        group_key="sechage", entry_label="07h38", fields={"temperature_c": 78.4, "delta": 7.1},
    )
    assert isinstance(saved, Ok), getattr(saved, "message", "")

    entries = QualityReportService(db).list_parameters(tenant_id=TENANT, report_id=report.id)
    assert len(entries) == 1
    assert entries[0]["group_key"] == "sechage"
    assert entries[0]["entry_label"] == "07h38"
    assert entries[0]["fields"]["temperature_c"] == 78.4


def test_an_invalid_group_is_rejected():
    pass  # covered at the domain layer (test_parameters.py); service delegates to validate_parameter_entry


def test_saving_an_entry_for_an_unknown_field_is_rejected(db, env, of):
    report = _quality_report(db, env, of)
    result = QualityReportService(db).save_parameter_entry(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        group_key="sechage", entry_label="07h38", fields={"not_a_field": 1},
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_FIELD"


def test_deleting_an_entry_removes_it(db, env, of):
    report = _quality_report(db, env, of)
    saved = _ok(QualityReportService(db).save_parameter_entry(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        group_key="presse", entry_label="4132", fields={"pression": 114},
    ))
    QualityReportService(db).delete_parameter_entry(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, entry_id=saved["id"])
    assert QualityReportService(db).list_parameters(tenant_id=TENANT, report_id=report.id) == []
```

Remove the placeholder `test_an_invalid_group_is_rejected` (it's a no-op left in by mistake — delete it rather than keep a passing-by-definition test) before running.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_parameters_integration.py -q`
Expected: FAIL — `AttributeError: 'QualityReportService' object has no attribute 'save_parameter_entry'`.

- [ ] **Step 3: Implement in `quality_service.py`**

Add the import `from modules.qc.domain.parameters import validate_parameter_entry` and:

```python
def list_parameters(self, *, tenant_id: str, report_id: str) -> list[dict]:
    rows = self._connection.execute(
        "SELECT id, group_key, entry_label, fields FROM qc.quality_parameters "
        "WHERE tenant_id = %s AND report_id = %s ORDER BY group_key, created_at",
        (tenant_id, report_id),
    ).fetchall()
    return [{"id": r[0], "group_key": r[1], "entry_label": r[2], "fields": r[3]} for r in rows]

def save_parameter_entry(
    self, *, tenant_id: str, actor_id: str, report_id: str, group_key: str,
    entry_label: str | None, fields: dict,
) -> Result[dict]:
    import json

    report = self._load_report(tenant_id=tenant_id, report_id=report_id)
    if report is None:
        return Err("NOT_FOUND", f"quality report {report_id} not found")
    validation = validate_parameter_entry(group_key, fields)
    if isinstance(validation, Err):
        return validation

    entry_id = str(ULID())
    self._connection.execute(
        "INSERT INTO qc.quality_parameters (id, tenant_id, report_id, group_key, entry_label, fields) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (entry_id, tenant_id, report_id, group_key, entry_label, json.dumps(fields)),
    )
    record_audit(
        self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_parameter.saved",
        entity_type="quality_report", entity_id=report_id, payload={"group_key": group_key, "entry_label": entry_label},
    )
    return Ok({"id": entry_id, "group_key": group_key, "entry_label": entry_label, "fields": fields})

def delete_parameter_entry(self, *, tenant_id: str, actor_id: str, report_id: str, entry_id: str) -> Result[None]:
    deleted = self._connection.execute(
        "DELETE FROM qc.quality_parameters WHERE tenant_id = %s AND report_id = %s AND id = %s RETURNING id",
        (tenant_id, report_id, entry_id),
    ).fetchone()
    if deleted is None:
        return Err("NOT_FOUND", f"parameter entry {entry_id} not found on report {report_id}")
    record_audit(
        self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_parameter.deleted",
        entity_type="quality_report", entity_id=report_id, payload={"entry_id": entry_id},
    )
    return Ok(None)
```

Also add deletion of `qc.quality_parameters` rows to `delete_report`'s cascade (alongside the conformity-lines delete added in Task 5 Step 3.20):
```python
self._connection.execute(
    "DELETE FROM qc.quality_parameters WHERE tenant_id = %s AND report_id = %s", (tenant_id, report_id),
)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_parameters_integration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/qc/api/quality_service.py backend/modules/qc/api/test_parameters_integration.py
git commit -m "feat(qc): parameter entry CRUD for Contrôle des paramètres

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Service — non-conformity quantity derivation from conformity lines

**Files:**
- Modify: `backend/modules/qc/api/non_conformity_service.py`
- Modify: `backend/modules/qc/api/test_qc_flow_integration.py` (add one test)

**Interfaces:**
- Consumes: `qc.quality_conformity_lines`.
- Produces: `_quantity_from_quality_report` unchanged signature, new query.

- [ ] **Step 1: Write the failing test**

Add to `test_qc_flow_integration.py`:

```python
def test_raising_an_nc_from_a_quality_report_derives_quantity_from_its_line(db, env, of):
    qc = QualityReportService(db)
    report = _quality_report(db, env, of)
    line = qc._load_lines(tenant_id=TENANT, report_id=report.id)[0]
    qc.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{"shift_packing_row_id": line.shift_packing_row_id, "conforming_cartons": 10, "non_conforming_cartons": 4, "defect_details": "soudure"}],
    )
    _ok(qc.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id))
    _ok(qc.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())))

    nc = NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, product_id=env["product"],
        quantity=0,  # ignored -- derived from the quality report
        source_location_id=env["location"], defect_type="soudure défectueuse",
        correlation_id=str(ULID()), quarantine_location_id=env["quarantine"],
        quality_report_id=report.id,
    )
    assert isinstance(nc, Ok), getattr(nc, "message", "")
    assert nc.value.quantity == 4  # no packets_per_carton on this test product, so cartons == pieces
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_qc_flow_integration.py -k derives_quantity_from_its_line -q`
Expected: FAIL — `sqlstate` error, `column "report_id" of relation "qc.quality_report_details" does not exist` or similar, since `_quantity_from_quality_report` still queries the dropped columns.

- [ ] **Step 3: Fix `_quantity_from_quality_report` in `non_conformity_service.py`**

```python
def _quantity_from_quality_report(
    self, *, tenant_id: str, quality_report_id: str, of_id: str, product_id: str
) -> Result[float]:
    """The piece quantity a quality report's rejection actually represents.

    Reads the conformity line for this report/of/product -- a shift's QC
    report can span several products, so the line is what carries the real
    non_conforming_cartons count, not the report as a whole.
    """
    row = self._connection.execute(
        """
        SELECT l.non_conforming_cartons
        FROM qc.quality_conformity_lines l
        WHERE l.report_id = %s AND l.tenant_id = %s AND l.of_id = %s AND l.product_id = %s
        """,
        (quality_report_id, tenant_id, of_id, product_id),
    ).fetchone()
    if row is None:
        return Err("QUALITY_REPORT_NOT_FOUND", f"no conformity line on report {quality_report_id} for OF {of_id} / product {product_id}")
    non_conforming_cartons = float(row[0])

    product = self._core.get_product(tenant_id, product_id)
    packets_per_carton = product.packets_per_carton if product else None
    if packets_per_carton and packets_per_carton > 0:
        return Ok(non_conforming_cartons * packets_per_carton)
    return Ok(non_conforming_cartons)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_qc_flow_integration.py -q`
Expected: PASS (full file, not just the new test — confirms nothing else broke).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/qc/api/non_conformity_service.py backend/modules/qc/api/test_qc_flow_integration.py
git commit -m "refactor(qc): non-conformity quantity derives from its conformity line

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 9: Router — new request/response shapes and routes

**Files:**
- Modify: `backend/modules/qc/api/router.py`

**Interfaces:**
- Consumes: everything produced in Tasks 5-8.
- Produces: `POST /qc/quality-reports` (body: `{shift_report_id}`), `GET /qc/shift-reports` (was `/qc/conditionnement-reports`), `PATCH /qc/quality-reports/{id}` (body: `{lines, comments?, corrective_action?}`), `PATCH /qc/quality-reports/{id}/admin`, `GET/POST/DELETE /qc/quality-reports/{id}/parameters`, `POST /qc/quality-reports/{id}/validate` (no `product_id` in body).

- [ ] **Step 1: Update the Pydantic models**

Replace `QualityDetailRequest`:
```python
class QualityDetailRequest(BaseModel):
    comments: str | None = None
    corrective_action: str | None = None

    def to_detail(self) -> QualityReportDetail:
        return QualityReportDetail(**self.model_dump())
```

Add:
```python
class ConformityLineRequest(BaseModel):
    shift_packing_row_id: str
    conforming_cartons: float = 0
    non_conforming_cartons: float = 0
    defect_details: str | None = None
```

Replace `CreateQualityReportRequest`:
```python
class CreateQualityReportRequest(BaseModel):
    # The shift report this report inspects. report_date/shift/team are all
    # derived from it -- see QualityReportService._resolve_shift.
    shift_report_id: str
```

Replace `UpdateQualityReportRequest`:
```python
class UpdateQualityReportRequest(BaseModel):
    lines: list[ConformityLineRequest] = []
    detail: QualityDetailRequest | None = None
```

Replace `AdminUpdateQualityReportRequest`:
```python
class AdminUpdateQualityReportRequest(BaseModel):
    lines: list[ConformityLineRequest] | None = None
    detail: QualityDetailRequest | None = None
    shift_report_id: str | None = None
    reason: str | None = None
```

Replace `ValidateQualityReportRequest` (drop `product_id` — no longer needed, follow-ups are per-line):
```python
class ValidateQualityReportRequest(BaseModel):
    correlation_id: str
```

Add:
```python
class ParameterEntryRequest(BaseModel):
    group_key: str
    entry_label: str | None = None
    fields: dict = {}
```

- [ ] **Step 2: Update the quality-report routes**

```python
@router.post("/quality-reports", status_code=status.HTTP_201_CREATED)
def create_quality_report(
    body: CreateQualityReportRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).create_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, shift_report_id=body.shift_report_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.get("/quality-reports")
def list_quality_reports(
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("qc.view_quality_reports")),
) -> list[dict]:
    with get_connection() as connection:
        reports = QualityReportService(connection).list_reports(tenant_id=tenant.tenant_id, status=status_filter)
    return [_serialize_report(report) for report in reports]


@router.get("/shift-reports")
def list_inspectable_shift_reports(
    tenant: TenantContext = Depends(require_permission("qc.view_quality_reports")),
) -> list[dict]:
    """Validated shift reports with no quality report yet."""
    with get_connection() as connection:
        rows = QualityReportService(connection).list_inspectable_shift_reports(tenant_id=tenant.tenant_id)
    return [
        {
            "shift_report_id": row["shift_report_id"], "work_center_id": row["work_center_id"],
            "report_date": row["report_date"], "shift": row["shift"], "team": row["team"],
        }
        for row in rows
    ]
```

Update `update_quality_report`/`admin_update_quality_report` to pass `lines=[l.model_dump() for l in body.lines]` and `detail=body.detail.to_detail() if body.detail else None`:

```python
@router.patch("/quality-reports/{report_id}")
def update_quality_report(
    report_id: str,
    body: UpdateQualityReportRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).update_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id,
            lines=[line.model_dump() for line in body.lines],
            detail=body.detail.to_detail() if body.detail is not None else None,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.patch("/quality-reports/{report_id}/admin")
def admin_update_quality_report(
    report_id: str,
    body: AdminUpdateQualityReportRequest,
    tenant: TenantContext = Depends(require_permission("qc.admin_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).admin_update_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id,
            lines=[line.model_dump() for line in body.lines] if body.lines is not None else None,
            detail=body.detail.to_detail() if body.detail is not None else None,
            shift_report_id=body.shift_report_id, reason=body.reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)
```

Update `validate_quality_report` to drop `product_id`:
```python
@router.post("/quality-reports/{report_id}/validate")
def validate_quality_report(
    report_id: str,
    body: ValidateQualityReportRequest,
    tenant: TenantContext = Depends(require_permission("qc.validate_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).validate_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id, correlation_id=body.correlation_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    value = result.value
    return {
        "report": _serialize_report(value["report"]),
        "lines": [_serialize_line(l) for l in value["lines"]],
        "follow_ups": [{"follow_up_id": f["follow_up_id"], "of_id": f["of_id"], "window_ends_on": f["window_ends_on"].isoformat()} for f in value["follow_ups"]],
    }
```

Remove `list_quality_index_trend` entirely (route and function).

Remove `of_id` query param from `list_follow_ups`/`list_non_conformities` call sites only if the underlying service signature changed — it did not (NonConformityService's `of_id` filter is untouched, and FollowUpService's `of_id` filter is untouched since `of_id` still lives on `quality_follow_ups` rows). No change needed there.

- [ ] **Step 3: Add the parameters routes**

```python
# --- Contrôle des paramètres -------------------------------------------------


@router.get("/quality-reports/{report_id}/parameters")
def list_parameters(
    report_id: str, tenant: TenantContext = Depends(require_permission("qc.view_quality_reports"))
) -> list[dict]:
    with get_connection() as connection:
        return QualityReportService(connection).list_parameters(tenant_id=tenant.tenant_id, report_id=report_id)


@router.post("/quality-reports/{report_id}/parameters", status_code=status.HTTP_201_CREATED)
def save_parameter_entry(
    report_id: str,
    body: ParameterEntryRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).save_parameter_entry(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id,
            group_key=body.group_key, entry_label=body.entry_label, fields=body.fields,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return result.value


@router.delete("/quality-reports/{report_id}/parameters/{entry_id}")
def delete_parameter_entry(
    report_id: str,
    entry_id: str,
    tenant: TenantContext = Depends(require_permission("qc.manage_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).delete_parameter_entry(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id, entry_id=entry_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return {"deleted": entry_id}
```

Add `"INVALID_GROUP"` and `"INVALID_FIELD"` and `"LINE_NOT_FOUND"` to `_err_status`'s 409 list only if they represent a conflict; they're really 400s (bad input), so leave `_err_status` as-is — they fall through to the default `HTTP_400_BAD_REQUEST`, which is correct.

- [ ] **Step 4: Update serialization functions**

```python
def _serialize_report(report: QualityReport) -> dict:
    return {
        "id": report.id,
        "shift_report_id": report.shift_report_id,
        "report_date": report.report_date.isoformat(),
        "status": report.status,
        "revision": report.revision,
        "team": report.team,
        "shift": report.shift,
        "created_by": report.created_by,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at is not None else None,
        "validated_by": report.validated_by,
        "validated_at": report.validated_at.isoformat() if report.validated_at is not None else None,
        "rejection_reason": report.rejection_reason,
    }


def _serialize_detail(detail: QualityReportDetail) -> dict:
    return {"comments": detail.comments, "corrective_action": detail.corrective_action}


def _serialize_line(line) -> dict:
    return {
        "id": line.id,
        "shift_packing_row_id": line.shift_packing_row_id,
        "of_id": line.of_id,
        "product_id": line.product_id,
        "conforming_cartons": line.conforming_cartons,
        "non_conforming_cartons": line.non_conforming_cartons,
        "defect_details": line.defect_details,
    }


def _serialize_report_with_detail(value: dict) -> dict:
    detail = value.get("detail")
    return {
        **_serialize_report(value["report"]),
        "detail": _serialize_detail(detail) if detail is not None else None,
        "lines": [_serialize_line(l) for l in value.get("lines", [])],
    }
```

Update `_serialize_follow_up` to include `conformity_line_id`:
```python
def _serialize_follow_up(follow_up: FollowUp) -> dict:
    return {
        "id": follow_up.id,
        "quality_report_id": follow_up.quality_report_id,
        "of_id": follow_up.of_id,
        "conformity_line_id": follow_up.conformity_line_id,
        "window_ends_on": follow_up.window_ends_on.isoformat(),
        "observed_on": follow_up.observed_on.isoformat(),
        "status": follow_up.status,
        "result": follow_up.result,
        "observation": follow_up.observation,
        "actor_id": follow_up.actor_id,
    }
```

Update the `ConformityLine`/`FollowUp` import line at the top of the file to include `ConformityLine`.

Also update `FollowUpService._row_to_follow_up` and its `_FOLLOW_UP_COLUMNS`/`_FOLLOW_UP_INSERT_COLUMNS` in `quality_service.py` to include `conformity_line_id` — go back and check this was covered; if Task 5 Step 3.18 already inserts `conformity_line_id` into `quality_follow_ups`, `_FOLLOW_UP_COLUMNS` (used by `list_follow_ups`) must select it too:

```python
_FOLLOW_UP_COLUMNS = """
    id, quality_report_id, of_id, conformity_line_id, window_ends_on, observed_on, status, result, observation, actor_id
"""

def _row_to_follow_up(row: tuple) -> FollowUp:
    return FollowUp(
        id=row[0], quality_report_id=row[1], of_id=row[2], conformity_line_id=row[3],
        window_ends_on=row[4], observed_on=row[5], status=row[6], result=row[7], observation=row[8], actor_id=row[9],
    )
```

`record_observation`'s manual (non-validation) follow-up insert uses `_FOLLOW_UP_INSERT_COLUMNS` — since a manually recorded follow-up isn't tied to a specific conformity line, leave `conformity_line_id` NULL there:
```python
_FOLLOW_UP_INSERT_COLUMNS = """
    quality_report_id, of_id, window_ends_on, observed_on, status, result, observation, actor_id
"""
```
(unchanged from today — `record_observation` still inserts the 8-column set without `conformity_line_id`; only `validate_report`'s insert in Task 5 Step 3.18 supplies it. Confirm the two INSERT statements use column lists matching their own value tuples — they already do, since `validate_report` writes its own explicit column list rather than reusing `_FOLLOW_UP_INSERT_COLUMNS`.)

- [ ] **Step 5: Run the full qc backend suite**

Run: `.venv/Scripts/python -m pytest modules/qc -q`
Expected: PASS across every qc test file (domain, service, router-level integration). Fix any remaining mismatches surfaced here — this is the first point every prior task's changes are exercised together through the router layer conceptually (the tests call the services directly, not the FastAPI app, so also do a quick manual smoke check in Step 6).

- [ ] **Step 6: Smoke-check the router imports cleanly**

Run: `.venv/Scripts/python -c "from app.main import app"` (from `backend/`) to catch a router-level syntax/import error FastAPI's route registration would otherwise hide until first request.

Expected: no error.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/qc/api/router.py backend/modules/qc/api/quality_service.py
git commit -m "feat(qc): router surface for shift-based reports, conformity lines, and parameters

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 10: Port remaining qc test files off the legacy report shapes

**Files:**
- Modify: `backend/modules/qc/api/test_disposition_summary_integration.py`

**Interfaces:**
- Consumes: the same shift-based fixtures introduced in Task 5.

- [ ] **Step 1: Read the file and identify every legacy call site**

Run: search for `conditionnement_report_id`, `QualityReportDetail(`, `ProductionReportService`, `ConditionnementReportService` inside `test_disposition_summary_integration.py`.

- [ ] **Step 2: Rewrite its fixtures/helpers to the shift-based pattern**

Follow the exact same substitution as Task 5 Step 1/5 (build a validated shift via `ShiftReportService` + `ShiftValidationService`, create the QC report via `shift_report_id`, edit conformity lines via `update_draft(lines=[...])`).

- [ ] **Step 3: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest modules/qc/api/test_disposition_summary_integration.py -q`
Expected: PASS.

- [ ] **Step 4: Run the entire qc suite once more**

Run: `.venv/Scripts/python -m pytest modules/qc -q`
Expected: PASS, no skips due to a DB connection issue (per `CLAUDE.md`: a green run with many skips means nothing was tested — confirm the output shows real pass counts, not skips).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/qc/api/test_disposition_summary_integration.py
git commit -m "test(qc): port disposition summary tests off the legacy conditionnement fixtures

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 11: Production — StockReleaseService reads QC-validated conforming quantity

**Files:**
- Modify: `backend/modules/qc/api/quality_service.py` (add `get_validated_conforming`)
- Modify: `backend/modules/production/api/stock_release_service.py`
- Modify: `backend/modules/production/api/test_stock_release_integration.py`

**Interfaces:**
- Produces (qc side): `QualityReportService.get_validated_conforming(tenant_id, day) -> dict[str, float]` (product_id → conforming pieces, converted via `packets_per_carton` like the rest of `stock_release_service.py`).
- Produces (production side): `StockReleaseService._list_for` items gain `pending_qc: float`; `releasable` capped by QC; `release()` refuses a request exceeding the QC-validated cap.

- [ ] **Step 1: Add `get_validated_conforming` to `QualityReportService`**

This must call into production through a service function, not read `production.shift_packing_rows` directly (module-boundary rule) — that helper is added in Step 2 below (`packing_row_packets_per_carton` in `report_product.py`); implement this method after Step 2's helper exists. `r.report_date` here is the QC report's own `report_date`, copied from the shift at creation time (Task 5 Step 3.14) and always equal to the shift's own date, so no join to `shift_reports` is needed at all:

```python
def get_validated_conforming(self, *, tenant_id: str, day: datetime.date) -> dict[str, float]:
    from modules.production.api.report_product import packing_row_packets_per_carton
    from modules.production.domain.packaging_estimate import finished_quantity_from_count

    rows = self._connection.execute(
        """
        SELECT l.product_id, l.shift_packing_row_id, l.conforming_cartons
        FROM qc.quality_conformity_lines l
        JOIN qc.quality_reports r ON r.id = l.report_id AND r.tenant_id = l.tenant_id
        WHERE l.tenant_id = %s AND r.status = 'validated' AND r.report_date = %s
        """,
        (tenant_id, day),
    ).fetchall()
    per_carton_by_row = packing_row_packets_per_carton(
        self._connection, tenant_id=tenant_id, shift_packing_row_ids=[r[1] for r in rows]
    )
    totals: dict[str, float] = {}
    for product_id, row_id, conforming_cartons in rows:
        per_carton = per_carton_by_row.get(row_id)
        pieces = finished_quantity_from_count(
            packets_per_carton=per_carton, carton_quantity=float(conforming_cartons), packets_counted=float(conforming_cartons),
        )
        totals[product_id] = totals.get(product_id, 0.0) + pieces
    return totals
```

Note `r.report_date` here is the **QC report's own** `report_date` (copied from the shift at creation, per Task 5 Step 3.14), which always equals the shift's `report_date` — no join to `shift_reports` needed at all. Simpler and keeps the module boundary clean.

- [ ] **Step 2: Add `packing_row_packets_per_carton` to `report_product.py`**

```python
def packing_row_packets_per_carton(
    connection: psycopg.Connection, *, tenant_id: str, shift_packing_row_ids: list[str]
) -> dict[str, float | None]:
    """Each row's own frozen packets-per-carton snapshot, for a caller converting its conforming
    carton count to pieces without re-reading the product's current (possibly since-changed) setting."""
    if not shift_packing_row_ids:
        return {}
    rows = connection.execute(
        "SELECT id, snapshot_packets_per_carton FROM production.shift_packing_rows WHERE tenant_id = %s AND id = ANY(%s)",
        (tenant_id, shift_packing_row_ids),
    ).fetchall()
    return {row_id: float(per_carton) if per_carton else None for row_id, per_carton in rows}
```

- [ ] **Step 3: Write the failing tests in `test_stock_release_integration.py`**

Read the file's existing fixtures first (`env`, `stores`, `_submitted_shift`, `_validate` — imported from `test_shift_machine_integration.py`). Add:

```python
from modules.qc.api.quality_service import QualityReportService


def _validated_qc_report(db, env, shift_id, *, conforming, non_conforming=0, defect_details=None):
    qc = QualityReportService(db)
    report = _ok(qc.create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))["report"]
    line = qc._load_lines(tenant_id=TENANT, report_id=report.id)[0]
    _ok(qc.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{
            "shift_packing_row_id": line.shift_packing_row_id,
            "conforming_cartons": conforming, "non_conforming_cartons": non_conforming, "defect_details": defect_details,
        }],
    ))
    _ok(qc.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id))
    _ok(qc.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())))
    return report.id


def test_a_product_with_no_qc_report_yet_is_all_pending(db, env, stores):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    [item] = _list(db)["items"]
    assert item["releasable"] == 0
    assert item["pending_qc"] == item["packed"]


def test_qc_validated_conforming_becomes_releasable(db, env, stores):
    """`_submitted_shift` (test_shift_machine_integration.py) packs env["pasta"] via packets_counted=120
    with no carton tier engaged on the packing row itself (carton_quantity is never set), so
    finished_quantity_from_count falls to its packets_counted fallback: packed == 120 pieces
    (confirmed by the existing test_the_list_shows_what_was_packed_that_day_and_where_it_will_go,
    which asserts the same (120, 0, 120, 120) tuple before this task's QC cap existed).
    """
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    _validated_qc_report(db, env, shift_id, conforming=80, non_conforming=40, defect_details="soudure")
    [item] = _list(db)["items"]
    assert item["packed"] == 120
    assert item["releasable"] == 80
    assert item["pending_qc"] == 40


def test_release_is_refused_above_the_qc_validated_cap_even_within_on_hand(db, env, stores):
    shift_id = _submitted_shift(db, env)
    _validate(db, env, shift_id)
    _validated_qc_report(db, env, shift_id, conforming=10, non_conforming=0)  # far below the 120 on hand
    result = StockReleaseService(db).release(
        tenant_id=TENANT, actor_id=env["actor"], day=DAY,
        items=[{"product_id": env["pasta"], "quantity": 120}],  # ask for everything packed, not just what QC cleared
    )
    assert isinstance(result, Err)
    assert result.code == "EXCEEDS_QC_VALIDATED"
```

Note: `conforming`/`non_conforming` passed to `_validated_qc_report` are **carton** counts on the QC report, but since this fixture's packing row has no carton tier engaged, `get_validated_conforming`'s call to `finished_quantity_from_count` also falls to its `packets_counted` fallback — passing the carton count straight through as the piece count (see Task 11 Step 1's implementation: `packets_counted=float(conforming_cartons)`). This is why `conforming=80` directly yields `releasable == 80` with no `packets_per_carton` multiplication; if a future test uses a product with an engaged carton tier, the multiplication applies instead. This must actually run against the real fixture before being trusted — Step 2 below is not optional.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest modules/production/api/test_stock_release_integration.py -k qc -q`
Expected: FAIL — `item["pending_qc"]` KeyError, since `_list_for` doesn't produce it yet, and `EXCEEDS_QC_VALIDATED` doesn't exist in `release()` yet.

- [ ] **Step 3: Implement the cap in `stock_release_service.py`**

Add the import `from modules.qc.api.quality_service import QualityReportService` at the top. In `_list_for`:

```python
def _list_for(self, tenant_id: str, day: datetime.date, today: datetime.date) -> dict:
    header = {"day": day.isoformat(), "today": today.isoformat()}
    line_id = self._line_store(tenant_id)
    if line_id is None:
        return {**header, "line_store": None, "items": []}
    names = {location.id: location.name for location in LocationService(self._connection).list_locations(tenant_id=tenant_id)}
    on_hand = {level.product_id: level.quantity_on_hand for level in self._stock.list_stock_items(tenant_id, location_id=line_id)}
    released = self._released_on(tenant_id, day)
    qc_validated = QualityReportService(self._connection).get_validated_conforming(tenant_id=tenant_id, day=day)
    items = []
    for product_id, packed in self._packed_on(tenant_id, day).items():
        product = self._core.get_product(tenant_id, product_id)
        if product is None:
            continue
        remaining = max(packed - released.get(product_id, 0.0), 0.0)
        destination = product.default_location_id
        per_carton = product.packets_per_carton
        classification = self._classifications.get_classification(tenant_id, product_id)
        qc_conforming = qc_validated.get(product_id, 0.0)
        # What QC has cleared, minus what's already been released -- the same "remaining" idea as
        # the packed-based figure, but capped by validated conformity instead of by everything packed.
        qc_remaining = max(qc_conforming - released.get(product_id, 0.0), 0.0)
        items.append(
            {
                "product_id": product.id,
                "product_name": product.name,
                "uom_id": product.uom_id,
                "packets_per_carton": per_carton if per_carton and per_carton > 0 else None,
                "packaging_format": classification.packaging_format if classification else None,
                "packed": packed,
                "released": released.get(product_id, 0.0),
                "remaining": remaining,
                "releasable": min(remaining, max(on_hand.get(product_id, 0.0), 0.0), qc_remaining),
                "pending_qc": max(packed - qc_conforming, 0.0),
                "destination": {"id": destination, "name": names.get(destination)} if destination else None,
            }
        )
```

In `release()`, add the QC check inside the per-item validation loop, after the existing `EXCEEDS_PACKED` check:

```python
qc_validated = QualityReportService(self._connection).get_validated_conforming(tenant_id=tenant_id, day=day)
...
for item in items:
    ...
    left = packed.get(product_id, 0.0) - released.get(product_id, 0.0)
    if quantity > left + _EPSILON:
        return Err("EXCEEDS_PACKED", f"{product.name}: only {max(left, 0.0):g} of what was packed on {day.isoformat()} is left to release, {quantity:g} asked")
    qc_left = qc_validated.get(product_id, 0.0) - released.get(product_id, 0.0)
    if quantity > qc_left + _EPSILON:
        return Err(
            "EXCEEDS_QC_VALIDATED",
            f"{product.name}: only {max(qc_left, 0.0):g} has been validated by quality control, {quantity:g} asked",
        )
    if not product.default_location_id:
        ...
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `.venv/Scripts/python -m pytest modules/production/api/test_stock_release_integration.py -q`
Expected: PASS — every existing test in the file too (they didn't validate a QC report, so `qc_validated` is empty for their products; confirm this doesn't break them — if an existing test asserts `releasable == packed` without ever creating a QC report, it will now fail since `qc_remaining` is 0). **This is expected and must be fixed**: those existing tests represent a real behavior change (packed-but-not-QC'd stock is no longer releasable), so update each one to call `_validated_qc_report(db, env, shift_id, conforming=<the packed amount>)` after `_validate(...)`, matching the spec's decision 8. Do not weaken the new cap to make old tests pass unchanged — the old tests' assumption is exactly what this task changes.

- [ ] **Step 5: Run the full production + qc suites**

Run: `.venv/Scripts/python -m pytest modules/production modules/qc -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/qc/api/quality_service.py backend/modules/production/api/report_product.py backend/modules/production/api/stock_release_service.py backend/modules/production/api/test_stock_release_integration.py
git commit -m "feat(production): cap the Libéré release at QC-validated conforming quantity

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 12: Frontend — qc/api.ts types and endpoints

**Files:**
- Modify: `frontend/src/features/qc/api.ts`

**Interfaces:**
- Produces: `QualityReport` (no `of_id`/`product_id`/`conditionnement_report_id`, has `shift_report_id`), `QualityReportDetail` (`comments`, `corrective_action` only), `ConformityLine`, `ParameterEntry`, `listInspectableShiftReports`, `listParameters`, `saveParameterEntry`, `deleteParameterEntry`, updated `createQualityReport`/`updateQualityReport`/`adminUpdateQualityReport`/`validateQualityReport` signatures.

- [ ] **Step 1: Read the current file in full**

Read `frontend/src/features/qc/api.ts` completely (it's referenced above by line but not fully shown — read it before editing) to catch every type/function that needs updating, not just the ones already spotted via grep.

- [ ] **Step 2: Apply the type and function changes**

Replace the `QualityReport` interface:
```typescript
export interface QualityReport {
  id: string;
  shift_report_id: string;
  report_date: string;
  status: "draft" | "submitted" | "validated" | "rejected";
  revision: number;
  team: string | null;
  shift: string | null;
  created_by: string | null;
  submitted_at: string | null;
  validated_by: string | null;
  validated_at: string | null;
  rejection_reason: string | null;
}

export interface QualityReportDetail {
  comments: string | null;
  corrective_action: string | null;
}

export interface ConformityLine {
  id: string;
  shift_packing_row_id: string;
  of_id: string;
  product_id: string;
  conforming_cartons: number;
  non_conforming_cartons: number;
  defect_details: string | null;
}

export interface QualityReportWithDetail extends QualityReport {
  detail: QualityReportDetail | null;
  lines: ConformityLine[];
}

export interface InspectableShiftReport {
  shift_report_id: string;
  work_center_id: string;
  report_date: string;
  shift: string | null;
  team: string | null;
}

export interface ParameterEntry {
  id: string;
  group_key: string;
  entry_label: string | null;
  fields: Record<string, number | string | null>;
}
```

Replace `createQualityReport`:
```typescript
export function createQualityReport(token: string, shiftReportId: string) {
  return apiFetch<QualityReportWithDetail>("/qc/quality-reports", {
    method: "POST", token, body: { shift_report_id: shiftReportId },
  });
}
```

Replace `updateQualityReport`:
```typescript
export function updateQualityReport(
  token: string,
  reportId: string,
  input: { lines: Partial<ConformityLine>[]; detail?: Partial<QualityReportDetail> },
) {
  return apiFetch<QualityReportWithDetail>(`/qc/quality-reports/${reportId}`, {
    method: "PATCH", token, body: input,
  });
}
```

Replace `adminUpdateQualityReport` similarly (adds `shift_report_id?: string; reason?: string`).

Replace `listInspectableConditionnementReports` with:
```typescript
export function listInspectableShiftReports(token: string) {
  return apiFetch<InspectableShiftReport[]>("/qc/shift-reports", { token });
}
```

Replace `validateQualityReport` to drop `product_id`:
```typescript
export function validateQualityReport(token: string, reportId: string, correlationId: string) {
  return apiFetch<{ report: QualityReport; lines: ConformityLine[]; follow_ups: { follow_up_id: string; of_id: string; window_ends_on: string }[] }>(
    `/qc/quality-reports/${reportId}/validate`,
    { method: "POST", token, body: { correlation_id: correlationId } },
  );
}
```

Add:
```typescript
export function listParameters(token: string, reportId: string) {
  return apiFetch<ParameterEntry[]>(`/qc/quality-reports/${reportId}/parameters`, { token });
}

export function saveParameterEntry(
  token: string, reportId: string, input: { group_key: string; entry_label?: string | null; fields: Record<string, number | string | null> },
) {
  return apiFetch<ParameterEntry>(`/qc/quality-reports/${reportId}/parameters`, { method: "POST", token, body: input });
}

export function deleteParameterEntry(token: string, reportId: string, entryId: string) {
  return apiFetch<{ deleted: string }>(`/qc/quality-reports/${reportId}/parameters/${entryId}`, { method: "DELETE", token });
}
```

Remove `listQualityIndexTrend` and its response type (the five-index analytics call — deleted per spec decision 4).

Update `getQualityReport`'s return type to `QualityReportWithDetail`.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: errors listing every call site across the codebase that still references the old shapes — this is the todo list for Task 13.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/qc/api.ts
git commit -m "feat(qc): frontend types/endpoints for shift-based reports and conformity lines

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

(Committed even though downstream files won't typecheck yet — Task 13 fixes them next; keeping this as its own commit makes the diff reviewable per-layer, matching how the backend tasks were split.)

---

## Task 13: Frontend — QualityReportsTab conformity-line table, parameters section, dropped index fields

**Files:**
- Modify: `frontend/src/features/qc/QualityReportsTab.tsx`
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: everything from Task 12.

- [ ] **Step 1: Read the full current file**

Read `frontend/src/features/qc/QualityReportsTab.tsx` in its entirety (it's long — over 1000 lines per the line numbers already seen; read it fully before editing since this task touches the create form, the detail/edit dialog, and the figures list).

- [ ] **Step 2: Replace the create form's report picker**

The `conditionnement_report_id` select (around today's line 508-521) becomes a `shift_report_id` select sourced from `listInspectableShiftReports`. Update `createSchema` (Zod) to require `shift_report_id` instead of `conditionnement_report_id`, and the `defaultValues`/`watch` call sites accordingly.

- [ ] **Step 3: Replace the conforming/non-conforming/defect inputs with a per-line table**

Where the detail dialog currently renders `conforming_cartons`/`non_conforming_cartons`/`defect_details` as three fields (today's lines ~1082-1093 plus the `figures` array around line 765-784), replace with a small editable table: one row per `full.lines[i]`, columns Product (read-only, resolved from `product_id` via the already-loaded `ncProducts` query), Conforming, Non-conforming, Defect details. Each row's edits accumulate into a local `lines` state array keyed by `shift_packing_row_id`, sent as `updateQualityReport(token, report.id, { lines, detail: { comments, corrective_action } })` on save — reuse the existing `saveMutation` pattern, just change what `toDetail`-equivalent function builds from form state.

Remove the five process-index fields (`pre_dryer_index`, `humidity_percentage`, `cooling_index`, `pf_index`, `sumo_index`) from the form, the Zod schema, `EMPTY_DETAIL`, and the `figures` array entirely.

- [ ] **Step 4: Add a Paramètres section**

Below the conformity table, add a collapsible section per the nine `PARAMETER_GROUPS` keys (hardcode the same nine keys client-side, matching `backend/modules/qc/domain/parameters.py`'s `PARAMETER_GROUPS` — do not fetch the schema from the server; it's small and static). Each group renders its saved entries (`useQuery(["qc", "parameters", report.id], () => listParameters(token, report.id))`, filtered client-side by `group_key`) as a small table with an "Ajouter" row that calls `saveParameterEntry`, and a delete action per row calling `deleteParameterEntry`. Invalidate the parameters query key on both mutations' `onSuccess`.

- [ ] **Step 5: Add i18n strings**

Add to `frontend/src/lib/i18n.tsx` (both `en` and `fr` keys) for: the nine group titles/short labels, "Produit", "Conforme", "Non conforme", the parameters section title, "Ajouter une entrée", and any removed-field label cleanup (delete the five index field keys if `i18n.tsx` centralizes them — check whether `QualityReportsTab.tsx` used inline `t("qc.quality.field.preDryer")`-style keys per the earlier grep; if so, remove those five keys from `i18n.tsx` too, don't leave them orphaned).

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: fewer errors than Task 12's run; fix any remaining ones in this file before moving on.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/qc/QualityReportsTab.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(qc): per-product conformity table and Contrôle des paramètres on the QC report screen

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 14: Frontend — dependent screens updated to the new response shapes

**Files:**
- Modify: `frontend/src/features/qc/QualityDashboardTab.tsx`
- Modify: `frontend/src/features/analytics/TeamPerformanceTab.tsx`
- Modify: `frontend/src/features/production/ValidationCenterTab.tsx`
- Modify: `frontend/src/features/production/ProductionDashboardTab.tsx`
- Modify: `frontend/src/features/production/api.ts`
- Modify: `frontend/src/features/production/WorkOrderDetailsPage.tsx`
- Modify: `frontend/src/features/analytics/manufacturing/metrics.ts`
- Modify: `frontend/src/features/production/board/QualityBlock.tsx`

**Interfaces:**
- Consumes: Task 12's `api.ts`.

- [ ] **Step 1: Run the typecheck from Task 12 again to get the current error list**

Run: `cd frontend && npx tsc -b --force`
Expected: a list of remaining errors scoped to these eight files (Task 13 already cleared `QualityReportsTab.tsx`). Work through them one file at a time.

- [ ] **Step 2: Fix each file**

For each error: if it references `listQualityIndexTrend` or the five process indices, remove that UI (chart/stat) entirely rather than stub it — the spec removed the underlying data. If it references `conditionnement_report_id`/report-level `conforming_cartons`, switch to the new `lines`-based shape (sum across `lines` where a total is needed, e.g. `ProductionDashboardTab.tsx`'s pending-clearance count already sums `conformity.data` from `team_conformity`, whose response shape is unchanged — likely only a type import needs updating there, not logic). `QualityBlock.tsx`'s `listInspectableConditionnementReports` call becomes `listInspectableShiftReports`.

For each fix, keep the change minimal and confirm the surrounding logic still makes sense against the new data (e.g. `WorkOrderDetailsPage.tsx` may read `QualityReport.of_id` directly somewhere — that field no longer exists on the header; find where the OF's conformity actually comes from, which should already be `get_conformity_summary`/`team_conformity`-shaped data unaffected by this refactor, not the raw report object).

- [ ] **Step 3: Typecheck until clean**

Run: `cd frontend && npx tsc -b --force`
Expected: PASS with zero errors, repeated after each file's fix.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/qc/QualityDashboardTab.tsx frontend/src/features/analytics/TeamPerformanceTab.tsx frontend/src/features/production/ValidationCenterTab.tsx frontend/src/features/production/ProductionDashboardTab.tsx frontend/src/features/production/api.ts frontend/src/features/production/WorkOrderDetailsPage.tsx frontend/src/features/analytics/manufacturing/metrics.ts frontend/src/features/production/board/QualityBlock.tsx
git commit -m "fix(qc): update dependent screens to the shift-based QC report shapes

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 15: Frontend — Libéré dialog shows pending_qc

**Files:**
- Modify: `frontend/src/features/production/board/api.ts`
- Modify: `frontend/src/features/production/board/ReleaseStockDialog.tsx`
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: Task 11's `pending_qc` field.

- [ ] **Step 1: Add `pending_qc` to `ReleaseItem`**

In `frontend/src/features/production/board/api.ts`:
```typescript
export interface ReleaseItem {
  product_id: string;
  product_name: string;
  uom_id: string;
  packets_per_carton: number | null;
  packaging_format: "packet" | "carton" | "sac" | null;
  packed: number;
  released: number;
  remaining: number;
  releasable: number;
  /** What was packed but is not yet cleared by quality control (pending or non-conforming), in the product's own unit. */
  pending_qc: number;
  destination: { id: string; name: string | null } | null;
}
```

- [ ] **Step 2: Show it in the dialog**

In `ReleaseStockDialog.tsx`, inside the quantity cell's `else` branch (today's line ~205-209, the `!canRelease(item)` case), add a QC-specific message before the existing "not in line store"/"already released" text:

```tsx
<td className="px-2 py-2">
  {canRelease(item) ? (
    /* ...unchanged... */
  ) : (
    <span className="text-xs text-muted-foreground">
      {item.remaining <= 0
        ? t("production.board.release.alreadyReleased")
        : item.pending_qc > 0 && item.destination !== null
          ? t("production.board.release.pendingQc")
          : item.destination === null
            ? ""
            : t("production.board.release.notInLineStore")}
    </span>
  )}
</td>
```

Also show `pending_qc` as an info line next to the "packed" column whenever it's > 0, regardless of `canRelease`, so a partially-cleared product still shows both figures:

```tsx
<td className="px-2 py-2 text-right tabular-nums">
  {formatQuantity(item.packed / factor, unit)}
  {factor !== 1 ? <span className="block text-xs text-muted-foreground">{formatQuantity(item.packed, unitOf(item.uom_id))}</span> : null}
  {item.pending_qc > 0 ? (
    <span className="block text-xs text-amber-600">{formatQuantity(item.pending_qc / factor, unit)} {t("production.board.release.pendingQcShort")}</span>
  ) : null}
</td>
```

- [ ] **Step 3: Add the i18n keys**

In `frontend/src/lib/i18n.tsx`, add both `en`/`fr` entries for `production.board.release.pendingQc` ("Waiting on quality control" / "En attente de validation qualité") and `production.board.release.pendingQcShort` ("pending QC" / "en attente QC").

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: PASS, zero errors across the whole frontend (this is the final typecheck for the plan — if anything else broke, fix it here).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/production/board/api.ts frontend/src/features/production/board/ReleaseStockDialog.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(production): show QC-pending quantity on the Libéré dialog

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 16: Seed data — rewrite seed_qc_month.py against shift reports

**Files:**
- Modify: `backend/scripts/seed_qc_month.py`

**Interfaces:**
- Consumes: `ShiftReportService`, `ShiftValidationService`, `QualityReportService.create_report(shift_report_id=...)`, `update_draft(lines=...)`, `save_parameter_entry`.

- [ ] **Step 1: Read the current script in full**

Read `backend/scripts/seed_qc_month.py` completely to understand its current loop structure (which days/shifts/products it seeds, what conformity spread it uses).

- [ ] **Step 2: Rewrite it against shift reports**

Replace every `ConditionnementReportService`/`ProductionReportService` call with the equivalent `ShiftReportService`/`ShiftValidationService` sequence (same pattern as `_validated_shift` in Task 5), and every `QualityReportService.create_report(conditionnement_report_id=...)` / `update_draft(detail=QualityReportDetail(conforming_cartons=..., ...))` call with `create_report(shift_report_id=...)` / `update_draft(lines=[{...}])`. Add a handful of parameter entries per seeded report via `save_parameter_entry` across a few of the nine groups, so the new screen has something to show (e.g. 2-3 groups populated per seeded shift, not all nine every time — matches how the real paper sheet is filled inconsistently).

- [ ] **Step 3: Run the script against the dev database**

Run: `.venv/Scripts/python -m scripts.seed_qc_month` (from `backend/`, matching the existing seed script invocation convention in `CLAUDE.md`).

Expected: completes without error; spot-check a few rows via `psql` or the demo login (`demo@sonalim-erp.local` / `demo1234`) in the QC screen.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/seed_qc_month.py
git commit -m "chore(qc): reseed QC month data against shift reports

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 17: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Backend full suite**

Run: `.venv/Scripts/python -m pytest modules/production modules/qc -q` (from `backend/`, with the venv active and a real Postgres reachable — confirm `DATABASE_URL`/`TEST_DATABASE_URL` per `CLAUDE.md` so this doesn't silently skip).

Expected: PASS, with a real (non-zero, non-skipped) test count reported.

- [ ] **Step 2: Frontend typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: PASS, zero errors.

- [ ] **Step 3: Browser walkthrough**

Using the demo login + session-seeding recipe (per project memory), manually verify: create a QC report from a validated multi-product shift; edit per-product conformity + defect details; save a few parameter entries across at least 3 of the 9 groups; submit; validate; raise a non-conformity from one conformity line and confirm its quantity; open the Libéré dialog for that day and confirm the just-validated product shows the correct `releasable`/`pending_qc` split, and that a product from a shift whose QC report is still draft shows `pending_qc === packed`.

- [ ] **Step 4: Report results**

State plainly which of Steps 1-3 passed and which didn't, with actual output — do not claim success without having run them.

---

## Self-review notes

- **Spec coverage:** decisions 1 (shift_report_id link) → Tasks 1, 5; decision 2 (parameters on QC report) → Tasks 2, 4, 7, 9 Step 3, 13 Step 4; decision 3 (per-product conformity lines, of_id per line) → Tasks 1, 3, 5; decision 4 (indices removed) → Tasks 3, 6, 9, 12, 13; decision 5 (defect_details per line, comments/corrective_action per report) → Tasks 1, 3, 5; decision 6 (follow-ups per line) → Tasks 1, 5, 9; decision 7 (truncate, no conversion) → Task 1; decision 8 (release cap, enforced in both read and write paths) → Task 11. All eight decisions have an owning task.
- **Placeholder scan:** the draft of Task 11 originally left a `# confirm against...` comment and a scratch `if False else` ternary in example code — both replaced with the final, concrete version inline before this plan was saved; no such markers remain.
- **Type consistency:** `ConformityLine`/`QualityReportDetail`/`FollowUp` field names are identical across `domain/quality.py` (Task 3), `api/quality_service.py` (Tasks 5-9), `api/router.py` serialization (Task 9), and `frontend/api.ts` (Task 12) — `shift_packing_row_id`, `of_id`, `product_id`, `conforming_cartons`, `non_conforming_cartons`, `defect_details` used consistently throughout. `get_validated_conforming`/`pending_qc` naming matches between Task 11's backend and Task 15's frontend.
- **Review Focus coverage:** each of the five items has an owning task and explicit test — multi-OF shift NC cleanup (Task 6's summary test + existing `reject_report` behavior, unchanged query already scoped correctly), pending-QC dialog display (Task 11 Step 3/Task 15), server-side release cap bypass (Task 11 Step 1 test `test_release_is_refused_above_the_qc_validated_cap_even_within_on_hand`), missing defect details per line (Task 3's domain tests + Task 5's `test_submit_requires_defect_details_when_a_line_is_non_conforming`), out-of-range parameter fields (Task 4's domain tests + Task 7's service-level `INVALID_FIELD` test).
