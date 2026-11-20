"""Error reporting and alerts (core/observability.py). No database."""
from __future__ import annotations

import http.server
import json
import logging
import threading

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from core import observability
from core.events import consumers
from core.observability import ErrorReportingMiddleware, GrowthWatch, report_exception, send_alert


def test_growth_watch_alerts_on_a_rise_only_and_follows_a_fall_down():
    watch = GrowthWatch()
    assert [watch.check("q", v) for v in (0, 3, 3, 5, 2, 2, 4, 0, 1)] == [
        False, True, False, True, False, False, True, False, True,
    ]
    assert watch.check("other", 1) is True  # keys are independent


def test_report_exception_logs_the_traceback_and_context(caplog):
    caplog.set_level(logging.WARNING, logger="erp")
    try:
        raise ValueError("boom")
    except ValueError as error:
        reference = report_exception(error, where="test", event_id="E1", skipped=None)
    record = caplog.records[-1]
    assert record.levelno == logging.ERROR and record.exc_info is not None
    assert f"reference={reference}" in record.getMessage() and "event_id=E1" in record.getMessage()
    assert "skipped" not in record.getMessage()


def test_an_expected_refusal_is_a_warning_and_is_not_sent(caplog, monkeypatch):
    class Refused(Exception):
        expected_refusal = True

    sent = []
    monkeypatch.setattr(observability, "_sentry_enabled", True)
    monkeypatch.setattr("sentry_sdk.capture_exception", lambda error: sent.append(error))
    caplog.set_level(logging.WARNING, logger="erp")
    report_exception(Refused("PERIOD_CLOSED"), where="consumer")
    assert caplog.records[-1].levelno == logging.WARNING and caplog.records[-1].exc_info is None
    assert sent == []


def test_an_unexpected_error_is_sent_to_sentry_exactly_once(monkeypatch):
    sent = []
    monkeypatch.setattr(observability, "_sentry_enabled", True)
    monkeypatch.setattr("sentry_sdk.capture_exception", lambda error: sent.append(error))
    error = RuntimeError("x")
    report_exception(error, where="test")
    assert sent == [error]


def test_without_a_dsn_error_reporting_stays_off(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert observability.init_error_reporting("test") is False


def test_with_a_dsn_sentry_starts_without_the_framework_auto_reporting(monkeypatch):
    import sentry_sdk
    from sentry_sdk.transport import Transport

    class NullTransport(Transport):  # the test client must send nothing anywhere
        def capture_envelope(self, envelope):
            pass

    real_init = sentry_sdk.init
    monkeypatch.setattr(sentry_sdk, "init", lambda *args, **kwargs: real_init(*args, transport=NullTransport, **kwargs))
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setattr(observability, "_sentry_enabled", False)
    try:
        assert observability.init_error_reporting("test") is True
        client = sentry_sdk.get_client()
        assert client.is_active() and client.options["send_default_pii"] is False
        assert "starlette" not in client.integrations and "fastapi" not in client.integrations
    finally:
        monkeypatch.delenv("SENTRY_DSN")  # init() falls back to the variable
        real_init()  # back to a client that sends nothing
        observability._sentry_enabled = False


@pytest.fixture
def webhook():
    received: list[dict] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/hook", received
    server.shutdown()


def test_send_alert_posts_json_to_the_webhook(monkeypatch, webhook):
    url, received = webhook
    monkeypatch.setenv("ALERT_WEBHOOK_URL", url)
    send_alert("Dead-letter queue growing", "3 event(s)", {"messages": 3})
    assert received == [{
        "title": "Dead-letter queue growing",
        "text": "Dead-letter queue growing\n3 event(s)",
        "content": "Dead-letter queue growing\n3 event(s)",
        "details": {"messages": 3},
    }]


def test_send_alert_never_raises_when_the_webhook_is_down(monkeypatch, caplog):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://127.0.0.1:9/unreachable")
    caplog.set_level(logging.ERROR, logger="erp")
    send_alert("t", "x")
    assert "Could not deliver alert" in caplog.records[-1].getMessage()


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ErrorReportingMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["http://front.test"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/crash")
    def crash():
        raise RuntimeError("database exploded")

    @app.get("/refuse")
    def refuse():
        raise HTTPException(status_code=409, detail={"code": "NOPE", "message": "no"})

    return app


def test_an_unhandled_route_error_is_a_readable_500_with_a_reference(caplog):
    caplog.set_level(logging.ERROR, logger="erp")
    response = TestClient(_app(), raise_server_exceptions=False).get("/crash", headers={"Origin": "http://front.test"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://front.test"
    detail = response.json()["detail"]
    assert detail["code"] == "INTERNAL_ERROR"
    assert detail["reference"] in detail["message"] and detail["reference"] in detail["message_fr"]
    assert "database exploded" not in json.dumps(detail)  # internals stay in the log
    logged = caplog.records[-1].getMessage()
    assert "path=/crash" in logged and "method=GET" in logged and detail["reference"] in logged


def test_http_exceptions_pass_through_untouched():
    response = TestClient(_app()).get("/refuse")
    assert response.status_code == 409 and response.json() == {"detail": {"code": "NOPE", "message": "no"}}


class _FakeConnection:
    def __init__(self):
        self.rolled_back = 0

    def execute(self, *args):
        return self

    def fetchone(self):
        return None

    def commit(self):
        pass

    def rollback(self):
        self.rolled_back += 1


def test_a_failing_consumer_is_reported_before_the_message_is_dead_lettered(monkeypatch, caplog):
    def broken(connection, envelope):
        raise KeyError("missing payload field")

    monkeypatch.setattr(consumers, "_registry", {"test.thing.happened": [("test.broken", broken)]})
    caplog.set_level(logging.ERROR, logger="erp")
    connection = _FakeConnection()
    assert consumers._process(connection, {"event_id": "E42", "event_type": "test.thing.happened"}) is False
    assert connection.rolled_back == 1
    logged = caplog.records[-1].getMessage()
    assert "consumer=test.broken" in logged and "event_id=E42" in logged and "event_type=test.thing.happened" in logged
