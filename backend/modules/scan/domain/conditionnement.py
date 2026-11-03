"""The Fiche conditionnement par équipe, block by block, into the shift report's sections."""
from __future__ import annotations

from functools import partial

from modules.scan.domain.common import map_header, map_silo, map_stops
from modules.scan.domain.draft import Draft, path, section_path
from modules.scan.domain.ocr_result import PageRead
from modules.scan.domain.text import first_number, parse_decimal

PERSON_FIELDS = ("machiniste", "aide_machiniste")
_QUANTITIES = (("carton_quantity", "cartons"), ("tape_quantity", "bobine"), ("scotch_quantity", "scotch"), ("ruban_quantity", "ruban"))
_CHECKS = (("film_state", "film"), ("long_weld", "long_weld"), ("vertical_weld", "vert_weld"), ("date_print", "date_print"))


def map_conditionnement(page: PageRead, draft: Draft) -> None:
    draft.accept_score = page.accept_score
    map_header(page, draft, PERSON_FIELDS)
    map_silo(page, draft, "packing")
    _packing(page, draft)
    _packet_checks(page, draft)
    _waste(page, draft)
    map_stops(page, draft, "stops")


def _packing(page: PageRead, draft: Draft) -> None:
    block = page.block("packing")
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("packing"), "rows_disagree")
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:packing:{index}"
        at = partial(path, "packing", "rows", ref)
        line = draft.add_row("packing", "rows", ref, {
            "product_id": None, "of_id": draft.ctx.default_of_id, "lot_number": None, "film_product_id": None,
            "carton_quantity": None, "tape_quantity": None, "scotch_quantity": None, "ruban_quantity": None,
        })
        line["product_id"] = draft.code(at("product_id"), "finished_product", row.cell("format"), prefer=draft.ctx.default_product_id)
        draft.lot(at("lot_number"), row.cell("lot"), line, "lot_number", check=True)
        made = draft.date(at("lot_number"), row.cell("fab_date"))
        if made is not None and made != draft.ctx.report_date:
            draft.flag(at("lot_number"), "fab_date", made.isoformat())
        grams = first_number(row.cell("pack_type").text)
        weight = draft.ctx.vocabulary.attr("finished_product", line["product_id"], "net_weight_grams") if line["product_id"] else None
        if grams is not None and weight and float(weight) != grams:
            draft.flag(at("product_id"), "format_mismatch", f"{grams:g} g")
        line["film_product_id"] = draft.code(at("film_product_id"), "film_item", row.cell("film_type"))
        for field, key in _QUANTITIES:
            line[field] = draft.decimal(at(field), row.cell(key))


def _packet_checks(page: PageRead, draft: Draft) -> None:
    block = page.block("packet_checks")
    if block is None:
        return
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:packet_checks:{index}"
        at = partial(path, "packet_checks", "checks", ref)
        check = draft.add_row("packet_checks", "checks", ref, {})
        moment = draft.time(at("checked_at"), row.cell("time"))
        check["checked_at"] = draft.ctx.at(moment) if moment else None
        for field, key in _CHECKS:
            check[field] = draft.code(at(field), "check_state", row.cell(key))
        check["packet_weight_grams"] = draft.decimal(at("packet_weight_grams"), row.cell("weight"))
        check["note"] = draft.text(at("note"), row.cell("observation"))


def _waste(page: PageRead, draft: Draft) -> None:
    block = page.block("waste")
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("waste_packing"), "rows_disagree")
    for index, row in enumerate(block.rows):
        if row.is_blank() or parse_decimal(row.cell("quantity").text).value == 0:
            continue  # "00" on the fiche: nothing was lost
        ref = f"{page.page_id}:waste:{index}"
        at = partial(path, "waste_packing", "waste_lines", ref)
        line = draft.add_row("waste_packing", "waste_lines", ref, {"category": None, "quantity": None, "occurred_at": None, "note": None, "product_id": None})
        kind_cell = row.cell("type") if row.cell("type").text.strip() else row.cell("cause")
        line["category"] = draft.code(at("category"), "waste_packing", kind_cell)
        line["quantity"] = draft.decimal(at("quantity"), row.cell("quantity"))
        moment = draft.time(at("occurred_at"), row.cell("time"))
        line["occurred_at"] = draft.ctx.at(moment) if moment else None
        line["note"] = draft.text(at("note"), row.cell("cause"))
        if line["category"] == "product":
            line["product_id"] = draft.ctx.default_product_id
