"""Tests for the production IA assistant.

Pure helpers and the Groq tool-calling loop are pinned with no database, faking
`urllib.request.urlopen` the same way test_recipe_correlation_insight_service.py
does -- a live Groq call has no place in a suite that must stay green offline.
Conversation persistence and per-user isolation (the property this feature is
built around) are pinned against a real database via the shared `db` fixture,
since that is exactly the kind of SQL-correctness question a mock would rubber-
stamp.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from ulid import ULID

from modules.production.api import ia_assistant_service as svc

TENANT = "integration-test-ia-assistant"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_in_range_rejects_missing_value():
    assert svc._in_range(None, None, None) is False


def test_in_range_respects_both_bounds():
    assert svc._in_range("2026-06-15", "2026-06-01", "2026-06-30") is True
    assert svc._in_range("2026-05-31", "2026-06-01", "2026-06-30") is False
    assert svc._in_range("2026-07-01", "2026-06-01", "2026-06-30") is False


def test_too_few_below_floor():
    result = svc._too_few(svc.MIN_ROWS_FOR_TOOL_RESULT - 1)
    assert result == {
        "available": False,
        "matching_count": svc.MIN_ROWS_FOR_TOOL_RESULT - 1,
        "reason": (
            f"only {svc.MIN_ROWS_FOR_TOOL_RESULT - 1} matching shift(s)/report(s), fewer than the "
            f"{svc.MIN_ROWS_FOR_TOOL_RESULT} needed for a meaningful statistic -- "
            "try again with a wider date range or without the team filter"
        ),
    }


def test_too_few_at_or_above_floor_is_none():
    assert svc._too_few(svc.MIN_ROWS_FOR_TOOL_RESULT) is None


# ---------------------------------------------------------------------------
# Tool handlers -- underlying services monkeypatched, no database needed
# ---------------------------------------------------------------------------

def _yield_row(report_date, *, team="A", water=30.0, target_min=28.0, target_max=32.0, flow=4.5, yield_ratio=1.0):
    return {
        "report_date": report_date,
        "team": team,
        "water_percentage": water,
        "water_target_min": target_min,
        "water_target_max": target_max,
        "semolina_flow_rate": flow,
        "yield_ratio": yield_ratio,
    }


def test_yield_tool_refuses_below_floor(monkeypatch):
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.WorkOrderYieldService.list_recipe_correlation",
        lambda self, *, tenant_id: [_yield_row("2026-09-01")],
    )
    result = svc._tool_get_yield_and_water_stats(None, TENANT, {})
    assert result["available"] is False
    assert result["matching_count"] == 1


def test_yield_tool_aggregates_and_filters_by_team_and_date(monkeypatch):
    rows = [_yield_row(f"2026-09-{d:02d}", team="A", water=30.0 + d, yield_ratio=1.0 + d / 100) for d in range(1, 11)]
    rows += [_yield_row("2026-09-05", team="B", water=50.0, yield_ratio=2.0)]
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.WorkOrderYieldService.list_recipe_correlation",
        lambda self, *, tenant_id: rows,
    )
    result = svc._tool_get_yield_and_water_stats(None, TENANT, {"team": "A"})
    assert result["available"] is True
    assert result["shift_count"] == 10
    assert result["date_from"] == "2026-09-01"
    assert result["date_to"] == "2026-09-10"
    # Team B's outlier (water=50, yield=200%) must not leak into team A's stats.
    assert result["water_avg_pct"] < 40
    assert result["yield_max_pct"] < 150


def test_downtime_tool_refuses_below_floor(monkeypatch):
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.TeamPerformanceService.list_downtime_reasons",
        lambda self, *, tenant_id, date_from, date_to: [{"reason": "panne", "minutes": 30, "report_count": 2}],
    )
    result = svc._tool_get_downtime_reasons(None, TENANT, {})
    assert result["available"] is False


def test_downtime_tool_returns_breakdown_above_floor(monkeypatch):
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.TeamPerformanceService.list_downtime_reasons",
        lambda self, *, tenant_id, date_from, date_to: [
            {"reason": "panne", "minutes": 120, "report_count": 6},
            {"reason": "changement de format", "minutes": 60, "report_count": 5},
        ],
    )
    result = svc._tool_get_downtime_reasons(None, TENANT, {})
    assert result == {
        "available": True,
        "report_count": 11,
        "by_reason": [
            {"reason": "panne", "minutes": 120, "report_count": 6},
            {"reason": "changement de format", "minutes": 60, "report_count": 5},
        ],
    }


def _fake_classification(product_id):
    return SimpleNamespace(product_id=product_id, category="finished_good")


def _fake_product(product_id, name):
    return SimpleNamespace(id=product_id, name=name)


def _fake_stock_item(product_id, *, on_hand=0.0, reserved=0.0, in_production=0.0, location_id="wh-1"):
    return SimpleNamespace(
        location_id=location_id, product_id=product_id, quantity_on_hand=on_hand, quantity_reserved=reserved, quantity_in_production=in_production
    )


def test_finished_goods_stock_tool_refuses_when_nothing_classified(monkeypatch):
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.ProductClassificationService.list_classifications",
        lambda self, tenant_id, category=None: [],
    )
    result = svc._tool_get_finished_goods_stock(None, TENANT, {})
    assert result == {"available": False, "reason": "no product is classified as a finished good yet"}


def test_finished_goods_stock_tool_sums_across_locations_and_ignores_other_categories(monkeypatch):
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.ProductClassificationService.list_classifications",
        lambda self, tenant_id, category=None: [_fake_classification("prod-spaghetti")],
    )
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.CoreService.list_products",
        lambda self, tenant_id: [_fake_product("prod-spaghetti", "Spaghetti 500g"), _fake_product("prod-semoule", "Semoule")],
    )
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.CoreService.get_product_uom",
        lambda self, tenant_id, product_id: SimpleNamespace(symbol=None, code="pce"),
    )
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.StockService.list_stock_items",
        lambda self, tenant_id: [
            _fake_stock_item("prod-spaghetti", on_hand=100.0, reserved=20.0, location_id="wh-1"),
            _fake_stock_item("prod-spaghetti", on_hand=50.0, reserved=0.0, location_id="wh-2"),
            _fake_stock_item("prod-semoule", on_hand=9999.0),  # raw material, must not leak in
        ],
    )
    result = svc._tool_get_finished_goods_stock(None, TENANT, {})
    assert result == {
        "available": True,
        "product_count": 1,
        "by_product": [
            {
                "product": "Spaghetti 500g",
                "quantity_on_hand": 150.0,
                "quantity_reserved": 20.0,
                "quantity_available": 130.0,
                "quantity_in_production": 0.0,
                "unit": "pce",
            }
        ],
    }


def test_finished_goods_stock_tool_filters_by_product_name(monkeypatch):
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.ProductClassificationService.list_classifications",
        lambda self, tenant_id, category=None: [_fake_classification("prod-a"), _fake_classification("prod-b")],
    )
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.CoreService.list_products",
        lambda self, tenant_id: [_fake_product("prod-a", "Spaghetti 500g"), _fake_product("prod-b", "Penne 500g")],
    )
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.CoreService.get_product_uom",
        lambda self, tenant_id, product_id: SimpleNamespace(symbol="pce", code="pce"),
    )
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.StockService.list_stock_items",
        lambda self, tenant_id: [_fake_stock_item("prod-a", on_hand=10.0), _fake_stock_item("prod-b", on_hand=20.0)],
    )
    result = svc._tool_get_finished_goods_stock(None, TENANT, {"product_name": "penne"})
    assert result["available"] is True
    assert [p["product"] for p in result["by_product"]] == ["Penne 500g"]


def test_unknown_tool_name_reported_gracefully():
    handler = svc._TOOL_HANDLERS.get("not_a_real_tool")
    assert handler is None


# ---------------------------------------------------------------------------
# Groq tool-calling loop -- urlopen faked, tool handlers faked
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_run_turn_executes_a_tool_call_then_returns_final_text(monkeypatch):
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(json.loads(request.data))
        if len(calls) == 1:
            return _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_downtime_reasons",
                                            "arguments": json.dumps({"date_from": "2026-09-01"}),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )
        return _FakeResponse(
            {"choices": [{"message": {"role": "assistant", "content": "Downtime was mostly changeovers."}}]}
        )

    monkeypatch.setattr("modules.production.api.ia_assistant_service.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service._TOOL_HANDLERS",
        {"get_downtime_reasons": lambda connection, tenant_id, args: {"available": True, "report_count": 12, "by_reason": []}},
    )

    text, trace = svc._run_turn(
        None, tenant_id=TENANT, history=[], user_text="Why did the line stop?", language="English"
    )
    assert text == "Downtime was mostly changeovers."
    assert len(calls) == 2
    assert trace == [{"name": "get_downtime_reasons", "args": {"date_from": "2026-09-01"}, "result": {"available": True, "report_count": 12, "by_reason": []}}]


def test_run_turn_raises_when_tool_budget_exhausted(monkeypatch):
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    def fake_urlopen(request, timeout=None):
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "get_downtime_reasons", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("modules.production.api.ia_assistant_service.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service._TOOL_HANDLERS",
        {"get_downtime_reasons": lambda connection, tenant_id, args: {"available": False, "reason": "still not enough"}},
    )

    with pytest.raises(svc.IaAssistantUnavailable):
        svc._run_turn(None, tenant_id=TENANT, history=[], user_text="Why?", language="English")


def test_run_turn_raises_on_empty_final_text(monkeypatch):
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.urllib.request.urlopen",
        lambda request, timeout=None: _FakeResponse({"choices": [{"message": {"role": "assistant", "content": "  "}}]}),
    )
    with pytest.raises(svc.IaAssistantUnavailable):
        svc._run_turn(None, tenant_id=TENANT, history=[], user_text="Hi", language="English")


# ---------------------------------------------------------------------------
# Conversation persistence and per-user isolation -- real database
# ---------------------------------------------------------------------------

def test_conversations_are_isolated_per_user(db):
    user_a, user_b = str(ULID()), str(ULID())
    conv_a = svc.create_conversation(db, tenant_id=TENANT, user_id=user_a)
    svc.create_conversation(db, tenant_id=TENANT, user_id=user_b)

    listing_a = svc.list_conversations(db, tenant_id=TENANT, user_id=user_a)
    assert [c["id"] for c in listing_a] == [conv_a["id"]]

    with pytest.raises(svc.IaAssistantNotFound):
        svc.list_messages(db, tenant_id=TENANT, user_id=user_b, conversation_id=conv_a["id"])

    with pytest.raises(svc.IaAssistantNotFound):
        svc.delete_conversation(db, tenant_id=TENANT, user_id=user_b, conversation_id=conv_a["id"])


def test_send_message_persists_pair_and_titles_conversation(db, monkeypatch):
    user_id = str(ULID())
    conversation = svc.create_conversation(db, tenant_id=TENANT, user_id=user_id)

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        "modules.production.api.ia_assistant_service.urllib.request.urlopen",
        lambda request, timeout=None: _FakeResponse(
            {"choices": [{"message": {"role": "assistant", "content": "Yield looked normal this week."}}]}
        ),
    )

    reply = svc.send_message(
        db, tenant_id=TENANT, user_id=user_id, conversation_id=conversation["id"],
        user_text="How was yield this week?", locale="en",
    )
    assert reply["content"] == "Yield looked normal this week."

    messages = svc.list_messages(db, tenant_id=TENANT, user_id=user_id, conversation_id=conversation["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "How was yield this week?"

    refreshed = svc.list_conversations(db, tenant_id=TENANT, user_id=user_id)
    assert refreshed[0]["title"] == "How was yield this week?"


def test_send_message_rejects_unowned_conversation(db):
    owner, other = str(ULID()), str(ULID())
    conversation = svc.create_conversation(db, tenant_id=TENANT, user_id=owner)
    with pytest.raises(svc.IaAssistantNotFound):
        svc.send_message(db, tenant_id=TENANT, user_id=other, conversation_id=conversation["id"], user_text="Hi", locale="en")


def test_send_message_rate_limited_never_reaches_network(db, monkeypatch):
    user_id = str(ULID())
    conversation = svc.create_conversation(db, tenant_id=TENANT, user_id=user_id)
    for _ in range(svc.MAX_MESSAGES_PER_USER_PER_DAY):
        svc._insert_message(db, tenant_id=TENANT, conversation_id=conversation["id"], role="user", content="filler", tool_calls=None)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not reach the network once the daily cap is hit")

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr("modules.production.api.ia_assistant_service.urllib.request.urlopen", _fail_if_called)

    with pytest.raises(svc.IaAssistantRateLimited):
        svc.send_message(db, tenant_id=TENANT, user_id=user_id, conversation_id=conversation["id"], user_text="one more?", locale="en")
