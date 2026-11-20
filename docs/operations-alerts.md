# Error tracking and alerts

What tells you something went wrong on the server, and how to turn each piece on.
Design: `docs/superpowers/specs/2026-11-20-error-tracking-alerts-design.md`.

## What happens with nothing configured

- Every unexpected error in the API or the worker is logged with its traceback and a
  reference: `docker compose logs app worker | grep "Unexpected error"`.
- A user who hits one sees "Unexpected server error … (reference R)" in their language;
  grep the logs for `reference=R` to find it.
- A consumer that fails logs the consumer, event type and event id before the message goes
  to the dead-letter queue (`erp.events.dlq`).
- The worker checks the dead-letter queue and `finance.posting_failures` every 5 minutes and
  logs `ALERT …` at WARNING when either grows.
- Users with `finance.view_ledger` get an in-app notification when an automatic posting is
  refused (Finance > Entries shows the reason and a retry button).

## Turn on error tracking (Sentry)

1. Create a project in sentry.io, or in a self-hosted Sentry or GlitchTip (same protocol), and
   copy its DSN.
2. In the server `.env`: `SENTRY_DSN=https://…` and optionally `SENTRY_ENVIRONMENT=production`.
3. `docker compose up -d app worker`. The log line `Error reporting to Sentry on` confirms it.

Each error is sent once, tagged with `service` (api/worker), `where` (api, consumer,
outbox_dispatcher, dunning, …), the reference and the request path or event id. No request
bodies, cookies or user data are sent (`send_default_pii=False`) and there is no tracing.
Refused postings are business refusals, so they are logged as warnings and not sent.

## Turn on alert delivery (webhook)

Set `ALERT_WEBHOOK_URL` in the server `.env` and restart the worker. Each alert is a JSON POST:

```json
{"title": "Dead-letter queue growing", "text": "<title>\n<explanation>", "content": "<same>", "details": {"messages": 3}}
```

`text` is what Slack and Mattermost incoming webhooks show, `content` what Discord shows; an
ntfy topic URL takes the JSON as the message. With Sentry on, alerts also arrive there as
warnings, so Sentry's own email notifications work without a webhook.

An alert fires when a number rises above what was last announced (0 → 2 alerts, 2 → 2 does
not, 2 → 3 does; after it falls, the next rise alerts again). A worker restart starts from
zero, so a queue that is still not empty is announced again once after each deploy.
`ALERT_CHECK_INTERVAL_SECONDS` (default 300) sets the cadence.

## Dealing with what an alert reports

- **Dead-letter queue growing**: find the error in the worker log or Sentry
  (`where=consumer`). Messages can be inspected in the RabbitMQ management UI
  (`ssh -L 15672:localhost:15672 …`, queue `erp.events.dlq`). Fix the cause, then move them
  back (management UI "Move messages" to `erp.worker.consumers`, needs the shovel plugin, or
  re-publish them); consumers are idempotent on `event_id`.
- **Automatic postings refused**: Finance > Entries, failures list: fix the reason (closed
  period, missing account in the posting rules…) and press retry.

## Metrics

The worker serves `erp_dead_letter_messages` and `erp_posting_failures_open{tenant}` on
`:9101/metrics` (`WORKER_METRICS_PORT`, `0` turns it off); the compose Prometheus scrapes it
(job `erp-worker`) next to the API's `/metrics`, so Grafana can graph both.
