# Plan: module manifests match the code (WP-0.5)

Spec: `specs/2026-11-20-module-manifests-design.md`.

1. [x] Write `backend/core/test_module_manifests.py`: depends / optional_depends against
   imports (module-level and lazy), no cycle, publishes against `publish_event` calls,
   subscribes against the consumer registry, worker imports, catalog rows, provides_api.
2. [x] Run it and list the drift: 22 failures over ten manifests and the catalog.
3. [x] Fix the manifests (`depends`, `optional_depends`, `provides_api`).
4. [x] Break the maintenance ↔ production module-level import cycle (lazy import in
   `history_export.journal_workbook`).
5. [x] Fix the catalog consumers (hr on payroll run events, `hr.presence_month.closed`).
6. [x] Check that the test fails when a manifest drifts (dropped `depends`, unhandled
   subscription).
7. [x] Run the `tests.yml` backend steps on Postgres 16 (migrations, `seed_dev`, full suite).
8. [x] Roadmap: tick WP-0.5, progress log.
