"""ClaudeReader: Claude's answer -> the OCR /read contract, and API failures -> the queue's
OcrUnavailable / OcrReadError. A fake client stands in for the API; no DB, no network."""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from modules.scan.api.claude_reader import CONFIDENT, UNCERTAIN, ClaudeReader, to_contract
from modules.scan.api.ocr_client import OcrReadError, OcrUnavailable
from modules.scan.domain.ocr_result import page_read_from_json

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32

FABRICATION_ANSWER = {
    "form_type": "fabrication",
    "rotation": 90,
    "header": [
        {"key": "date", "text": "Le07/09/2026", "uncertain": False, "box": [0.1, 0.05, 0.25, 0.08]},
        {"key": "team_hours", "text": "D 07 H à 14H00", "uncertain": False, "box": None},
        {"key": "line_pc", "text": "x", "uncertain": False, "box": None},
        {"key": "machiniste", "text": "not on this fiche", "uncertain": False, "box": None},
    ],
    "blocks": [
        {"key": "production", "rows": [
            {"cells": [
                {"key": "lot", "text": "D6249SNL", "uncertain": False, "box": None},
                {"key": "sem_tonnes", "text": "3,25", "uncertain": True, "box": [0.5, 0.2, 0.55, 0.22]},
            ]},
            {"cells": [{"key": "lot", "text": "  ", "uncertain": False, "box": None}]},
        ]},
        {"key": "packing", "rows": [{"cells": [{"key": "format", "text": "Ver", "uncertain": False, "box": None}]}]},
    ],
}


def test_the_answer_becomes_the_ocr_contract_the_domain_reads():
    result = to_contract(FABRICATION_ANSWER, None, "claude-opus-5")
    page = page_read_from_json("P1", result)

    assert page.form_type == "fabrication"
    assert page.rotation == 90
    assert page.head("date").text == "Le07/09/2026"
    assert page.head("date").box == (0.1, 0.05, 0.25, 0.08)
    assert "machiniste" not in page.header  # a conditionnement field, not on this fiche
    production = page.block("production")
    assert len(production.rows) == 1  # the blank line is dropped
    assert production.rows[0].cell("lot").confidence == CONFIDENT
    assert production.rows[0].cell("sem_tonnes").confidence == UNCERTAIN < page.accept_score
    assert page.block("packing") is None  # not a fabrication block
    assert page.blocks["stops"].found is False


def test_a_photo_that_is_no_fiche_is_unrecognized():
    result = to_contract({"form_type": None, "rotation": 0, "header": [], "blocks": []}, None, "m")
    assert result["form_type"] is None and result["blocks"] == []


def test_the_users_form_hint_wins_over_claudes_guess():
    answer = {**FABRICATION_ANSWER, "form_type": None}
    assert to_contract(answer, "fabrication", "m")["form_type"] == "fabrication"


def test_a_box_out_of_range_is_clamped_or_dropped():
    answer = {"form_type": "bobines", "rotation": 0, "header": [], "blocks": [{"key": "changes", "rows": [{"cells": [
        {"key": "machine", "text": "C1", "uncertain": False, "box": [-0.1, 0.2, 1.3, 0.3]},
        {"key": "date", "text": "07/09/26", "uncertain": False, "box": [0.5, 0.5, 0.4, 0.6]},
    ]}]}]}
    cells = to_contract(answer, None, "m")["blocks"][0]["rows"][0]["cells"]
    assert cells["machine"]["box"] == [0.0, 0.2, 1.0, 0.3]
    assert cells["date"]["box"] is None


class _FakeStream:
    def __init__(self, message=None, error=None):
        self._message, self._error = message, error

    def __enter__(self):
        if self._error:
            raise self._error
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


def _reader(message=None, error=None, calls=None):
    def stream(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return _FakeStream(message, error)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    return ClaudeReader("key", model="claude-opus-5", client=client)


def _message(text: str | None, stop_reason: str = "end_turn"):
    content = [SimpleNamespace(type="text", text=text)] if text is not None else []
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def _status_error(cls, status: int):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def test_read_sends_the_photo_and_returns_the_contract():
    calls = []
    result = _reader(_message(json.dumps(FABRICATION_ANSWER)), calls=calls).read(JPEG, "fabrication")

    assert result["form_type"] == "fabrication" and result["reader"] == "claude"
    image = calls[0]["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/jpeg"
    assert "fabrication" in calls[0]["messages"][0]["content"][1]["text"]


@pytest.mark.parametrize("error", [
    anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")),
    _status_error(anthropic.RateLimitError, 429),
    _status_error(anthropic.InternalServerError, 529),
    _status_error(anthropic.AuthenticationError, 401),
])
def test_an_outage_or_a_bad_key_leaves_the_page_queued(error):
    with pytest.raises(OcrUnavailable):
        _reader(error=error).read(JPEG, None)


def test_a_rejected_request_counts_as_a_failed_read():
    with pytest.raises(OcrReadError):
        _reader(error=_status_error(anthropic.BadRequestError, 400)).read(JPEG, None)


@pytest.mark.parametrize("message", [_message(None, "refusal"), _message("{", "max_tokens"), _message("not json")])
def test_an_unusable_answer_counts_as_a_failed_read(message):
    with pytest.raises(OcrReadError):
        _reader(message).read(JPEG, None)


def test_an_unknown_image_format_is_refused_before_any_call():
    with pytest.raises(OcrReadError):
        _reader(error=AssertionError("must not be called")).read(b"GIF89a....", None)
