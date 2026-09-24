# Shift report lifecycle: drafts, delete, validator edits, day view

Date: 2026-09-22. Builds on `2026-09-20-shift-report-core-design.md` (section state machine, per-section revisions, whole-shift validation) and `2026-09-21-shift-form-rework-design.md`. Does not change the section list, the section state machine, or existing permission keys except as noted below.

## Why

Four gaps reported after the team started using the shift screen day to day:
1. Typed-but-unsaved edits are lost if someone navigates away before clicking Save — there is no autosave and no local backup, despite the original spec (section 7) calling for a `localStorage` copy that was never built.
2. There is no way to delete a shift report that was opened by mistake or abandoned before hand-in.
3. Once a shift is submitted, the Validation Center's review dialog renders every section read-only — a validator who spots a mistake must reject the whole section back to the team instead of fixing it themselves.
4. Picking an older date resolves to a single shift via a client-side `.find()` on shift name; there is no way to see every report filed on a given day across lines.

## Decisions (agreed 2026-09-22)

1. **Autosave writes through the existing draft save, plus a local backup.** No second draft store; a debounced autosave calls the same per-section save endpoint used by the explicit Save button, backed by a `localStorage` mirror for the gap before the debounce fires.
2. **Delete is a new dedicated permission**, `production.shift.delete`, granted per-user like the other shift permissions.
3. **"Not fully submitted" means shift status `open` or `returned`.** Nothing has posted to stock in either state, so deletion is low-blast-radius. `submitted` and `validated` shifts cannot be deleted.
4. **Validator edit is gated by `production.shift.validate` alone** (no new permission). Every validator edit requires a reason and is tagged `edited_by_validator` in the revision it freezes, distinct from a normal team revision.
5. **The day view applies to every date, including today.** Selecting a date always shows one row per shift report for that date across every line the user can view; today's current clock shift is highlighted with a shortcut into it.

## 1. Draft persistence

### 1.1 Autosave
`SectionCard.tsx`'s existing `dirty`/`draft` state (currently `useState` only) gets a debounced autosave: ~1.5s after the last field change, plus an immediate flush on section blur, tab/route change, and `beforeunload`. It calls the same `PUT /shift-reports/{id}/sections/{key}` the explicit Save button already uses — a section left as `draft` is already the server's source of truth, so no new endpoint or status is introduced. The explicit Save button stays (it's also how a user clears the "unsaved" state on demand); autosave and explicit Save both funnel into the same call and the same dirty-tracking.

The Save button's label/indicator changes from a static "unsaved" badge to a small status ("Enregistrement…" / "Enregistré à HH:MM"), reusing the save-on-blur indicator pattern already in `HeaderNames`.

### 1.2 localStorage backup
Per the original spec's section 7 (not previously implemented): on every field change, mirror the row's current in-memory value to `localStorage` under a key scoped to shift id + section key, wrapped in try/catch (private browsing / quota errors are swallowed, not surfaced). Cleared on a successful autosave or explicit save. On mount, `SectionCard` checks for a newer local copy than what the server returned and, if found, offers to restore it (a single non-blocking banner: "Des modifications non enregistrées ont été retrouvées — restaurer ?"). This only covers the debounce window; it is not a second source of truth once a save succeeds.

### 1.3 "My unfinished reports" strip
A horizontal strip at the top of the shift screen (shown regardless of the selected date) listing shifts with status `open` or `returned` across the lines the current user can view, sorted by date descending, capped at a handful with a "Voir tout" that lands on the day view (4) for the most recent one. Each entry is a chip: line, shift, date, and a "Continuer" link straight into that shift's editor. Backed by `list_shifts` filtered by `status in (open, returned)` — no new backend method, just a new query/filter combination on the existing one used by `HeaderNames`' datalist.

## 2. Delete right

- New permission `production.shift.delete` in `module.json`, granted per-user through the same screen as the other shift permissions (not bundled into `production.shift.edit.*` or `.validate`).
- New `delete_shift(shift_id, actor)` in `shift_report_service.py`:
  - permission check;
  - status check — `open` or `returned` only, else `409 DELETE_NOT_ALLOWED`;
  - in one transaction: delete child rows (`shift_report_sections`, `shift_section_revisions`, run rows, packing rows, packing waste, production waste, energy, etc. — whatever currently cascades or needs explicit cleanup, confirmed against the schema in the plan) then the `shift_reports` row;
  - `record_audit("shift_report.deleted", ...)` before the row is gone (actor, shift id, line, date, shift, status at time of delete).
- New `DELETE /shift-reports/{id}` in `router.py`, same auth pattern as the other shift endpoints.
- Frontend: a Delete action on the shift screen's header area, and on each day-view row (4), shown only when the viewer holds the permission and the row's status allows it. Confirms via a dialog before calling the endpoint (destructive, irreversible — no undo, no soft delete).

## 3. Validator edit

### 3.1 Editing from the Validation Center
`ShiftValidationPanel.tsx`'s review dialog currently renders every section read-only. Sections become editable in place (reusing `SectionCard`) whenever the reviewing user holds `production.shift.validate`, even though the shift's status is `submitted`. This does not change `_editable_section`'s existing rule for the normal team flow (still blocked once `validated`) — it adds a second, validator-specific path that is allowed exactly while `submitted`.

### 3.2 Backend
New `edit_section_as_validator(shift_id, section_key, rows, reason, actor)` in `shift_validation_service.py`:
- requires `production.shift.validate` and shift status `submitted`;
- `reason` is mandatory (empty/whitespace refused with `REASON_REQUIRED`);
- writes the section rows the same way `save_section` does, then calls the existing `_freeze_revision` with `reason` and a new `edited_by_validator=True` flag;
- does not change section or shift status — the section stays `submitted`, ready for the same Approve action.
- New `PUT /shift-reports/{id}/sections/{key}/validator-edit` endpoint (kept separate from the team's `PUT .../sections/{key}` so the two paths' gating and required-`reason` behavior don't have to share one signature).

### 3.3 Revision tagging
`shift_section_revisions` gets a new column `edited_by_validator boolean not null default false` (small migration, e.g. `0055`) set only by 3.2's path — this is recorded at write time rather than inferred later from the actor's current permissions, so history stays correct if permissions change afterward. The revision-history panel (already built in M5) shows these with a distinct badge, e.g. "Modifié par le validateur — <reason>", next to the existing revision number and normal reason display.

### 3.4 CHANGED_SINCE_OPENED interaction
`validate_shift`'s existing guard refuses validation if any section changed since the reviewer opened the shift for review. A validator's own edit through 3.2 must not trip this against themselves. Handling: after a successful validator edit, the review dialog's frontend state refetches the shift (as it already does after a reject), refreshing the "opened at" baseline it sends with the next Approve call — so approving after your own edit carries current section timestamps and passes. The guard still fires normally if someone else changes the shift concurrently (e.g. the team edits a different section mid-review) — no backend change to the guard itself.

## 4. Day view

### 4.1 List
Selecting a date shows one row per shift report for that date, across every line the current user can view (not narrowed to a single line first). Backed by `list_shifts`/`GET /shift-reports?report_date=`, with `work_center_id` made optional on that endpoint — when omitted, it returns shifts across every line the caller holds `production.shift.view` for.

Each row: line, shift (matin/après-midi/nuit), team name(s) from the header, status chip (draft/submitted/returned/validated — reusing the existing status vocabulary and colors from `StatusNode`), sections done as a fraction (e.g. 6/9), and who last touched it + when (from the latest audit entry or revision).

### 4.2 Interaction
- Clicking a row opens that shift in the existing single-shift editor (`ShiftReportTab`'s current detail view), with a "Retour à la journée" link back to the day list for the same date.
- A line/shift combination with no report yet for that date shows a "Nouveau" affordance instead of a row, gated by that section's edit permissions — same "Open shift" action that exists today, just per combination instead of a single button.
- Applies uniformly to every date, including today. Today's row for the viewer's current clock shift is highlighted with a "Continuer" shortcut, so the common case (walk up, keep filling today's shift) is still one click past the day list, not lost behind it.

### 4.3 Frontend
`ShiftReportTab.tsx`'s current flow (resolve params → query by date+line → `.find()` one shift → single editor or "Open shift" button) is replaced by: resolve the date (param or today) → render the day list (4.1) as the default view for that date → drill into a shift on row click. The date/line pickers that exist today move to filters on the day list rather than being the entry condition for reaching a shift.

## 5. Not in scope

- No change to the section state machine, whole-shift validation transaction, or targeted rejection (`reject_shift`, `reverse_shift`).
- No roles/bundling of permissions — `production.shift.delete` is granted per-user like the rest, same as decided for the core program.
- No offline support beyond the `localStorage` debounce backup (1.2) — this is not an offline-first rework.
- No change to how `CHANGED_SINCE_OPENED` behaves for the normal team-vs-validator race; only the validator's own edit is exempted, and only by refreshing the frontend's baseline.

## 6. Testing

- Backend integration tests (real DB, existing pattern):
  - autosave: no new backend behavior beyond what `save_section` already does, so covered by existing section-save tests plus a debounce/flush test at the frontend level;
  - `delete_shift`: permission check, status gate (open/returned allowed, submitted/validated refused), cascade of child rows, audit entry;
  - `edit_section_as_validator`: permission + status gate, `REASON_REQUIRED`, revision tagged `edited_by_validator`, section/shift status unchanged, and a case proving a validator's own edit does not trip `CHANGED_SINCE_OPENED` on their own subsequent `validate_shift` call while a genuine concurrent team edit still does;
  - `list_shifts` with `work_center_id` omitted returning shifts across all viewable lines for a date, filtered correctly by `production.shift.view`.
- Frontend: `npx tsc -b --force`, then a real-browser pass covering: type in a section, navigate away without saving, come back and see it restored; delete on an open and a returned shift, confirm it's refused on a submitted one; validator edit + reason + Approve from the Validation Center, and the revision-history badge; the day view on a seeded multi-shift, multi-line date, including a "Nouveau" affordance and the highlighted current-shift row on today.
- Full backend suites for production stay green (currently ~975 per the prior milestones).

## 7. Risks

- Cascade-deleting a shift touches several child tables (sections, revisions, runs, packing rows, waste, energy); the plan needs to enumerate them against the actual schema rather than assume `ON DELETE CASCADE` is set everywhere — some of these FKs may need explicit deletes in `delete_shift`.
- Making `work_center_id` optional on `GET /shift-reports` changes an existing endpoint's contract; other callers of `list_shifts` (e.g. `HeaderNames`' datalist, the "unfinished reports" strip in 1.3) must keep working when they do pass a filter.
- The `localStorage` restore banner (1.2) needs a clear rule for what counts as "newer" (local timestamp vs. server's `updated_at`) to avoid offering to restore a local copy that's actually older than what the server already has.
