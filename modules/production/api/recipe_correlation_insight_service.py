"""A one-sentence, plain-language reading of the recipe-correlation figures.

Deliberately thin: this calls out to the Groq API rather than reading any
new data itself -- `list_recipe_correlation`'s rows are the only input. Kept
as its own module (not folded into `WorkOrderYieldService`) because it has a
different failure mode than the rest of that service: a missing API key, a
network error or an exhausted quota must all fall back to "no insight right
now", never a 500 that takes the whole dashboard card down with it.

Only aggregates cross the wire to Groq, never the raw rows: no OF
reference, no product or team name, no per-shift date. The user chose the
free API tier for this -- rounded plant-wide statistics carry a lot less than
a named OF's exact figures, and there is nothing here an insight needs that
the aggregate doesn't already say.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# Override via GROQ_MODEL if a different Llama size/version is ever needed.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 10

# Below this, min/max/avg over a handful of shifts is noise dressed up as a
# sentence -- the model would state it just as confidently either way. Lower
# than the scatter's 20-shift floor since a single aggregate sentence is less
# sensitive to a small N than a plotted trend is.
MIN_ROWS_FOR_INSIGHT = 10


class RecipeCorrelationInsightUnavailable(Exception):
    """No insight could be produced. Callers show "not available now", never an error banner."""


def summarize_recipe_correlation(rows: list[dict], *, locale: str) -> str:
    if len(rows) < MIN_ROWS_FOR_INSIGHT:
        raise RecipeCorrelationInsightUnavailable(
            f"only {len(rows)} row(s), need at least {MIN_ROWS_FOR_INSIGHT}"
        )

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RecipeCorrelationInsightUnavailable("GROQ_API_KEY is not configured")

    prompt = _build_prompt(_aggregate(rows), locale=locale)
    return _call_groq(api_key, prompt)


def _aggregate(rows: list[dict]) -> dict:
    yields = [row["yield_ratio"] * 100 for row in rows]
    waters = [row["water_percentage"] for row in rows if row["water_percentage"] is not None]
    flows = [row["semolina_flow_rate"] for row in rows if row["semolina_flow_rate"] is not None]
    below_target = sum(
        1
        for row in rows
        if row["water_percentage"] is not None
        and row["water_target_min"] is not None
        and row["water_percentage"] < row["water_target_min"]
    )
    above_target = sum(
        1
        for row in rows
        if row["water_percentage"] is not None
        and row["water_target_max"] is not None
        and row["water_percentage"] > row["water_target_max"]
    )
    dates = sorted(row["report_date"] for row in rows)
    return {
        "shift_count": len(rows),
        "date_from": dates[0],
        "date_to": dates[-1],
        "yield_min": round(min(yields), 1),
        "yield_max": round(max(yields), 1),
        "yield_avg": round(sum(yields) / len(yields), 1),
        "water_avg": round(sum(waters) / len(waters), 1) if waters else None,
        "water_below_target_count": below_target,
        "water_above_target_count": above_target,
        "flow_avg": round(sum(flows) / len(flows), 2) if flows else None,
    }


def _build_prompt(stats: dict, *, locale: str) -> str:
    language = "French" if locale == "fr" else "English"
    facts = [
        f"yield ranged {stats['yield_min']}-{stats['yield_max']}% (average {stats['yield_avg']}%)",
    ]
    if stats["water_avg"] is not None:
        facts.append(f"average water dosage {stats['water_avg']}%")
    if stats["water_below_target_count"] or stats["water_above_target_count"]:
        facts.append(
            f"{stats['water_below_target_count']} shift(s) dosed below their recipe's water range and "
            f"{stats['water_above_target_count']} above it"
        )
    if stats["flow_avg"] is not None:
        facts.append(f"average semolina flow rate {stats['flow_avg']} t/h")

    return (
        "You are summarizing plant-floor production statistics for a pasta factory's shift supervisor. "
        f"Write ONE short sentence (max 35 words), in {language}, plain and factual -- no ranking of recipes, "
        "no recommendation, no praise or blame, just what the numbers say. "
        f"Data, from {stats['shift_count']} validated shifts between {stats['date_from']} and {stats['date_to']}: "
        + "; ".join(facts)
        + "."
    )


def _call_groq(api_key: str, prompt: str) -> str:
    body = json.dumps(
        {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 200,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GROQ_API_URL,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RecipeCorrelationInsightUnavailable(f"Groq request failed: {exc}") from exc

    try:
        return payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RecipeCorrelationInsightUnavailable(f"unexpected Groq response shape: {payload}") from exc
