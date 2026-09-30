"""One photo to the OCR result the backend reads: upright it, type it, locate its cells,
then re-read each table cell from its own crop."""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from app.engine import ACCEPT_SCORE
from app.locate import anchor_hits, classify, extract
from app.templates import load_templates

TEMPLATES = load_templates(Path(__file__).resolve().parents[1] / "templates")
_ROTATIONS = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
_ORIENTATION_SIDE = 960
# Enough printed landmarks read on the photo as taken: no need to try the other rotations.
_UPRIGHT_ENOUGH = 3
# Pixels added around a cell's region before re-reading it, so strokes on its edge stay whole.
_CROP_PAD = 2


def _rotate(image: np.ndarray, degrees: int) -> np.ndarray:
    code = _ROTATIONS[degrees]
    return image if code is None else cv2.rotate(image, code)


def _shrink(image: np.ndarray) -> np.ndarray:
    scale = _ORIENTATION_SIDE / max(image.shape[:2])
    return image if scale >= 1 else cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _orientation(engine, image: np.ndarray) -> int:
    """The clockwise rotation under which the most printed landmarks are read as lines
    running left to right. The engine also reads a sideways line (it turns a tall box
    before reading it), so only boxes wider than tall count."""
    small = _shrink(image)
    best, best_hits = 0, -1
    for degrees in _ROTATIONS:
        boxes = [b for b in engine.detect(_rotate(small, degrees)) if b.x1 - b.x0 > b.y1 - b.y0]
        hits = anchor_hits(boxes, TEMPLATES)
        if hits > best_hits:
            best, best_hits = degrees, hits
        if degrees == 0 and hits >= _UPRIGHT_ENOUGH:
            break
    return best


def _ink(gray: np.ndarray, region: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = (int(round(v)) for v in region)
    crop = gray[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)]
    if crop.size == 0:
        return 0.0
    _, dark = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return float(dark.mean()) / 255


def _ticks(gray: np.ndarray, regions: dict) -> dict:
    """PC / PL: the box with more ink than the other is the one ticked."""
    if "line_pc" not in regions or "line_pl" not in regions:
        return {}
    pc, pl = _ink(gray, regions["line_pc"]), _ink(gray, regions["line_pl"])
    if pc == pl:
        return {}
    ticked = "line_pc" if pc > pl else "line_pl"
    confidence = round(abs(pc - pl) / max(pc + pl, 1e-6), 3)
    return {ticked: {"text": "x", "confidence": confidence, "box": list(regions[ticked])}}


def _crop(image: np.ndarray, region: tuple[float, float, float, float]) -> np.ndarray:
    height, width = image.shape[:2]
    x0, y0, x1, y1 = region
    left, top = max(math.floor(x0) - _CROP_PAD, 0), max(math.floor(y0) - _CROP_PAD, 0)
    right, bottom = min(math.ceil(x1) + _CROP_PAD, width), min(math.ceil(y1) + _CROP_PAD, height)
    return image[top:bottom, left:right]


def _reread(engine, image: np.ndarray, row: dict) -> dict:
    """The row's cells with each column region read again on its own: a non-blank re-read
    replaces what detection put there; a blank one keeps it."""
    cells = dict(row["cells"])
    for key, region in row["regions"].items():
        text, score = engine.recognize(_crop(image, region))
        if text.strip():
            cells[key] = {"text": text.strip(), "confidence": round(score, 3), "box": list(region)}
    return cells


def _fractions(cell: dict, width: int, height: int) -> dict:
    x0, y0, x1, y1 = cell["box"]
    return {**cell, "box": [round(x0 / width, 4), round(y0 / height, 4), round(x1 / width, 4), round(y1 / height, 4)]}


def _empty(rotation: int) -> dict:
    return {"form_type": None, "form_confidence": 0.0, "rotation": rotation, "accept_score": ACCEPT_SCORE, "header": {}, "blocks": []}


def read(engine, templates, data: bytes, form_hint: str | None) -> dict:
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return _empty(0)
    rotation = _orientation(engine, image)
    upright = _rotate(image, rotation)
    height, width = upright.shape[:2]
    boxes = engine.detect(upright)
    template, confidence = classify(boxes, templates, form_hint)
    if template is None:
        return _empty(rotation)
    found = extract(template, boxes, width, height)
    header = {**found["header"], **_ticks(cv2.cvtColor(upright, cv2.COLOR_BGR2GRAY), found["checkbox_regions"])}
    return {
        "form_type": template.form_type,
        "form_confidence": confidence,
        "rotation": rotation,
        "accept_score": ACCEPT_SCORE,
        "header": {key: _fractions(cell, width, height) for key, cell in header.items()},
        "blocks": [
            {
                **block,
                "rows": [
                    {"cells": {k: _fractions(c, width, height) for k, c in _reread(engine, upright, row).items()}}
                    for row in block["rows"]
                ],
            }
            for block in found["blocks"]
        ],
    }
