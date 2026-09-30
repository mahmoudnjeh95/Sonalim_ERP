"""The client's example fiches (07/09/2026, line PC, team D) as the OCR would return them.

Transcribed from the photos, with the workers' names replaced: the photos themselves
are never committed. Used by the domain tests only.
"""
from __future__ import annotations

import datetime

from modules.scan.domain.draft import ProposalContext
from modules.scan.domain.ocr_result import PageRead, ReadBlock, ReadCell, ReadRow
from modules.scan.domain.vocabulary import Term, Vocabulary

VOCABULARY = Vocabulary({
    "finished_product": (Term("P-VERM", ("Vermicelle 500g PC", "PF-VERM-500"), {"net_weight_grams": 500}),),
    "raw_material": (Term("MP-SSSE", ("Semoule SSSE", "MP-SSSE")),),
    "regrind_item": (Term("RB-PC", ("Rebroyat PC",)),),
    "film_item": (Term("FILM-ACT", ("Film Active PC 390mm",)),),
    "waste_production": (Term("press", ("Presse",)), Term("raw_material", ("Matière",)), Term("kneading", ("Pétrin",))),
    "waste_packing": (Term("product", ("Produit",)), Term("packaging", ("Emballage",))),
    "line_state": (Term("running", ("En marche", "Marche")), Term("stopped", ("En arrêt", "Arrêt"))),
    "check_state": (Term("good", ("Bon", "B", "OK", "Conforme")), Term("not_good", ("Non bon", "NB", "Non conforme"))),
    "team": (Term("Equipe D", ("Equipe D",), {"letter": "D"}), Term("Equipe A", ("Equipe A",), {"letter": "A"})),
    "downtime_motif": (Term("electrical_failure", ("electrical_failure",)),),
    "equipment": (),
    "mold": (),
})


def context(**overrides) -> ProposalContext:
    values = dict(
        report_date=datetime.date(2026, 9, 7),
        shift_start=datetime.time(7, 0),
        shift_end=datetime.time(15, 0),
        team="Equipe D",
        default_of_id="OF1",
        default_product_id="P-VERM",
        vocabulary=VOCABULARY,
        aliases={("raw_material", "bsk1"): "MP-SSSE"},
    )
    values.update(overrides)
    return ProposalContext(**values)


def make_page(page_id: str, form_type: str | None, header: dict, blocks: dict, confidence: float = 0.9) -> PageRead:
    def cell(text: str) -> ReadCell:
        return ReadCell(text, confidence, (0.1, 0.1, 0.2, 0.2), page_id)

    return PageRead(
        page_id=page_id,
        form_type=form_type,
        rotation=0,
        header={key: cell(value) for key, value in header.items()},
        blocks={
            key: ReadBlock(key, True, tuple(ReadRow({k: cell(v) for k, v in row.items()}) for row in rows))
            for key, rows in blocks.items()
        },
        accept_score=0.5,
    )


def fabrication_page(page_id: str = "FAB") -> PageRead:
    return make_page(
        page_id,
        "fabrication",
        {"date": "Le07/09/2026", "team_hours": "D 07 H à 14H00", "line_pc": "x", "conducteur": "Conducteur Un", "agent_fabrication": "Agent Deux"},
        {
            "production": [
                {"lot": "D6249SNL", "product": "Vermicelle", "start": "07h00", "sem_origin": "BSK1", "sem_bags": "65",
                 "sem_tonnes": "3,25", "water": "28,9", "humidity": "9,83"},
                {"sem_origin": "B05I", "sem_bags": "66", "sem_tonnes": "3,3"},
            ],
            "waste_petrin": [
                {"time": "14h", "format": "Ver", "lot": "D6249", "quantity": "1,47", "cause": "Déchet Presse"},
                {"time": "14h", "format": "semoule", "lot": "D6249", "quantity": "05", "cause": "Déchet semoule"},
            ],
            "waste_finished": [{"time": "14h", "format": "Ver", "lot": "D6249", "quantity": "75,25", "cause": "A Broyer"}],
            "stops": [
                {"panne": "Démarrage de la production à 09h27mn"},
                {"panne": "Alarme silo à reprises 10h43-10h53, 12h56-12h58"},
                {"panne": "coupure sur l'EDM", "start": "12h18", "end": "12h37", "action": "Production sur GE"},
            ],
            "silo_start": [{"format": "Vermicelle", "lot": "D6249SNL", "level": "0 %", "line_state": "En Arrêt"}],
            "silo_end": [{"format": "Vermicelle", "lot": "D6249SNL", "level": "29 %", "line_state": "En Marche"}],
        },
    )


def conditionnement_page(page_id: str = "COND") -> PageRead:
    return make_page(
        page_id,
        "conditionnement",
        {"date": "07/09/26", "team_hours": "D 07H à 14H", "line_pc": "x", "machiniste": "Machiniste Trois", "aide_machiniste": "Aide Quatre"},
        {
            "silo_start": [{"format": "Vermicelles", "lot": "D6249SNL", "level": "20 %", "line_state": "En Arrêt"}],
            "silo_end": [{"format": "Vermicelles", "lot": "D6249SNL", "level": "29 %", "line_state": "En Marche"}],
            "packing": [
                {"format": "Vermicelles", "lot": "D6249SNL", "fab_date": "07-09-26", "pack_type": "(500g)",
                 "film_type": "Active", "cartons": "|", "bobine": "|", "scotch": "-"},
            ],
            "waste": [
                {"time": "07H14", "type": "Produits finis", "quantity": "02,46kg", "cause": "Nettoyage de la Machine"},
                {"type": "Films Déchet C1", "quantity": "0,35Kg", "cause": "Réglage de Machine"},
                {"type": "Films Déchet C2", "quantity": "0,23Kg"},
                {"type": "Carton Déchets", "quantity": "00", "cause": "Sale"},
                {"type": "Broyage", "quantity": "75,28Kg", "cause": "Produit non Conforme"},
            ],
        },
    )


def bobines_page(page_id: str = "BOB") -> PageRead:
    return make_page(
        page_id,
        "bobines",
        {},
        {"changes": [{"date": "07/09/26", "team": "A", "hours": "14H23H", "machine": "C1", "reel_weight": "87,00", "core_weight": "0,63"}]},
    )
