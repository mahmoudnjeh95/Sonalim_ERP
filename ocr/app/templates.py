"""A fiche's printed layout, as data: its title, the landmarks only it has, the header
labels, and each block's band title and column headers (left to right).

`x` is a column's nominal centre as a fraction of the block's width, used only for a
column whose printed header was not read. Calibrate against a blank fiche.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Column:
    key: str
    headers: tuple[str, ...]
    x: float = 0.5


@dataclass(frozen=True)
class Block:
    key: str
    anchors: tuple[str, ...]
    columns: tuple[Column, ...]
    layout: str = "table"  # table | labels
    exclude: tuple[str, ...] = ()
    x_range: tuple[float, float] = (0.0, 1.0)


@dataclass(frozen=True)
class HeaderField:
    key: str
    anchors: tuple[str, ...]
    kind: str = "right_of"  # right_of | checkbox
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Template:
    form_type: str
    titles: tuple[str, ...]
    markers: tuple[str, ...]
    header: tuple[HeaderField, ...]
    blocks: tuple[Block, ...]
    boundaries: tuple[str, ...] = ()


def _template(data: dict) -> Template:
    return Template(
        form_type=data["form_type"],
        titles=tuple(data["titles"]),
        markers=tuple(data.get("markers", ())),
        header=tuple(
            HeaderField(f["key"], tuple(f["anchors"]), f.get("kind", "right_of"), tuple(f.get("exclude", ())))
            for f in data.get("header", ())
        ),
        blocks=tuple(
            Block(
                key=b["key"],
                anchors=tuple(b["anchors"]),
                columns=tuple(Column(c["key"], tuple(c["headers"]), float(c.get("x", 0.5))) for c in b["columns"]),
                layout=b.get("layout", "table"),
                exclude=tuple(b.get("exclude", ())),
                x_range=tuple(b.get("x_range", (0.0, 1.0))),
            )
            for b in data["blocks"]
        ),
        boundaries=tuple(data.get("boundaries", ())),
    )


def load_templates(directory: Path) -> list[Template]:
    return [_template(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(Path(directory).glob("*.json"))]
