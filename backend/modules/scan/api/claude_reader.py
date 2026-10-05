"""Reads a photographed fiche with Claude (vision) instead of the local OCR container.

It answers with the same contract as the OCR container's `POST /read` (see
`domain/ocr_result.py`), so the reading queue, the proposal, the dictionary and the
review screen are unchanged: Claude only transcribes what is written in each cell. All
interpretation -- decimals with commas, times, lots, codes, cross-checks -- stays in
`scan/domain`, exactly as with the OCR.

Claude does not give a numeric confidence per cell, so it marks a cell `uncertain`
when the handwriting is hard to read; that maps under the page's `accept_score`, which
is what makes the review screen show the cell in yellow.

Unlike the OCR container, this sends the photo to the Anthropic API. Enabled on the
worker with SCAN_READER=claude and CLAUDE_API_KEY.
"""
from __future__ import annotations

import base64
import json
import logging
import os

import anthropic

from modules.scan.api.ocr_client import OcrReadError, OcrUnavailable

logger = logging.getLogger(__name__)

SCAN_CLAUDE_MODEL = os.environ.get("SCAN_CLAUDE_MODEL") or os.environ.get("CLAUDE_MODEL", "claude-opus-5")
# The API's own per-image limit; the browser already downscales to 2400 px, so a page is far below it.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ACCEPT_SCORE = 0.5
CONFIDENT, UNCERTAIN = 0.95, 0.3

# What each fiche holds, keyed like ocr/templates/*.json, with the printed labels Claude
# looks for. Keys are the contract the domain mappers read (fabrication.py, ...).
FORMS: dict[str, dict] = {
    "fabrication": {
        "title": "FICHE FABRICATION PAR EQUIPE",
        "header": {
            "date": "Date", "team_hours": "Équipe + heures (e.g. 'D 07H à 14H00')",
            "line_pc": "Ligne PC checkbox ('x' only if ticked)", "line_pl": "Ligne PL checkbox ('x' only if ticked)",
            "conducteur": "Conducteur ligne", "agent_fabrication": "Agent de fabrication",
        },
        "blocks": {
            "production": ("PRODUCTION table, one row per written line", {
                "lot": "N° lot", "product": "Produit/Format", "start": "HD prod", "end": "HF prod",
                "sem_origin": "Semoule: Origine", "sem_lot": "Semoule: Lot", "sem_bags": "Semoule: Qté (sac)",
                "sem_tonnes": "Semoule: Qté (T)", "broy_lot": "Broyage: Lot", "broy_percent": "Broyage: %",
                "broy_bags": "Broyage: Qté (sac)", "broy_kg": "Broyage: Qté (kg)", "water": "% Eau", "humidity": "Humidité",
            }),
            "waste_petrin": ("PÂTES NON CONFORMES -- Déchet pétrin", {
                "time": "Heure", "format": "Format", "lot": "N° lot", "quantity": "Qté (kg)", "cause": "Cause",
            }),
            "waste_finished": ("PÂTES NON CONFORMES -- Produit fini", {
                "time": "Heure", "format": "Format", "lot": "N° lot", "quantity": "Qté (kg)", "cause": "Cause",
            }),
            "mold_washes": ("LAVAGE DES MOULES", {"mold": "N° moule", "time": "Heure", "state": "État"}),
            "staffing": ("PRÉSENCE PERSONNEL -- a single row with the number written beside each label", {
                "control_room": "Salle de contrôle", "petrin": "Pétrin", "semoule": "Semoule", "broyage": "Broyage",
            }),
            "stops": ("ARRÊT DE LA PRODUCTION", {
                "panne": "Panne", "start": "Heure d.", "end": "Heure f.", "action": "Action corrective",
            }),
            "silo_start": ("ÉTAT DE SILO -- Début production", {
                "format": "Format", "lot": "N° du lot", "level": "Quantité %", "line_state": "État de la ligne",
            }),
            "silo_end": ("ÉTAT DE SILO -- Fin production", {
                "format": "Format", "lot": "N° du lot", "level": "Quantité %", "line_state": "État de la ligne",
            }),
        },
    },
    "conditionnement": {
        "title": "FICHE CONDITIONNEMENT PAR EQUIPE",
        "header": {
            "date": "Date", "team_hours": "Équipe + heures",
            "line_pc": "Ligne PC checkbox ('x' only if ticked)", "line_pl": "Ligne PL checkbox ('x' only if ticked)",
            "machiniste": "Machiniste", "aide_machiniste": "Aide machiniste",
        },
        "blocks": {
            "silo_start": ("ÉTAT DU SILO -- Début production", {
                "format": "Format", "lot": "N° du lot", "level": "Quantité %", "line_state": "État de la ligne",
            }),
            "silo_end": ("ÉTAT DU SILO -- Fin production", {
                "format": "Format", "lot": "N° du lot", "level": "Quantité %", "line_state": "État de la ligne",
            }),
            "packing": ("CONDITIONNEMENT", {
                "format": "Format", "lot": "N° lot", "fab_date": "Date de fab", "pack_type": "Type de condit.",
                "film_type": "Type film", "cartons": "Qté cartons", "bobine": "Qté bobine", "scotch": "Qté scotch",
                "ruban": "Qté ruban",
            }),
            "packet_checks": ("VÉRIFICATION D'ÉTAT DE PAQUET", {
                "time": "Heure", "film": "Film", "weight": "Pds paquet", "long_weld": "Soudure longi.",
                "vert_weld": "Soudure vert.", "date_print": "Imp. date", "observation": "Observation",
            }),
            "waste": ("DÉCHETS PÂTES OU INTRANTS", {
                "time": "Heure", "type": "Type de déchet", "quantity": "Qté (kg)", "cause": "Cause",
            }),
            "stops": ("ARRÊT MACHINE", {
                "panne": "Panne", "start": "Heure d.", "end": "Heure f.", "action": "Action corrective",
            }),
        },
    },
    "bobines": {
        "title": "FICHE CHANGEMENT BOBINES",
        "header": {},
        "blocks": {
            "changes": ("The roll-change table, one row per written line", {
                "date": "Date", "team": "Éq.", "hours": "H. travail", "machine": "N° machine", "counter": "D. compteur",
                "format": "Format", "reel_type": "Type bobine", "internal_lot": "N° lot int.", "start": "H.D",
                "end": "H.F", "reel_weight": "Pds bobine", "core_weight": "Pds cyl.", "waste": "Déchets",
                "remain_weight": "Reste: poids", "remain_conf": "Reste: conf.", "remain_nonconf": "Reste: non conf.",
                "machinist": "Machiniste",
            }),
        },
    },
}

_HEADER_KEYS = sorted({key for form in FORMS.values() for key in form["header"]})
_BLOCK_KEYS = sorted({key for form in FORMS.values() for key in form["blocks"]})
_CELL_KEYS = sorted({key for form in FORMS.values() for _, columns in form["blocks"].values() for key in columns})


def _cell_schema(keys: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string", "enum": keys},
            "text": {"type": "string"},
            "uncertain": {"type": "boolean"},
            "box": {"anyOf": [{"type": "array", "items": {"type": "number"}}, {"type": "null"}]},
        },
        "required": ["key", "text", "uncertain", "box"],
        "additionalProperties": False,
    }


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "form_type": {"anyOf": [{"type": "string", "enum": sorted(FORMS)}, {"type": "null"}]},
        "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
        "header": {"type": "array", "items": _cell_schema(_HEADER_KEYS)},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "enum": _BLOCK_KEYS},
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"cells": {"type": "array", "items": _cell_schema(_CELL_KEYS)}},
                            "required": ["cells"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["key", "rows"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["form_type", "rotation", "header", "blocks"],
    "additionalProperties": False,
}


def _describe_forms() -> str:
    parts = []
    for form_type, form in FORMS.items():
        lines = [f'form_type "{form_type}" -- printed title "{form["title"]}"']
        if form["header"]:
            lines.append("  header: " + "; ".join(f"{k} = {label}" for k, label in form["header"].items()))
        for block_key, (title, columns) in form["blocks"].items():
            lines.append(f'  block "{block_key}" ({title}): ' + "; ".join(f"{k} = {label}" for k, label in columns.items()))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


SYSTEM_PROMPT = (
    "You transcribe photos of handwritten paper forms (fiches) from a pasta factory's "
    "production line into structured cells. Another system parses and checks the values, "
    "so your only job is a faithful transcription.\n\n"
    "The fiches, their blocks and the key of each column:\n\n"
    f"{_describe_forms()}\n\n"
    "Rules:\n"
    "- Identify the fiche by its printed title. A partial photo without its title can be "
    "identified by its block titles. If the photo is not one of these fiches, return "
    "form_type null with empty header and blocks.\n"
    "- rotation: the clockwise rotation in degrees that makes the page upright (0 if it already is).\n"
    "- Copy handwriting exactly as written: keep French decimal commas, units, leading zeros "
    "and abbreviations ('02,46kg', '09h27mn', 'BSK1', 'Ver'). Do not convert, translate, "
    "complete or correct anything, and never invent a value for an empty cell.\n"
    "- Only use the keys listed for the identified fiche. List only blocks visible on the "
    "photo, one row per written line in paper order, skipping fully blank lines. Omit empty "
    "cells. A sentence written across a row (e.g. a stop described in the Panne column with "
    "its times) goes in the cell where it starts.\n"
    "- Set uncertain to true when a cell's handwriting is hard to read or you had to guess "
    "a character; false when you are sure of it.\n"
    "- box: the cell's position as [x0, y0, x1, y1] fractions (0-1) of the upright page, "
    "or null if you cannot place it."
)


def _media_type(image: bytes) -> str:
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    raise OcrReadError("unsupported image format (expected JPEG, PNG or WebP)")


def _box(value) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    x0, y0, x1, y1 = (min(max(float(v), 0.0), 1.0) for v in value)
    return [x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None


def _cells(items: list[dict], allowed: set[str] | dict) -> dict:
    cells = {}
    for item in items:
        text = str(item.get("text") or "").strip()
        if item.get("key") not in allowed or not text:
            continue
        cells[item["key"]] = {
            "text": text,
            "confidence": UNCERTAIN if item.get("uncertain") else CONFIDENT,
            "box": _box(item.get("box")),
        }
    return cells


def to_contract(answer: dict, form_hint: str | None, model: str) -> dict:
    """Claude's answer -> the OCR container's /read result. Keys that don't belong to the
    identified fiche are dropped, so the domain never sees a cell it has no mapper for."""
    form_type = answer.get("form_type") or None
    if form_hint in FORMS:
        form_type = form_hint
    rotation = answer.get("rotation") if answer.get("rotation") in (0, 90, 180, 270) else 0
    result = {
        "form_type": form_type if form_type in FORMS else None,
        "form_confidence": 1.0 if form_type in FORMS else 0.0,
        "rotation": rotation,
        "accept_score": ACCEPT_SCORE,
        "header": {},
        "blocks": [],
        "reader": "claude",
        "model": model,
    }
    if result["form_type"] is None:
        return result
    form = FORMS[result["form_type"]]
    result["header"] = _cells(answer.get("header") or [], form["header"])
    by_key: dict[str, list[dict]] = {}
    for block in answer.get("blocks") or []:
        if block.get("key") not in form["blocks"]:
            continue
        columns = form["blocks"][block["key"]][1]
        rows = [{"cells": cells} for row in block.get("rows") or [] if (cells := _cells(row.get("cells") or [], columns))]
        by_key.setdefault(block["key"], []).extend(rows)
    result["blocks"] = [
        {"key": key, "found": key in by_key, "rows": by_key.get(key, [])} for key in form["blocks"]
    ]
    return result


class ClaudeReader:
    """Same call shape as OcrClient.read, so the worker's reading queue takes either."""

    def __init__(self, api_key: str, model: str = SCAN_CLAUDE_MODEL, client: anthropic.Anthropic | None = None) -> None:
        self._model = model
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=300, max_retries=2)

    def read(self, image: bytes, form_hint: str | None) -> dict:
        if len(image) > MAX_IMAGE_BYTES:
            raise OcrReadError(f"image is {len(image)} bytes, above the {MAX_IMAGE_BYTES} the API accepts")
        instruction = "Transcribe this fiche."
        if form_hint in FORMS:
            instruction += f' The user says it is the "{form_hint}" fiche ({FORMS[form_hint]["title"]}).'
        try:
            with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=32000,
                system=SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                # A declined request is re-run server-side on Anthropic's recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": _media_type(image),
                            "data": base64.standard_b64encode(image).decode("ascii"),
                        }},
                        {"type": "text", "text": instruction},
                    ],
                }],
            ) as stream:
                message = stream.get_final_message()
        # Outages, rate limits and a missing/wrong key: the page waits in the queue without
        # spending an attempt, and reading resumes once the API (or the key) is back.
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError,
                anthropic.AuthenticationError, anthropic.PermissionDeniedError) as error:
            logger.warning("Claude scan reader unavailable: %s", error)
            raise OcrUnavailable(f"Claude API: {error}") from error
        except anthropic.APIStatusError as error:
            raise OcrReadError(f"Claude API {error.status_code}: {error.message}") from error
        if message.stop_reason == "refusal":
            raise OcrReadError("Claude declined to read this photo")
        if message.stop_reason == "max_tokens":
            raise OcrReadError("Claude's transcription was cut off (max_tokens)")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise OcrReadError(f"Claude returned no transcription (stop_reason={message.stop_reason})")
        try:
            answer = json.loads(text)
        except json.JSONDecodeError as error:
            raise OcrReadError(f"Claude returned invalid JSON: {error}") from error
        return to_contract(answer, form_hint, self._model)
