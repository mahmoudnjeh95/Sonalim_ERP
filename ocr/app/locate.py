"""Finding a fiche's printed landmarks among the OCR's text boxes, and the handwriting in each cell.

Pure: text boxes in, cells out. A fiche is a fixed printed form, so its title, band
titles and column headers are printed text the engine reads reliably; they locate each
block and its columns, and every handwritten box goes to the cell it falls in. Each
block is located on its own, which is what lets a partial photo yield the blocks it holds.
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass

from app.templates import Block, Template


@dataclass(frozen=True)
class TextBox:
    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)

    @property
    def norm(self) -> str:
        return normalize(self.text)


def normalize(text: str | None) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def has_phrase(norm_text: str, phrase: str) -> bool:
    wanted = normalize(phrase)
    return bool(wanted) and re.search(rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])", norm_text) is not None


def _find(boxes, phrases, exclude=()) -> list[TextBox]:
    return [
        b for b in boxes
        if any(has_phrase(b.norm, p) for p in phrases) and not any(has_phrase(b.norm, e) for e in exclude)
    ]


def anchor_hits(boxes: list[TextBox], templates: list[Template]) -> int:
    """How many boxes read as a printed landmark of some fiche: the orientation score."""
    phrases = {p for t in templates for p in (*t.titles, *t.markers, *(a for b in t.blocks for a in b.anchors))}
    return sum(1 for b in boxes if any(has_phrase(b.norm, p) for p in phrases))


def classify(boxes: list[TextBox], templates: list[Template], hint: str | None = None) -> tuple[Template | None, float]:
    if hint:
        chosen = next((t for t in templates if t.form_type == hint), None)
        return (chosen, 1.0) if chosen else (None, 0.0)
    best, best_score = None, 0
    for template in templates:
        score = 3 * bool(_find(boxes, template.titles)) + sum(1 for m in template.markers if _find(boxes, (m,)))
        if score > best_score:
            best, best_score = template, score
    if best is None:
        return None, 0.0
    return best, round(best_score / (3 + len(best.markers)), 2)


def _same_line(a: TextBox, b: TextBox) -> bool:
    return min(a.y1, b.y1) - max(a.y0, b.y0) > 0.5 * min(a.height, b.height)


def _cell(boxes: list[TextBox]) -> dict:
    ordered = sorted(boxes, key=lambda b: b.x0)
    return {
        "text": " ".join(b.text.strip() for b in ordered if b.text.strip()),
        "confidence": round(min(b.score for b in ordered), 3),
        "box": [min(b.x0 for b in ordered), min(b.y0 for b in ordered), max(b.x1 for b in ordered), max(b.y1 for b in ordered)],
    }


def _inline_value(anchor: TextBox) -> str:
    """"Date : 07/09/26" read as one box: what follows the label."""
    text = anchor.text
    if ":" in text:
        return text.split(":", 1)[1].strip()
    return ""


def _extract_header(template: Template, boxes: list[TextBox]) -> tuple[dict, dict]:
    anchors: dict[str, TextBox | None] = {}
    for field in template.header:
        hits = _find(boxes, field.anchors, field.exclude)
        anchors[field.key] = min(hits, key=lambda b: (b.y0, b.x0)) if hits else None
    labels = [b for b in anchors.values() if b is not None] + _find(boxes, template.titles)
    cells: dict[str, dict] = {}
    regions: dict[str, tuple[float, float, float, float]] = {}
    for field in template.header:
        anchor = anchors[field.key]
        if anchor is None:
            continue
        if field.kind == "checkbox":
            regions[field.key] = (anchor.x1, anchor.y0, anchor.x1 + 1.6 * anchor.height, anchor.y1)
            continue
        stop = min((b.x0 for b in labels if b is not anchor and b.x0 > anchor.x1 and _same_line(b, anchor)), default=float("inf"))
        values = [b for b in boxes if b not in labels and _same_line(b, anchor) and anchor.x1 <= b.cx < stop]
        inline = _inline_value(anchor)
        parts = ([TextBox(inline, anchor.score, anchor.x0, anchor.y0, anchor.x1, anchor.y1)] if inline else []) + values
        if parts:
            cells[field.key] = _cell(parts)
    return cells, regions


def _span(block: Block, left: float, right: float) -> tuple[float, float]:
    width = right - left
    return left + block.x_range[0] * width, left + block.x_range[1] * width


def _bounds(template: Template, boxes: list[TextBox], height: float, left: float, right: float) -> dict[str, tuple[TextBox, float]]:
    found: dict[str, TextBox] = {}
    for block in template.blocks:
        lo, hi = _span(block, left, right)
        hits = [b for b in _find(boxes, block.anchors, block.exclude) if lo <= b.cx <= hi]
        if hits:
            found[block.key] = min(hits, key=lambda b: b.y0)
    stops = list(found.values()) + _find(boxes, template.boundaries)
    bounds = {}
    for block in template.blocks:
        if block.key not in found:
            continue
        anchor = found[block.key]
        lo, hi = _span(block, left, right)
        below = [s.y0 for s in stops if s is not anchor and s.y0 > anchor.cy and lo <= s.cx <= hi]
        bounds[block.key] = (anchor, min(below, default=height))
    return bounds


def _rows(boxes: list[TextBox]) -> list[list[TextBox]]:
    if not boxes:
        return []
    typical = statistics.median(b.height for b in boxes)
    rows: list[list[TextBox]] = []
    current: list[TextBox] = []
    for box in sorted(boxes, key=lambda b: b.cy):
        if current and box.cy - statistics.fmean(b.cy for b in current) > typical / 2:
            rows.append(current)
            current = []
        current.append(box)
    rows.append(current)
    return rows


def _centers(block: Block, hits: dict[str, TextBox], lo: float, hi: float) -> dict[str, float]:
    known = [(c.x, hits[c.key].cx) for c in block.columns if c.key in hits]
    if len(known) >= 2 and known[-1][0] != known[0][0]:
        (f0, p0), (f1, p1) = known[0], known[-1]
        scale = (p1 - p0) / (f1 - f0)
        offset = p0 - scale * f0
    elif known:
        scale = hi - lo
        offset = known[0][1] - scale * known[0][0]
    else:
        scale, offset = hi - lo, lo
    return {c.key: hits[c.key].cx if c.key in hits else offset + scale * c.x for c in block.columns}


def _column_spans(centers: list[tuple[str, float]], lo: float, hi: float) -> dict[str, tuple[float, float]]:
    """Each column's horizontal span: from the midpoint with its neighbour (or the
    block's edge for the first/last column)."""
    spans: dict[str, tuple[float, float]] = {}
    for i, (key, cx) in enumerate(centers):
        span_lo = lo if i == 0 else (centers[i - 1][1] + cx) / 2
        span_hi = hi if i == len(centers) - 1 else (cx + centers[i + 1][1]) / 2
        spans[key] = (span_lo, span_hi)
    return spans


def _table(block: Block, anchor: TextBox, bottom: float, boxes: list[TextBox], lo: float, hi: float) -> list[dict]:
    region = [b for b in boxes if anchor.y0 <= b.cy < bottom and lo <= b.cx <= hi and b is not anchor]
    hits: dict[str, TextBox] = {}
    previous = lo - 1
    for column in block.columns:
        candidates = sorted((b for b in _find(region, column.headers) if b.cx > previous and b not in hits.values()), key=lambda b: b.cx)
        if candidates:
            hits[column.key] = candidates[0]
            previous = candidates[0].cx
    printed = set(hits.values())
    header_bottom = max((b.y1 for b in printed), default=anchor.y1)
    centers = sorted(_centers(block, hits, lo, hi).items(), key=lambda kv: kv[1])
    spans = _column_spans(centers, lo, hi)
    data = [b for b in region if b not in printed and b.cy > header_bottom]
    rows = []
    for row in _rows(data):
        cells: dict[str, list[TextBox]] = {}
        for box in row:
            key = min(centers, key=lambda kv: abs(kv[1] - box.cx))[0]
            cells.setdefault(key, []).append(box)
        regions: dict[str, tuple[float, float, float, float]] = {}
        row_y0 = min(b.y0 for b in row)
        row_y1 = max(b.y1 for b in row)
        for key, (span_lo, span_hi) in spans.items():
            if any(b.x1 > span_lo and b.x0 < span_hi for b in row):
                regions[key] = (span_lo, row_y0, span_hi, row_y1)
        rows.append({"cells": {key: _cell(parts) for key, parts in cells.items()}, "regions": regions})
    return rows


def _labels(block: Block, anchor: TextBox, bottom: float, boxes: list[TextBox], lo: float, hi: float) -> list[dict]:
    region = [b for b in boxes if anchor.y1 <= b.cy < bottom and lo <= b.cx <= hi]
    printed = _find(region, [h for c in block.columns for h in c.headers])
    row = {}
    for column in block.columns:
        hits = _find(region, column.headers)
        if not hits:
            continue
        label = min(hits, key=lambda b: b.y0)
        values = [b for b in region if b not in printed and _same_line(b, label) and b.cx > label.x1]
        if values:
            row[column.key] = _cell(values)
    return [{"cells": row, "regions": {}}] if row else []


def extract(template: Template, boxes: list[TextBox], width: float, height: float) -> dict:
    left = min((b.x0 for b in boxes), default=0.0)
    right = max((b.x1 for b in boxes), default=float(width))
    header, regions = _extract_header(template, boxes)
    bounds = _bounds(template, boxes, height, left, right)
    blocks = []
    for block in template.blocks:
        if block.key not in bounds:
            blocks.append({"key": block.key, "found": False, "rows": []})
            continue
        anchor, bottom = bounds[block.key]
        lo, hi = _span(block, left, right)
        rows = (_labels if block.layout == "labels" else _table)(block, anchor, bottom, boxes, lo, hi)
        blocks.append({"key": block.key, "found": True, "rows": rows})
    return {"header": header, "blocks": blocks, "checkbox_regions": regions}
