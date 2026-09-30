"""The example fiches end to end. The photos hold workers' names: they live outside the
repo, in OCR_FIXTURES_DIR, and the photo tests skip when it is not set."""
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

FIXTURES = os.environ.get("OCR_FIXTURES_DIR")
photos = pytest.mark.skipif(not FIXTURES, reason="OCR_FIXTURES_DIR not set")

EXPECTED_TEXT = {
    "fabrication": [("production", "sem_tonnes", "3,25"), ("production", "water", "28,9"), ("production", "humidity", "9,83"),
                    ("stops", "start", "12h18"), ("silo_end", "level", "29")],
    "conditionnement": [("packing", "lot", "D6249SNL"), ("waste", "quantity", "75,28"), ("silo_end", "level", "29")],
}
# Key cells read on the example photos when this floor was set (2026-09-30, templates with column
# centres, per-cell re-read on): fabrication 1/5 (stops.start), conditionnement 1/3 (silo_end.level).
# Raise these as the reading improves; a drop below them is a regression.
MIN_KEY_CELLS = {"fabrication": 1, "conditionnement": 1}


@pytest.fixture(scope="module")
def reader():
    from app.engine import Engine
    from app.pipeline import TEMPLATES, read
    engine = Engine()
    return lambda data: read(engine, TEMPLATES, data, None)


@photos
@pytest.mark.parametrize("name", ["fabrication", "conditionnement", "bobines"])
def test_form_type_and_orientation(reader, name):
    result = reader((Path(FIXTURES) / f"{name}.png").read_bytes())
    assert result["form_type"] == name
    if name == "bobines":
        assert result["rotation"] in (90, 270)
    else:
        assert result["rotation"] == 0


@photos
@pytest.mark.parametrize("name", ["fabrication", "conditionnement"])
def test_key_cells_accuracy_report(reader, name):
    result = reader((Path(FIXTURES) / f"{name}.png").read_bytes())
    blocks = {b["key"]: b for b in result["blocks"]}
    hits = 0
    for block, cell, expected in EXPECTED_TEXT[name]:
        texts = [r["cells"].get(cell, {}).get("text", "") for r in blocks.get(block, {"rows": []})["rows"]]
        found = any(expected.replace(" ", "") in t.replace(" ", "") for t in texts)
        hits += found
        print(f"{name}.{block}.{cell}: expected {expected!r}, read {texts!r} -> {'OK' if found else 'MISS'}")
    print(f"{name}: {hits}/{len(EXPECTED_TEXT[name])} key cells read")
    assert hits >= MIN_KEY_CELLS[name]


class _FakeEngine:
    """Detection gives a waste row whose quantity and cause are glued in one box; the
    re-read of each column region reads them apart (blank for the time column)."""

    def detect(self, image):
        from app.locate import TextBox
        return [
            TextBox("FICHE CONDITIONNEMENT PAR EQUIPE", 1.0, 250, 40, 750, 70),
            TextBox("DECHET PATES OU INTRANTS", 1.0, 380, 600, 620, 620),
            TextBox("Heure", 1.0, 20, 630, 60, 645), TextBox("Type de déchet", 1.0, 100, 630, 200, 645),
            TextBox("Qté (kg)", 1.0, 260, 630, 320, 645), TextBox("Cause", 1.0, 400, 630, 460, 645),
            TextBox("Produits finis", 0.9, 100, 660, 200, 680),
            TextBox("75,25Ke Nettoyage", 0.4, 260, 660, 480, 680),
        ]

    def recognize(self, crop):
        # Column spans (x 20..750): type 95-220, quantity 220-360, cause 360-750; crops add 2 px a side.
        width = crop.shape[1]
        if width < 135:
            return "", 0.0
        return ("75,28Kg", 0.95) if width < 200 else ("Nettoyage", 0.95)


def test_each_table_cell_is_re_read_from_its_own_region():
    from app.pipeline import TEMPLATES, read
    data = cv2.imencode(".png", np.full((900, 1000, 3), 255, np.uint8))[1].tobytes()
    result = read(_FakeEngine(), TEMPLATES, data, None)
    [row] = next(b for b in result["blocks"] if b["key"] == "waste")["rows"]
    assert set(row) == {"cells"}
    assert row["cells"]["quantity"]["text"] == "75,28Kg" and row["cells"]["quantity"]["confidence"] == 0.95
    assert row["cells"]["cause"]["text"] == "Nettoyage"
    # A blank re-read keeps what detection read there.
    assert row["cells"]["type"]["text"] == "Produits finis" and row["cells"]["type"]["confidence"] == 0.9
    # Boxes are fractions of the upright image.
    assert all(0 <= v <= 1 for cell in row["cells"].values() for v in cell["box"])
