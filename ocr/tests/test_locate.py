from pathlib import Path

from app.locate import TextBox, anchor_hits, classify, extract
from app.templates import load_templates

TEMPLATES = load_templates(Path(__file__).resolve().parents[1] / "templates")


def box(text, x0, y0, x1, y1, score=0.9):
    return TextBox(text, score, x0, y0, x1, y1)


# A conditionnement fiche, upright, 1000 px wide.
CONDITIONNEMENT = [
    box("FICHE CONDITIONNEMENT PAR EQUIPE", 250, 40, 750, 70),
    box("Date de création : 17 Juillet 2023", 800, 20, 990, 35),
    box("Ligne:", 20, 100, 70, 120), box("PC", 80, 100, 100, 120), box("PL", 160, 100, 180, 120),
    box("Date :", 300, 100, 350, 120), box("07/09/26", 360, 100, 450, 120),
    box("Equipe :", 600, 100, 660, 120), box("D 07H à 14H", 670, 100, 800, 120),
    box("Machiniste", 20, 140, 100, 160), box("Machiniste Trois", 110, 140, 260, 160),
    box("Aide machiniste:", 330, 140, 450, 160), box("Aide Quatre", 460, 140, 560, 160),
    box("CONDITIONNEMENT", 400, 300, 600, 320),
    box("Format", 20, 330, 80, 345), box("N° lot", 100, 330, 160, 345), box("Date de fab", 180, 330, 260, 345),
    box("Type de conditi", 280, 330, 360, 345), box("Type film", 380, 330, 440, 345), box("Qté du cartons", 460, 330, 540, 345),
    box("Qté bobine", 560, 330, 620, 345), box("Qté scotch", 640, 330, 700, 345), box("Qté ruban", 720, 330, 780, 345),
    box("Vermicelles", 20, 360, 90, 380), box("D6249SNL", 100, 360, 170, 380), box("07-0926", 180, 360, 250, 380),
    box("(500g)", 290, 360, 340, 380), box("Active", 385, 360, 430, 380),
    box("VERIFICATION D'ETAT DE PAQUET", 350, 420, 650, 440),
    box("DECHET PATES OU INTRANTS", 380, 600, 620, 620),
    box("Heure", 20, 630, 60, 645), box("Type de déchet", 100, 630, 200, 645), box("Qté (kg)", 260, 630, 320, 645), box("Cause", 400, 630, 460, 645),
    box("07H14", 20, 660, 60, 680), box("Produits finis", 100, 660, 200, 680), box("02,46kg", 260, 660, 320, 680),
    box("Nettoyage de la Machine", 400, 660, 560, 680),
    box("Films Déchet C1", 100, 692, 200, 712), box("0,35Kg", 260, 692, 320, 712), box("Réglage de Machine", 400, 692, 540, 712),
    box("ARRET MACHINE", 420, 800, 580, 820),
]


def _block(result, key):
    return next(b for b in result["blocks"] if b["key"] == key)


def test_the_form_is_classified_by_its_title_and_markers():
    template, confidence = classify(CONDITIONNEMENT, TEMPLATES)
    assert template.form_type == "conditionnement" and confidence > 0.5
    assert classify([box("nothing printed", 0, 0, 10, 10)], TEMPLATES) == (None, 0.0)
    assert classify([], TEMPLATES, hint="bobines")[0].form_type == "bobines"


def test_anchor_hits_count_printed_landmarks():
    assert anchor_hits(CONDITIONNEMENT, TEMPLATES) >= 4
    assert anchor_hits([box("D6249SNL", 0, 0, 10, 10)], TEMPLATES) == 0


def test_header_fields_are_read_right_of_their_label():
    template, _ = classify(CONDITIONNEMENT, TEMPLATES)
    header = extract(template, CONDITIONNEMENT, 1000, 900)["header"]
    assert header["date"]["text"] == "07/09/26"
    assert header["team_hours"]["text"] == "D 07H à 14H"
    assert header["machiniste"]["text"] == "Machiniste Trois"
    assert header["aide_machiniste"]["text"] == "Aide Quatre"


def test_checkbox_regions_sit_right_of_pc_and_pl():
    template, _ = classify(CONDITIONNEMENT, TEMPLATES)
    regions = extract(template, CONDITIONNEMENT, 1000, 900)["checkbox_regions"]
    assert regions["line_pc"][0] == 100 and regions["line_pl"][0] == 180


def test_table_rows_land_in_their_columns():
    template, _ = classify(CONDITIONNEMENT, TEMPLATES)
    result = extract(template, CONDITIONNEMENT, 1000, 900)
    [packing] = _block(result, "packing")["rows"]
    cells = {k: v["text"] for k, v in packing["cells"].items()}
    assert cells == {"format": "Vermicelles", "lot": "D6249SNL", "fab_date": "07-0926", "pack_type": "(500g)", "film_type": "Active"}
    waste = _block(result, "waste")["rows"]
    assert [{k: v["text"] for k, v in r["cells"].items()} for r in waste] == [
        {"time": "07H14", "type": "Produits finis", "quantity": "02,46kg", "cause": "Nettoyage de la Machine"},
        {"type": "Films Déchet C1", "quantity": "0,35Kg", "cause": "Réglage de Machine"},
    ]
    assert _block(result, "packet_checks") == {"key": "packet_checks", "found": True, "rows": []}
    assert _block(result, "silo_start")["found"] is False


def test_a_partial_photo_yields_only_its_blocks():
    partial = [b for b in CONDITIONNEMENT if b.y0 >= 590]
    template, _ = classify(partial, TEMPLATES)
    assert template.form_type == "conditionnement"
    result = extract(template, partial, 1000, 900)
    assert len(_block(result, "waste")["rows"]) == 2 and _block(result, "packing")["found"] is False


def test_labels_layout_rows_have_no_regions():
    template = next(t for t in TEMPLATES if t.form_type == "fabrication")
    boxes = [
        box("PRESENCE PERSONNEL", 700, 500, 900, 520),
        box("Salle de controle", 700, 530, 810, 550), box("Oui", 820, 530, 850, 550),
        box("elabore par", 20, 850, 100, 870),
    ]
    result = extract(template, boxes, 1000, 900)
    staffing = _block(result, "staffing")
    assert staffing["found"] is True
    assert all(row["regions"] == {} for row in staffing["rows"])


def test_a_box_spanning_two_columns_yields_regions_for_both():
    # "12h1812h37"-style glued handwriting: one box straddling the waste table's
    # quantity (x=0.33) and cause (x=0.7) columns.
    glued = CONDITIONNEMENT + [box("15,20kg Nettoyage", 280, 725, 480, 745)]
    template, _ = classify(glued, TEMPLATES)
    result = extract(template, glued, 1000, 900)
    waste = _block(result, "waste")["rows"]
    spanning_row = next(r for r in waste if "15,20kg Nettoyage" in r["cells"].get("quantity", {}).get("text", "")
                         or "15,20kg Nettoyage" in r["cells"].get("cause", {}).get("text", ""))
    assert "quantity" in spanning_row["regions"] and "cause" in spanning_row["regions"]
    qty_lo, qty_y0, qty_hi, qty_y1 = spanning_row["regions"]["quantity"]
    cause_lo, cause_y0, cause_hi, cause_y1 = spanning_row["regions"]["cause"]
    assert qty_hi == cause_lo
    assert qty_y0 == cause_y0 == 725 and qty_y1 == cause_y1 == 745
