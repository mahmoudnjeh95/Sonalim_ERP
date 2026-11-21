# WP-1.1 Tax engine — plan

Spec: `specs/2026-11-21-tax-engine-design.md`.

1. [x] `core/domain/tax.py` (pure: validate code/rate/applies_to/exempt, DEFAULT_CODES) + `test_tax.py`.
2. [x] Migration `core/migrations/0031_core_tax_codes.sql` (schema only).
3. [x] `core/tax_codes.py` service (list, get, create, update, default_rate, audit) + integration tests.
4. [x] Finance router: `/finance/tax-codes` GET/POST/PATCH; permission `finance.manage_tax_codes` in
       `module.json`; grant to Administrateur like the other finance manage_* grants.
5. [x] Sales + procurement default VAT resolved from the default tax code; setting updates the code. Tests.
6. [x] `finance/api/vat_report_service.py` + `GET /finance/reports/vat` + integration test.
7. [x] Frontend: tax codes screen, VAT report page, en/fr keys, route + sidebar.
8. [x] Manifest/catalog tests, full backend suite on Postgres, `tsc` + vitest, ROADMAP log, commit, push.
