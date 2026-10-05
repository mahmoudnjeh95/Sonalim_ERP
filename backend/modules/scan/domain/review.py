"""What applying a reviewed scan needs: section fingerprints (to refuse a stale review),
values by field path (to learn aliases and record outcomes), and payload cleaning."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Collection, Mapping

from modules.scan.domain.draft import path

# The paper fiches' order, energy excepted (it is on no fiche). Runs first: the other
# sections' derived figures read the runs.
APPLY_ORDER: tuple[str, ...] = (
    "runs", "waste_production", "stops", "silo", "staffing", "packing", "packet_checks", "waste_packing",
)


def fingerprint(payload: Mapping[str, Any] | None) -> str:
    text = json.dumps(payload or {}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def count_rows(payload: Mapping[str, Any] | None) -> int:
    total = 0
    for value in (payload or {}).values():
        if isinstance(value, list):
            total += len(value)
        elif isinstance(value, dict):
            total += 1
    return total


def final_values(sections: Mapping[str, Mapping[str, Any]], header: Mapping[str, Any]) -> dict[str, Any]:
    """Every value by its field path, for rows that came from the scan (they carry `_scan_ref`)."""
    out = {path("header", "-", "-", key): value for key, value in header.items()}
    for section, parts in sections.items():
        for part, value in parts.items():
            if isinstance(value, list):
                for row in value:
                    ref = row.get("_scan_ref")
                    if ref:
                        out.update({path(section, part, ref, k): v for k, v in row.items() if not k.startswith("_")})
            elif isinstance(value, dict):
                out.update({path(section, part, "-", k): v for k, v in value.items() if not k.startswith("_")})
    return out


def strip_private(payload: Mapping[str, Any]) -> dict:
    """The payload without the screen's own keys (`_scan_ref`, `_key`, ...), as save_section takes it."""
    def clean(value: Any) -> Any:
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if not k.startswith("_")}
        return value
    return clean(dict(payload))


def stale_sections(
    requested: Collection[str], current: Mapping[str, Mapping[str, Any]] | None, shown: Mapping[str, str | None]
) -> list[str]:
    """Sections the review would overwrite that changed since the review loaded them."""
    changed = []
    for key in requested:
        now = (current or {}).get(key)
        expected = shown.get(key)
        if expected is None:
            if now is not None and now["rows"] > 0:
                changed.append(key)
        elif now is None or now["fingerprint"] != expected:
            changed.append(key)
    return changed


def _as_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return str(value).lower()
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value).strip()


def outcomes(proposal: Mapping[str, Any], finals: Mapping[str, Any]) -> list[dict]:
    """For every value the scan proposed: what was read, proposed and finally kept."""
    proposed = final_values(proposal["sections"], proposal["header"])
    rows = []
    for at, sources in proposal["sources"].items():
        first = sources[0]
        flags = proposal["flags"].get(at) or []
        before, after = _as_text(proposed.get(at)), _as_text(finals.get(at))
        rows.append({
            "field_path": at,
            "page_id": first["page_id"],
            "read_text": first["text"],
            "confidence": first["confidence"],
            "proposed_value": before,
            "final_value": after,
            "flag": flags[0]["reason"] if flags else None,
            "changed": before != after,
        })
    return rows


def aliases_to_learn(coded: Mapping[str, Mapping[str, Any]], finals: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """(kind, text written, value chosen) wherever the user chose something other than the resolution."""
    learned = []
    for at, entry in coded.items():
        final = finals.get(at)
        if final in (None, "") or final == entry["value"] or not entry["read_text"].strip():
            continue
        learned.append((entry["kind"], entry["read_text"], str(final)))
    return learned
