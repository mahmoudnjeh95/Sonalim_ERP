"""What the OCR container returns for one photo, as the domain reads it.

The container only locates printed anchors and returns the handwriting found in each
cell with the engine's confidence and the cell's box (fractions of the upright image).
Every cell remembers the photo it came from, so a value can be shown on its photo even
after several photos of the same fiche are merged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class ReadCell:
    text: str
    confidence: float
    box: tuple[float, float, float, float] | None = None
    page_id: str | None = None
    # Another photo's different reading of the same cell, kept so the user can choose.
    conflict: str | None = None


EMPTY_CELL = ReadCell("", 1.0)


@dataclass(frozen=True)
class ReadRow:
    cells: Mapping[str, ReadCell]

    def cell(self, key: str) -> ReadCell:
        return self.cells.get(key, EMPTY_CELL)

    def is_blank(self) -> bool:
        return all(not c.text.strip() for c in self.cells.values())


@dataclass(frozen=True)
class ReadBlock:
    key: str
    found: bool
    rows: tuple[ReadRow, ...]
    # Photos of this block showed different numbers of written rows; the longest was kept.
    rows_disagree: bool = False


@dataclass(frozen=True)
class PageRead:
    page_id: str
    form_type: str | None
    rotation: int
    header: Mapping[str, ReadCell]
    blocks: Mapping[str, ReadBlock] = field(default_factory=dict)
    accept_score: float = 0.5

    def block(self, key: str) -> ReadBlock | None:
        block = self.blocks.get(key)
        return block if block is not None and block.found else None

    def head(self, key: str) -> ReadCell:
        return self.header.get(key, EMPTY_CELL)


def _cell(data: dict, page_id: str) -> ReadCell:
    box = data.get("box")
    return ReadCell(
        text=str(data.get("text") or ""),
        confidence=float(data.get("confidence") or 0.0),
        box=tuple(float(v) for v in box) if box else None,
        page_id=page_id,
    )


def page_read_from_json(page_id: str, data: dict) -> PageRead:
    header = {key: _cell(value, page_id) for key, value in (data.get("header") or {}).items()}
    blocks = {}
    for block in data.get("blocks") or []:
        rows = tuple(
            ReadRow({key: _cell(value, page_id) for key, value in (row.get("cells") or {}).items()})
            for row in block.get("rows") or []
        )
        blocks[block["key"]] = ReadBlock(block["key"], bool(block.get("found")), rows)
    return PageRead(
        page_id=page_id,
        form_type=data.get("form_type"),
        rotation=int(data.get("rotation") or 0),
        header=header,
        blocks=blocks,
        accept_score=float(data.get("accept_score") or 0.5),
    )
