"""Error reporting and operator alerts, shared by the API and the worker.

- `setup_logging()` gives both processes one stdout log format (`docker logs` reads it).
- `init_error_reporting()` starts Sentry when `SENTRY_DSN` is set (sentry.io, or a self-hosted
  Sentry/GlitchTip); without it, errors are only logged.
- `report_exception()` is the one place an unexpected error is logged and sent, so it is sent once.
- `send_alert()` tells the operator something needs attention: log, Sentry message, and a JSON
  POST to `ALERT_WEBHOOK_URL` (Slack, Mattermost, Discord, ntfy, ...). It never raises.
- `GrowthWatch` decides when a growing number (dead letters, refused postings) deserves an alert.
- `ErrorReportingMiddleware` turns an exception a route let escape into the usual error shape.

See docs/superpowers/specs/2026-11-20-error-tracking-alerts-design.md.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

from ulid import ULID

logger = logging.getLogger("erp")

_sentry_enabled = False


def setup_logging() -> None:
    """One format for every logger, at `LOG_LEVEL` (default INFO). Safe to call twice."""
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def init_error_reporting(service: str) -> bool:
    """Starts Sentry if `SENTRY_DSN` is set. Returns whether it is on."""
    global _sentry_enabled
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("SENTRY_DSN not set: errors are logged only")
        return False
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("IMAGE_TAG") or None,
        server_name=service,
        send_default_pii=False,
        traces_sample_rate=0.0,
        # report_exception is the only sender: logged errors become breadcrumbs, not events,
        # and the framework integrations would report a route's exception a second time.
        integrations=[LoggingIntegration(level=logging.INFO, event_level=None)],
        disabled_integrations=[StarletteIntegration(), FastApiIntegration()],
    )
    sentry_sdk.set_tag("service", service)
    _sentry_enabled = True
    logger.info("Error reporting to Sentry on (service %s)", service)
    return True


def _clean(context: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in context.items() if value is not None}


def report_exception(error: BaseException, *, where: str, **context: Any) -> str:
    """Logs `error` with its traceback and sends it to Sentry. Returns a reference id to show the user.

    An exception marked `expected_refusal = True` is a business refusal recorded elsewhere: it is
    logged at WARNING, without traceback, and not sent."""
    reference = str(ULID())[-10:]
    tags = _clean({"where": where, "reference": reference, **context})
    described = " ".join(f"{key}={value}" for key, value in tags.items())
    if getattr(error, "expected_refusal", False):
        logger.warning("Refused (%s): %s", described, error)
        return reference
    logger.error("Unexpected error (%s): %s", described, error, exc_info=(type(error), error, error.__traceback__))
    if _sentry_enabled:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            for key, value in tags.items():
                scope.set_tag(key, value)
            sentry_sdk.capture_exception(error)
    return reference


def send_alert(title: str, text: str, details: dict[str, Any] | None = None) -> None:
    """Tells the operator. Never raises: a broken alert channel must not stop the worker."""
    details = details or {}
    logger.warning("ALERT %s: %s %s", title, text, json.dumps(details, default=str))
    if _sentry_enabled:
        try:
            import sentry_sdk

            with sentry_sdk.new_scope() as scope:
                scope.set_context("alert", details)
                sentry_sdk.capture_message(f"{title}: {text}", level="warning")
        except Exception:  # noqa: BLE001 -- see docstring
            logger.exception("Could not send alert to Sentry")
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return
    message = f"{title}\n{text}"
    body = json.dumps({"title": title, "text": message, "content": message, "details": details}, default=str)
    request = urllib.request.Request(
        url, data=body.encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 -- operator-set URL
            response.read()
    except Exception as error:  # noqa: BLE001 -- see docstring
        logger.error("Could not deliver alert to ALERT_WEBHOOK_URL: %s", error)


class GrowthWatch:
    """Says when a watched number has grown past what was already announced.

    `check(key, value)` returns True when `value` is above the highest value announced for `key`
    (so 0 → 3 alerts, 3 → 3 does not, 3 → 5 does). When the number falls, the baseline follows it
    down, so a later rise alerts again. A new watch (worker restart) starts at 0."""

    def __init__(self) -> None:
        self._announced: dict[str, int] = {}

    def check(self, key: str, value: int) -> bool:
        announced = self._announced.get(key, 0)
        if value > announced:
            self._announced[key] = value
            return True
        self._announced[key] = value
        return False


INTERNAL_ERROR_MESSAGE = "Unexpected server error. It has been logged (reference {reference})."
INTERNAL_ERROR_MESSAGE_FR = "Erreur inattendue du serveur. Elle a été enregistrée (référence {reference})."


class ErrorReportingMiddleware:
    """Pure ASGI middleware: an exception a route lets escape is reported and answered with the
    usual `{"detail": {"code", "message", "message_fr"}}` 500. Install it inside CORS so the
    browser can read the answer. `HTTPException` never gets here: FastAPI answers it further in."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as error:
            reference = report_exception(error, where="api", method=scope.get("method"), path=scope.get("path"))
            if started:
                raise
            body = json.dumps(
                {
                    "detail": {
                        "code": "INTERNAL_ERROR",
                        "message": INTERNAL_ERROR_MESSAGE.format(reference=reference),
                        "message_fr": INTERNAL_ERROR_MESSAGE_FR.format(reference=reference),
                        "reference": reference,
                    }
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send({"type": "http.response.body", "body": body})
