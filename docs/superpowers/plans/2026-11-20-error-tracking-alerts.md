# WP-0.6 Error tracking and alerts — plan

Spec: `docs/superpowers/specs/2026-11-20-error-tracking-alerts-design.md`.

1. [x] `sentry-sdk` in `backend/requirements.txt`.
2. [x] `core/observability.py`: `setup_logging`, `init_error_reporting`, `report_exception`,
   `send_alert`, `GrowthWatch`, `ErrorReportingMiddleware`; tests `core/test_observability.py`
   (no DB).
3. [x] API: middleware inside CORS, logging + Sentry at import; test the 500 shape.
4. [x] Worker: consumer failures reported (`core/events/consumers.py`), sweeps use
   `report_exception`, dispatcher reconnect loop, `consume_forever` exit reported.
5. [x] Finance: `PostingRefused.expected_refusal`, `open_counts_by_tenant()`, notification on
   new/reopened failure; integration test.
6. [x] `worker/alerts.py` monitor thread + gauges; tests with fakes.
7. [x] compose (`SENTRY_*`, `ALERT_*` env, worker metrics), `prometheus.yml` scrape,
   `.env.example`, `docs/operations` note, `CLAUDE.md`.
8. [x] Full backend suite on Postgres; roadmap progress log.
