"""One fiche from several photos of it: the best reading of each cell wins.

Photos of the same block with the same number of written rows are merged cell by cell,
and a cell whose readings differ keeps the other reading as its `conflict`. When the
row counts differ the block with more written rows is kept whole and marked
`rows_disagree`: lining rows up across photos would be a guess.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from modules.scan.domain.ocr_result import PageRead, ReadBlock, ReadCell, ReadRow
from modules.scan.domain.text import normalize


def _better(a: ReadCell, b: ReadCell) -> ReadCell:
    if not a.text.strip():
        return b
    if not b.text.strip():
        return a
    keep, other = (a, b) if a.confidence >= b.confidence else (b, a)
    if normalize(keep.text) == normalize(other.text):
        return keep
    return replace(keep, conflict=other.text)


def _merge_cells(maps: Sequence[Mapping[str, ReadCell]]) -> dict[str, ReadCell]:
    out: dict[str, ReadCell] = {}
    for cells in maps:
        for key, cell in cells.items():
            out[key] = _better(out[key], cell) if key in out else cell
    return out


def _written(block: ReadBlock) -> list[ReadRow]:
    return [row for row in block.rows if not row.is_blank()]


def _merge_blocks(blocks: list[ReadBlock]) -> ReadBlock:
    if len(blocks) == 1:
        return blocks[0]
    rows = [_written(block) for block in blocks]
    if len({len(r) for r in rows}) == 1:
        merged = tuple(ReadRow(_merge_cells([r[i].cells for r in rows])) for i in range(len(rows[0])))
        return ReadBlock(blocks[0].key, True, merged)
    widest = max(range(len(blocks)), key=lambda i: len(rows[i]))
    return ReadBlock(blocks[0].key, True, tuple(rows[widest]), rows_disagree=True)


def merge_pages(pages: Sequence[PageRead]) -> PageRead:
    first = pages[0]
    if len(pages) == 1:
        return first
    keys = dict.fromkeys(key for page in pages for key, block in page.blocks.items() if block.found)
    blocks = {key: _merge_blocks([p.blocks[key] for p in pages if key in p.blocks and p.blocks[key].found]) for key in keys}
    return PageRead(
        page_id=first.page_id,
        form_type=first.form_type,
        rotation=first.rotation,
        header=_merge_cells([page.header for page in pages]),
        blocks=blocks,
        accept_score=first.accept_score,
    )
