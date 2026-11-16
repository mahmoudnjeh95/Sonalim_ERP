# B5 — Bank statement import, reconciliation and invoice-status reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Read `2026-11-03-treasury-interfaces.md` first. Needs B3.

**Goal:** Import bank statements (CSV/XLSX) into a bank journal, assign each line to a customer/supplier, match lines to recorded receipts/disbursements, and provide per-customer / per-supplier invoice-status reports with export.

**Architecture:** Pure parsing and matching in `treasury/domain/statement.py` (no DB, no file IO — takes already-read rows); `StatementImportService` handles file reading, preview and commit; reports are SQL read models in `ReportService` reading invoices through the public services (never their tables).

## Decisions

1. **File format:** the manual's columns (DATE, LIBELLE, DEBIT, CREDIT, SOLDE). Because banks differ, column names and date format are a per-bank **import profile**: `treasury.statement_profiles (account_id or bank_id, column_map_json, date_format, decimal_sep, has_header, skip_rows)`. Default profile = the manual's.
2. **Reading files:** CSV with the standard library; XLSX only if `openpyxl` is already a dependency (check `requirements`); otherwise accept CSV only and say so in the UI. Do not add a dependency without asking.
3. **Two-step import:** upload → parse → `preview` (rows, errors, duplicates) → `commit`. Nothing is written to `bank_statement_lines` before commit. Re-import of the same period is safe: a line is a duplicate when `(account_id, date, label, debit, credit, balance)` already exists → skipped and reported (`STATEMENT_DUPLICATE_LINE` is a per-line warning, not a failure).
4. **Sign convention (manual):** debit > 0 means money in (customer); credit > 0 means money out (supplier). A line with both or neither > 0 is a format error (`STATEMENT_FORMAT_INVALID`).
5. **Reconciliation:** each line may be linked to one receipt or disbursement payment (`matched_payment_id`, `matched_type`). Auto-suggest: same account, amount equal, date within ±5 days, unmatched; the user confirms. Matching never changes balances (the movement already exists); it only marks both sides reconciled and shows an unreconciled-difference figure per account (statement closing balance vs treasury balance).
6. **Party assignment:** debit line → choose from customers; credit line → suppliers (partners filtered by the existing partner-kind field — find how `core.partners` distinguishes them).
7. **Reports:** "Sales invoice status by customer" and "Purchase invoice status by supplier": per partner totals invoiced / paid / remaining, plus invoice drilldown with status and age buckets (0–30, 31–60, 61–90, 90+ days past due). Export CSV (XLSX if available per Decision 2).

## Tasks

### Task 1 — Domain
- [ ] `domain/statement.py` + tests, failing first: `parse_rows(rows, profile)` (dates, decimals with `,`/`.`, blanks), format errors with row numbers, `dedupe_key`, `suggest_matches(lines, payments, window_days=5)`, running-balance sanity check (warn when consecutive balances don't follow the line amounts). Implement; commit.

### Task 2 — Migration `treasury/0004_treasury_statements.sql`
- [ ] `statement_profiles`, `statement_imports (id, account_id, filename, imported_by, imported_at, row_count, skipped_count)`, `bank_statement_lines (id, import_id, account_id, line_date, label, debit, credit, balance, partner_id NULL, matched_type NULL, matched_id NULL, reconciled_at NULL)`; unique index on the dedupe key. Apply; commit.

### Task 3 — Import service and router
- [ ] Failing integration tests: preview does not write; commit writes and skips duplicates; bad rows reported with row numbers; partner assignment rules by sign; manual match and auto-suggest; reconciliation difference figure; delete a line only if unmatched; permission `import_statements`.
- [ ] Implement `StatementImportService` + router `/treasury/statements/preview`, `/commit`, `/lines`, `PATCH /lines/{id}` (partner, match), `/profiles`. Multipart upload size cap 5 MB. Audit imports. Commit.

### Task 4 — Reports
- [ ] Failing tests with seeded invoices and receipts: totals and buckets per partner; only validated+ invoices included; currency kept separate (no summing across currencies).
- [ ] Implement `ReportService` and routes `GET /treasury/reports/sales-invoices`, `/purchase-invoices` (`?format=csv`). Commit.

### Task 5 — Frontend
- [ ] Bank journal tab: upload dialog with profile choice, preview table with error/duplicate flags, commit; lines table with partner picker and match suggestions; reconciliation summary per account. Reports tab with partner totals, drilldown and export. i18n en+fr; `npx tsc -b --force`. Commit.

### Task 6 — Handoff
- [ ] Run treasury tests (report skips). Walk with a sample statement file (kept out of the repo; the pre-commit hook refuses dumps and real customer data must not be committed). Do not push.
