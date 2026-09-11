"""The production floor's "Assistance IA" chat: a Gemini conversation grounded in
this tenant's own production statistics via function-calling, never free-form.

The model never sees raw data up front. Each turn it chooses from a small set of
read-only, already-aggregated tools (see TOOL_DECLARATIONS) -- the same "only
rounded aggregates cross the wire" discipline as
recipe_correlation_insight_service.py, just decided per-question instead of
baked into one fixed prompt. Every tool enforces MIN_ROWS_FOR_TOOL_RESULT before
returning real numbers: tool-calling lets the model ask for an arbitrarily thin
slice ("team B, last Tuesday"), and a thin slice is not an aggregate any more --
it is one shift's exact figures wearing an aggregate's clothing. The system
instruction tells the model to widen its own search and say so when that
happens, rather than the backend silently guessing what a wider window should be.

Conversations are private per user (tenant_id AND user_id on every row) -- there
is no "team" or "shared" view of this data, by design; see the migration's own
comment. tool_calls on each assistant message is kept for audit (what real
figures backed this answer), mirroring core.audit_log for mutations.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.api.machine_performance_service import MachinePerformanceService
from modules.production.api.team_performance_service import TeamPerformanceService
from modules.production.api.work_order_yield_service import WorkOrderYieldService

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
REQUEST_TIMEOUT_SECONDS = 20

# Below this many underlying shifts/reports, a "statistic" is just those few
# rows' exact figures -- same reasoning and same floor as
# recipe_correlation_insight_service.MIN_ROWS_FOR_INSIGHT, generalized to every
# tool instead of one fixed card.
MIN_ROWS_FOR_TOOL_RESULT = 10

# A chat invites rapid-fire messages in a way the single-button insight card
# never did; each user turn can itself cost several Gemini calls (one per
# tool-call round trip), so the cap is on turns, not raw API calls. Rolling
# 24h window rather than a calendar day -- simpler, no timezone-of-day edge case.
MAX_MESSAGES_PER_USER_PER_DAY = 30

# Hard ceiling on tool-call round trips within one turn, so a model stuck in a
# call-tool-then-ask-again loop fails fast (as IaAssistantUnavailable) instead
# of silently burning the day's quota on a single question.
MAX_TOOL_ITERATIONS = 5


class IaAssistantUnavailable(Exception):
    """No answer could be produced. Callers show "assistant unavailable", never a 500."""


class IaAssistantRateLimited(Exception):
    """This user has hit MAX_MESSAGES_PER_USER_PER_DAY. Callers show a 429."""


class IaAssistantNotFound(Exception):
    """No conversation with this id owned by this user in this tenant."""


SYSTEM_INSTRUCTION_TEMPLATE = (
    "You are a plant-floor production assistant inside a pasta factory's ERP system. "
    "You answer questions about production statistics -- yield (rendement), water "
    "dosage, team performance, machine performance and downtime -- using ONLY the "
    "tools provided; never invent a number. Yield above 100% is expected and normal "
    "here (dosed water adds mass but is not in the yield denominator), so do not "
    "flag a high yield as an anomaly on its own.\n"
    "If a tool reports it does not have enough matching data for the requested "
    "filters, do not give up silently: retry the same tool with a wider date range "
    "or fewer filters, and when you do, tell the user plainly that you widened the "
    "search and why. When asked how to improve a metric, phrase your answer as "
    "hypotheses worth checking on the floor (e.g. \"worth checking scale calibration "
    "on...\"), never as confident causal claims, and never single out a named team or "
    "person for blame -- correlational plant data cannot support that. Keep answers "
    "short and concrete, written for a shift supervisor, not a report. "
    "Respond in {language}."
)

TOOL_DECLARATIONS = [
    {
        "name": "get_yield_and_water_stats",
        "description": (
            "Yield (rendement) and water-dosage compliance across validated shifts: "
            "min/max/average yield percentage, average water dosage, and how many "
            "shifts dosed outside their recipe's water range. Use for any question "
            "about yield, rendement, water dosage or semolina flow rate."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date_from": {"type": "STRING", "description": "ISO date (YYYY-MM-DD), inclusive lower bound. Omit for no lower bound."},
                "date_to": {"type": "STRING", "description": "ISO date (YYYY-MM-DD), inclusive upper bound. Omit for no upper bound."},
                "team": {"type": "STRING", "description": "Exact team name to filter to. Omit for all teams."},
            },
        },
    },
    {
        "name": "get_team_performance",
        "description": (
            "Material input, output, yield, production/downtime minutes and net semoule "
            "waste, totalled per team (or across all teams). Use for questions comparing "
            "or evaluating team output, waste or downtime."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date_from": {"type": "STRING", "description": "ISO date (YYYY-MM-DD), inclusive lower bound. Omit for no lower bound."},
                "date_to": {"type": "STRING", "description": "ISO date (YYYY-MM-DD), inclusive upper bound. Omit for no upper bound."},
                "team": {"type": "STRING", "description": "Exact team name to filter to. Omit for all teams."},
            },
        },
    },
    {
        "name": "get_machine_performance",
        "description": (
            "Output totals and downtime share, per machine, over a period. Use for "
            "questions about which machine ran well or lost time."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date_from": {"type": "STRING", "description": "ISO date (YYYY-MM-DD), inclusive lower bound. Omit for no lower bound."},
                "date_to": {"type": "STRING", "description": "ISO date (YYYY-MM-DD), inclusive upper bound. Omit for no upper bound."},
            },
        },
    },
    {
        "name": "get_downtime_reasons",
        "description": "Minutes of stoppage per stated reason, across validated shifts. Use for questions about why the line stopped.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date_from": {"type": "STRING", "description": "ISO date (YYYY-MM-DD), inclusive lower bound. Omit for no lower bound."},
                "date_to": {"type": "STRING", "description": "ISO date (YYYY-MM-DD), inclusive upper bound. Omit for no upper bound."},
            },
        },
    },
]


def _in_range(value: str | None, date_from: str | None, date_to: str | None) -> bool:
    if value is None:
        return False
    if date_from is not None and value < date_from:
        return False
    if date_to is not None and value > date_to:
        return False
    return True


def _too_few(count: int) -> dict | None:
    if count >= MIN_ROWS_FOR_TOOL_RESULT:
        return None
    return {
        "available": False,
        "matching_count": count,
        "reason": (
            f"only {count} matching shift(s)/report(s), fewer than the "
            f"{MIN_ROWS_FOR_TOOL_RESULT} needed for a meaningful statistic -- "
            "try again with a wider date range or without the team filter"
        ),
    }


def _tool_get_yield_and_water_stats(connection: psycopg.Connection, tenant_id: str, args: dict) -> dict:
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    team = args.get("team")

    rows = WorkOrderYieldService(connection).list_recipe_correlation(tenant_id=tenant_id)
    rows = [r for r in rows if _in_range(r.get("report_date"), date_from, date_to) and (team is None or r.get("team") == team)]

    too_few = _too_few(len(rows))
    if too_few is not None:
        return too_few

    yields = [r["yield_ratio"] * 100 for r in rows]
    waters = [r["water_percentage"] for r in rows if r["water_percentage"] is not None]
    flows = [r["semolina_flow_rate"] for r in rows if r["semolina_flow_rate"] is not None]
    below_target = sum(
        1 for r in rows
        if r["water_percentage"] is not None and r["water_target_min"] is not None and r["water_percentage"] < r["water_target_min"]
    )
    above_target = sum(
        1 for r in rows
        if r["water_percentage"] is not None and r["water_target_max"] is not None and r["water_percentage"] > r["water_target_max"]
    )
    dates = sorted(r["report_date"] for r in rows if r.get("report_date"))
    return {
        "available": True,
        "shift_count": len(rows),
        "date_from": dates[0] if dates else None,
        "date_to": dates[-1] if dates else None,
        "yield_avg_pct": round(sum(yields) / len(yields), 1),
        "yield_min_pct": round(min(yields), 1),
        "yield_max_pct": round(max(yields), 1),
        "water_avg_pct": round(sum(waters) / len(waters), 1) if waters else None,
        "water_below_target_count": below_target,
        "water_above_target_count": above_target,
        "flow_avg_t_per_h": round(sum(flows) / len(flows), 2) if flows else None,
    }


def _tool_get_team_performance(connection: psycopg.Connection, tenant_id: str, args: dict) -> dict:
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    team = args.get("team")

    rows = TeamPerformanceService(connection).list_team_performance(
        tenant_id=tenant_id, grain="week", date_from=date_from, date_to=date_to
    )
    if team is not None:
        rows = [r for r in rows if r.get("team") == team]

    too_few = _too_few(sum(r["report_count"] for r in rows))
    if too_few is not None:
        return too_few

    material_in = sum(r["material_input_quantity"] for r in rows)
    produced = sum(r["produced_quantity"] for r in rows)
    production_minutes = sum(r["production_minutes"] for r in rows)
    downtime_minutes = sum(r["downtime_minutes"] for r in rows)
    busy_minutes = production_minutes + downtime_minutes
    return {
        "available": True,
        "report_count": sum(r["report_count"] for r in rows),
        "teams_included": sorted({r["team"] for r in rows if r.get("team")}),
        "material_input_total": round(material_in, 1),
        "produced_total": round(produced, 1),
        "yield_pct": round(produced / material_in * 100, 1) if material_in else None,
        "production_minutes_total": production_minutes,
        "downtime_minutes_total": downtime_minutes,
        "downtime_share_pct": round(downtime_minutes / busy_minutes * 100, 1) if busy_minutes else None,
        "net_semoule_waste_total_kg": round(sum(r["net_semoule_waste"] for r in rows), 1),
    }


def _tool_get_machine_performance(connection: psycopg.Connection, tenant_id: str, args: dict) -> dict:
    date_from = args.get("date_from")
    date_to = args.get("date_to")

    rows = MachinePerformanceService(connection).list_machine_performance(
        tenant_id=tenant_id, grain="week", date_from=date_from, date_to=date_to
    )
    too_few = _too_few(sum(r["report_count"] for r in rows))
    if too_few is not None:
        return too_few

    # Production only stores the opaque equipment_id -- resolved here (never in
    # front of the model as a raw id) the same way the /machines endpoint does.
    equipment = EquipmentService(connection).list_equipment(tenant_id=tenant_id)
    name_by_id = {e.id: (e.name or e.code) for e in equipment}

    by_machine: dict[str, dict] = {}
    for r in rows:
        name = name_by_id.get(r["equipment_id"], "unidentified machine")
        bucket = by_machine.setdefault(
            name, {"report_count": 0, "produced_total": 0.0, "production_minutes": 0, "downtime_minutes": 0}
        )
        bucket["report_count"] += r["report_count"]
        bucket["produced_total"] += r["produced_quantity"]
        bucket["production_minutes"] += r["production_minutes"]
        bucket["downtime_minutes"] += r["downtime_minutes"]

    return {
        "available": True,
        "report_count": sum(r["report_count"] for r in rows),
        "per_machine": [
            {
                "machine": name,
                "report_count": b["report_count"],
                "produced_total": round(b["produced_total"], 1),
                "downtime_share_pct": (
                    round(b["downtime_minutes"] / (b["production_minutes"] + b["downtime_minutes"]) * 100, 1)
                    if (b["production_minutes"] + b["downtime_minutes"])
                    else None
                ),
            }
            for name, b in by_machine.items()
        ],
    }


def _tool_get_downtime_reasons(connection: psycopg.Connection, tenant_id: str, args: dict) -> dict:
    date_from = args.get("date_from")
    date_to = args.get("date_to")

    rows = TeamPerformanceService(connection).list_downtime_reasons(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
    too_few = _too_few(sum(r["report_count"] for r in rows))
    if too_few is not None:
        return too_few

    return {"available": True, "report_count": sum(r["report_count"] for r in rows), "by_reason": rows}


_TOOL_HANDLERS = {
    "get_yield_and_water_stats": _tool_get_yield_and_water_stats,
    "get_team_performance": _tool_get_team_performance,
    "get_machine_performance": _tool_get_machine_performance,
    "get_downtime_reasons": _tool_get_downtime_reasons,
}


def _call_gemini(api_key: str, contents: list[dict], *, language: str) -> dict:
    url = GEMINI_API_URL_TEMPLATE.format(model=GEMINI_MODEL)
    body = json.dumps(
        {
            "contents": contents,
            "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION_TEMPLATE.format(language=language)}]},
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{url}?key={api_key}", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise IaAssistantUnavailable(f"Gemini request failed: {exc}") from exc


def _run_turn(
    connection: psycopg.Connection, *, tenant_id: str, api_key: str, history: list[dict], user_text: str, language: str
) -> tuple[str, list[dict]]:
    contents = [*history, {"role": "user", "parts": [{"text": user_text}]}]
    tool_trace: list[dict] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        payload = _call_gemini(api_key, contents, language=language)
        try:
            parts = payload["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise IaAssistantUnavailable(f"unexpected Gemini response shape: {payload}") from exc

        function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not function_calls:
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                raise IaAssistantUnavailable(f"empty response: {payload}")
            return text, tool_trace

        contents.append({"role": "model", "parts": parts})
        response_parts = []
        for call in function_calls:
            name = call.get("name")
            args = call.get("args") or {}
            handler = _TOOL_HANDLERS.get(name)
            result = handler(connection, tenant_id, args) if handler is not None else {"available": False, "reason": f"unknown tool {name}"}
            tool_trace.append({"name": name, "args": args, "result": result})
            response_parts.append({"functionResponse": {"name": name, "response": result}})
        contents.append({"role": "function", "parts": response_parts})

    raise IaAssistantUnavailable("could not settle on an answer within the tool-call budget")


def _load_history_for_gemini(connection: psycopg.Connection, *, tenant_id: str, conversation_id: str) -> list[dict]:
    """Only final user/assistant turns are replayed -- not each turn's own tool
    calls, which the model re-derives fresh each time it needs them. Keeps stored
    history compact and never replays a tool-call transcript against a system
    instruction or tool set that may since have changed."""
    rows = connection.execute(
        """
        SELECT role, content FROM production.ia_assistant_messages
        WHERE tenant_id = %s AND conversation_id = %s
        ORDER BY created_at
        """,
        (tenant_id, conversation_id),
    ).fetchall()
    return [{"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]} for role, content in rows]


def _require_owned_conversation(connection: psycopg.Connection, *, tenant_id: str, user_id: str, conversation_id: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM production.ia_assistant_conversations WHERE id = %s AND tenant_id = %s AND user_id = %s",
        (conversation_id, tenant_id, user_id),
    ).fetchone()
    if row is None:
        raise IaAssistantNotFound(conversation_id)


def _count_recent_user_messages(connection: psycopg.Connection, *, tenant_id: str, user_id: str) -> int:
    row = connection.execute(
        """
        SELECT count(*)
        FROM production.ia_assistant_messages m
        JOIN production.ia_assistant_conversations c ON c.id = m.conversation_id AND c.tenant_id = m.tenant_id
        WHERE c.tenant_id = %s AND c.user_id = %s AND m.role = 'user' AND m.created_at >= NOW() - INTERVAL '1 day'
        """,
        (tenant_id, user_id),
    ).fetchone()
    return int(row[0])


def _insert_message(
    connection: psycopg.Connection, *, tenant_id: str, conversation_id: str, role: str, content: str, tool_calls: list[dict] | None
) -> str:
    message_id = str(ULID())
    connection.execute(
        """
        INSERT INTO production.ia_assistant_messages (id, tenant_id, conversation_id, role, content, tool_calls)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (message_id, tenant_id, conversation_id, role, content, Jsonb(tool_calls) if tool_calls is not None else None),
    )
    return message_id


def _touch_conversation(connection: psycopg.Connection, *, conversation_id: str, first_user_text: str) -> None:
    connection.execute(
        """
        UPDATE production.ia_assistant_conversations
        SET updated_at = NOW(), title = COALESCE(title, %s)
        WHERE id = %s
        """,
        (first_user_text[:60], conversation_id),
    )


def list_conversations(connection: psycopg.Connection, *, tenant_id: str, user_id: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT id, title, created_at, updated_at
        FROM production.ia_assistant_conversations
        WHERE tenant_id = %s AND user_id = %s
        ORDER BY updated_at DESC
        """,
        (tenant_id, user_id),
    ).fetchall()
    return [
        {"id": cid, "title": title, "created_at": created_at.isoformat(), "updated_at": updated_at.isoformat()}
        for cid, title, created_at, updated_at in rows
    ]


def create_conversation(connection: psycopg.Connection, *, tenant_id: str, user_id: str) -> dict:
    conversation_id = str(ULID())
    connection.execute(
        "INSERT INTO production.ia_assistant_conversations (id, tenant_id, user_id) VALUES (%s, %s, %s)",
        (conversation_id, tenant_id, user_id),
    )
    cid, title, created_at, updated_at = connection.execute(
        "SELECT id, title, created_at, updated_at FROM production.ia_assistant_conversations WHERE id = %s",
        (conversation_id,),
    ).fetchone()
    return {"id": cid, "title": title, "created_at": created_at.isoformat(), "updated_at": updated_at.isoformat()}


def delete_conversation(connection: psycopg.Connection, *, tenant_id: str, user_id: str, conversation_id: str) -> None:
    result = connection.execute(
        "DELETE FROM production.ia_assistant_conversations WHERE id = %s AND tenant_id = %s AND user_id = %s",
        (conversation_id, tenant_id, user_id),
    )
    if result.rowcount == 0:
        raise IaAssistantNotFound(conversation_id)


def list_messages(connection: psycopg.Connection, *, tenant_id: str, user_id: str, conversation_id: str) -> list[dict]:
    _require_owned_conversation(connection, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id)
    rows = connection.execute(
        """
        SELECT id, role, content, created_at FROM production.ia_assistant_messages
        WHERE tenant_id = %s AND conversation_id = %s
        ORDER BY created_at
        """,
        (tenant_id, conversation_id),
    ).fetchall()
    return [
        {"id": mid, "role": role, "content": content, "created_at": created_at.isoformat()}
        for mid, role, content, created_at in rows
    ]


def send_message(
    connection: psycopg.Connection, *, tenant_id: str, user_id: str, conversation_id: str, user_text: str, locale: str
) -> dict:
    """Runs the tool-calling loop and, only once a real answer exists, persists the
    user/assistant pair together -- a failed attempt leaves no half-sent message
    behind for a retry to pile on top of."""
    _require_owned_conversation(connection, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id)

    if _count_recent_user_messages(connection, tenant_id=tenant_id, user_id=user_id) >= MAX_MESSAGES_PER_USER_PER_DAY:
        raise IaAssistantRateLimited(f"{MAX_MESSAGES_PER_USER_PER_DAY} messages/day reached for this user")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise IaAssistantUnavailable("GEMINI_API_KEY is not configured")

    history = _load_history_for_gemini(connection, tenant_id=tenant_id, conversation_id=conversation_id)
    language = "French" if locale == "fr" else "English"
    answer_text, tool_trace = _run_turn(
        connection, tenant_id=tenant_id, api_key=api_key, history=history, user_text=user_text, language=language
    )

    _insert_message(connection, tenant_id=tenant_id, conversation_id=conversation_id, role="user", content=user_text, tool_calls=None)
    assistant_message_id = _insert_message(
        connection, tenant_id=tenant_id, conversation_id=conversation_id, role="assistant", content=answer_text, tool_calls=tool_trace or None
    )
    _touch_conversation(connection, conversation_id=conversation_id, first_user_text=user_text)

    return {"id": assistant_message_id, "role": "assistant", "content": answer_text, "tool_calls": tool_trace}
