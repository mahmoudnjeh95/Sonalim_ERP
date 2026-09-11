"""Unit tests for the recipe-correlation insight -- no database, no real network call.

`_aggregate`/`_build_prompt` are pinned as pure functions; `summarize_recipe_correlation`'s
error paths (no rows, no key, network failure, a malformed response) are pinned by
faking `urllib.request.urlopen`, since a live Gemini call has no place in a test suite
that must stay green offline.
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from modules.production.api.recipe_correlation_insight_service import (
    RecipeCorrelationInsightUnavailable,
    _aggregate,
    _build_prompt,
    summarize_recipe_correlation,
)

ROWS = [
    {
        "report_date": "2026-09-01",
        "water_percentage": 35.0,
        "semolina_flow_rate": 4.5,
        "yield_ratio": 1.05,
        "water_target_min": 28.0,
        "water_target_max": 32.0,
    },
    {
        "report_date": "2026-09-03",
        "water_percentage": 30.0,
        "semolina_flow_rate": 4.7,
        "yield_ratio": 0.98,
        "water_target_min": 28.0,
        "water_target_max": 32.0,
    },
]

# summarize_recipe_correlation refuses anything below MIN_ROWS_FOR_INSIGHT
# regardless of API key/network state, so its success/network-path tests need
# a fixture that clears that bar -- ROWS itself stays small for the pure
# _aggregate/_build_prompt tests, which don't care about the row-count floor.
MANY_ROWS = [{**ROWS[i % len(ROWS)], "report_date": f"2026-09-{i + 1:02d}"} for i in range(10)]


def test_aggregate_computes_expected_stats():
    stats = _aggregate(ROWS)
    assert stats["shift_count"] == 2
    assert stats["date_from"] == "2026-09-01"
    assert stats["date_to"] == "2026-09-03"
    assert stats["yield_min"] == 98.0
    assert stats["yield_max"] == 105.0
    assert stats["yield_avg"] == pytest.approx(101.5)
    assert stats["water_avg"] == pytest.approx(32.5)
    # Only the first row's 35% is outside the 28-32 range.
    assert stats["water_below_target_count"] == 0
    assert stats["water_above_target_count"] == 1


def test_aggregate_tolerates_rows_with_nothing_metered():
    stats = _aggregate([{**ROWS[0], "water_percentage": None, "semolina_flow_rate": None}])
    assert stats["water_avg"] is None
    assert stats["flow_avg"] is None
    assert stats["water_below_target_count"] == 0
    assert stats["water_above_target_count"] == 0


def test_build_prompt_uses_requested_language():
    stats = _aggregate(ROWS)
    assert "French" in _build_prompt(stats, locale="fr")
    assert "English" in _build_prompt(stats, locale="en")


def test_build_prompt_never_asks_for_ranking_or_recommendation():
    prompt = _build_prompt(_aggregate(ROWS), locale="en")
    assert "no ranking" in prompt
    assert "no recommendation" in prompt


def test_summarize_raises_when_no_rows():
    with pytest.raises(RecipeCorrelationInsightUnavailable):
        summarize_recipe_correlation([], locale="en")


def test_summarize_raises_when_too_few_rows(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not reach the network below the row-count floor")

    monkeypatch.setattr(
        "modules.production.api.recipe_correlation_insight_service.urllib.request.urlopen", _fail_if_called
    )
    with pytest.raises(RecipeCorrelationInsightUnavailable):
        summarize_recipe_correlation(ROWS, locale="en")


def test_summarize_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RecipeCorrelationInsightUnavailable):
        summarize_recipe_correlation(MANY_ROWS, locale="en")


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_summarize_returns_text_on_success(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "modules.production.api.recipe_correlation_insight_service.urllib.request.urlopen",
        lambda *a, **k: _FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": " Yield stayed near 100%. "}]}}]}
        ),
    )
    assert summarize_recipe_correlation(MANY_ROWS, locale="en") == "Yield stayed near 100%."


def test_summarize_raises_when_gemini_response_shape_is_unexpected(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "modules.production.api.recipe_correlation_insight_service.urllib.request.urlopen",
        lambda *a, **k: _FakeResponse({"candidates": []}),
    )
    with pytest.raises(RecipeCorrelationInsightUnavailable):
        summarize_recipe_correlation(MANY_ROWS, locale="en")


def test_summarize_raises_on_network_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def _raise(*args, **kwargs):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(
        "modules.production.api.recipe_correlation_insight_service.urllib.request.urlopen", _raise
    )
    with pytest.raises(RecipeCorrelationInsightUnavailable):
        summarize_recipe_correlation(MANY_ROWS, locale="en")
