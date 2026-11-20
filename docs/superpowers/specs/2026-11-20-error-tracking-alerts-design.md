# WP-0.6 Error tracking and alerts — design

Date: 2026-11-20. Roadmap: `docs/ROADMAP.md` WP-0.6.

## What was there

- API: an unhandled exception became Starlette's plain-text `Internal Server Error`, outside
  the CORS middleware (so the browser saw a CORS error, not a 500), with only uvicorn's
  traceback in `docker logs`.
- Worker: `core/events/consumers._process` caught a handler's exception, rolled back and
  dead-lettered the message **without logging anything**. The sweeps `print()`ed one line.
  The outbox dispatcher thread had no `try` at all: one RabbitMQ hiccup killed it for good
  while the rest of the worker kept running, so events stopped flowing silently.
- Nobody was told when the dead-letter queue (`erp.events.dlq`) filled up, or when finance
  refused an automatic posting (`finance.posting_failures`) unless someone opened the
  Entries page.

## Design

### Error reporting (`core/observability.py`, shared kernel)

- `setup_logging()` — one log format for API and worker (stdout, so `docker logs` keeps
  working), level from `LOG_LEVEL` (default `INFO`).
- `init_error_reporting(service)` — if `SENTRY_DSN` is set, starts `sentry-sdk` (works with
  sentry.io or a self-hosted Sentry/GlitchTip). `SENTRY_ENVIRONMENT` (default `production`),
  release = `IMAGE_TAG`. No tracing, no PII (`send_default_pii=False`). The Starlette/FastAPI
  auto-integrations are disabled and logging records only become breadcrumbs, so every
  error is sent exactly once, by `report_exception`. Without a DSN it is a no-op.
- `report_exception(error, *, where, **context)` — logs the traceback at ERROR with the
  context, sends it to Sentry with the context as tags, and returns a short reference id.
  An exception with `expected_refusal = True` (finance's `PostingRefused`, a business
  refusal already recorded and alerted on its own) is logged at WARNING and not sent.

### API

A pure ASGI middleware (`ErrorReportingMiddleware`), installed inside CORS, catches any
exception a route lets escape (`HTTPException` is already turned into a response before it),
calls `report_exception` with method and path, and answers `500` with the usual shape:
`{"detail": {"code": "INTERNAL_ERROR", "message": "... (reference R)", "message_fr": ...}}`,
so the user sees a translated message and a reference to quote. If the response had
already started, it re-raises.

### Worker

- Consumer failures: `_process` calls `report_exception(where="consumer", event_type,
  event_id, consumer)` before rolling back and dead-lettering.
- Sweeps: their `except` blocks call `report_exception` instead of `print`.
- Outbox dispatcher: wrapped in a reconnect loop; a failure is reported and the thread
  reconnects after 10 s instead of dying.
- `consume_forever` exiting is reported before the process exits (Docker restarts it).

### Alerts (`worker/alerts.py`, thread `run_alert_monitor`)

Every `ALERT_CHECK_INTERVAL_SECONDS` (default 300) the worker reads:

- the dead-letter queue depth (passive `queue_declare` on `erp.events.dlq`);
- open posting failures per tenant (`PostingFailureService.open_counts_by_tenant()`).

`core.observability.GrowthWatch` (pure, unit-tested) decides when to alert: when a value
rises above the highest value already alerted for that key. When it falls, the baseline
follows it down, so the next rise alerts again. A restart starts from zero, so a non-empty
queue is announced once after each deploy — a reminder, not noise. Both values are also
Prometheus gauges (`erp_dead_letter_messages`, `erp_posting_failures_open{tenant}`) on the
worker's `:9101/metrics`, scraped by the compose Prometheus.

An alert is delivered by `send_alert(title, text, details)`: logged at WARNING, sent to
Sentry as a message when configured, and POSTed as JSON to `ALERT_WEBHOOK_URL` if set
(`{"title", "text", "content", "details"}`: `text` is what Slack/Mattermost show, `content`
what Discord shows; ntfy and others take the JSON as-is). It never raises.

### In-app notification of posting failures (finance)

`PostingFailureService.record` notifies every user of the tenant holding
`finance.view_ledger` (kind `finance.posting.refused`, en/fr title, link
`/finance/entries`) when the failure is new or reopened — not when an already open failure
is refused again (a retry that fails). This is the tenant-facing alert; the webhook is the
operator-facing one. The DLQ is operator-only: its messages span tenants.

## Not in scope

Alertmanager (Prometheus alert routing), email (WP-3.2 adds email sending; the webhook can
point at any relay until then), frontend error reporting.

## Configuration (all optional)

`SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `ALERT_WEBHOOK_URL`, `ALERT_CHECK_INTERVAL_SECONDS`,
`WORKER_METRICS_PORT` (default 9101, `0` disables), `LOG_LEVEL`.
