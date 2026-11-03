"""The Fiche fabrication par équipe, block by block, into the shift report's sections.

Production rows: a row naming a lot, product or start begins a run; the semoule and
broyage columns of every row are the shift's versements (the report records them once
per shift). "Pâtes non conformes -- Produit fini" is finished product lost, which the
report files on the packing side ("one place per loss").
"""
from __future__ import annotations

from functools import partial

from modules.scan.domain.common import map_header, map_silo, map_stops
from modules.scan.domain.draft import Draft, path, section_path
from modules.scan.domain.ocr_result import PageRead, ReadRow
from modules.scan.domain.text import minutes_between
from modules.scan.domain.vocabulary import resolve

PERSON_FIELDS = ("conducteur", "agent_fabrication")
_RUN_STARTERS = ("lot", "product", "start")


def map_fabrication(page: PageRead, draft: Draft) -> None:
    draft.accept_score = page.accept_score
    map_header(page, draft, PERSON_FIELDS)
    _production(page, draft)
    _waste_petrin(page, draft)
    _waste_finished(page, draft)
    _mold_washes(page, draft)
    _staffing(page, draft)
    map_stops(page, draft, "stops")
    map_silo(page, draft, "production")


def _written(row: ReadRow, *keys: str) -> bool:
    return any(row.cell(key).text.strip() for key in keys)


def _new_run(page: PageRead, draft: Draft, row: ReadRow, ref: str) -> dict:
    at = partial(path, "runs", "runs", ref)
    run = draft.add_row("runs", "runs", ref, {
        "of_id": draft.ctx.default_of_id, "lot_number": None, "start_time": None, "end_time": None,
        "production_minutes": 0, "water_percentage": None, "humidity_percentage": None,
    })
    draft.lot(at("lot_number"), row.cell("lot"), run, "lot_number", check=True)
    start = draft.time(at("start_time"), row.cell("start"))
    end = draft.time(at("end_time"), row.cell("end"))
    run["start_time"] = start.strftime("%H:%M") if start else None
    run["end_time"] = end.strftime("%H:%M") if end else None
    if start and end:
        run["production_minutes"] = minutes_between(start, end)
    product = row.cell("product")
    if product.text.strip():
        # The run's product is its OF's; a product written that is surely another one is worth a look.
        draft.see(at("of_id"), product)
        found = resolve(draft.ctx.vocabulary, draft.ctx.aliases, "finished_product", product.text, prefer=draft.ctx.default_product_id)
        if found.how in ("alias", "exact") and draft.ctx.default_product_id and found.value != draft.ctx.default_product_id:
            draft.flag(at("of_id"), "of_product")
    return run


def _production(page: PageRead, draft: Draft) -> None:
    block = page.block("production")
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("runs"), "rows_disagree")
    run = None
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:production:{index}"
        if run is None or _written(row, *_RUN_STARTERS):
            run = _new_run(page, draft, row, ref)
        run_at = partial(path, "runs", "runs", run["_scan_ref"])
        for field, key in (("water_percentage", "water"), ("humidity_percentage", "humidity")):
            if row.cell(key).text.strip():
                run[field] = draft.percent(run_at(field), row.cell(key))
        if _written(row, "sem_origin", "sem_bags", "sem_tonnes"):
            sem_ref = f"{ref}:sem"
            at = partial(path, "runs", "versements", sem_ref)
            versement = draft.add_row("runs", "versements", sem_ref, {"product_id": None, "quantity": None})
            versement["product_id"] = draft.code(at("product_id"), "raw_material", row.cell("sem_origin"))
            versement["quantity"] = draft.decimal(at("quantity"), row.cell("sem_tonnes"))
        if _written(row, "broy_kg", "broy_bags", "broy_lot"):
            broy_ref = f"{ref}:broy"
            at = partial(path, "runs", "rebroyat_versements", broy_ref)
            kilos = draft.decimal(at("quantity"), row.cell("broy_kg"))
            regrind = draft.ctx.vocabulary.of("regrind_item")
            draft.add_row("runs", "rebroyat_versements", broy_ref, {
                # The fiche names no item; the plant's only rebroyat item when there is exactly one.
                "product_id": regrind[0].value if len(regrind) == 1 else None,
                "quantity": round(kilos / 1000, 6) if kilos is not None else None,
            })


def _waste_line(page: PageRead, draft: Draft, row: ReadRow, section: str, ref: str, kind: str | None) -> dict:
    at = partial(path, section, "waste_lines", ref)
    line = draft.add_row(section, "waste_lines", ref, {"category": None, "quantity": None, "lot_number": None, "occurred_at": None, "note": None})
    cause = row.cell("cause")
    if kind is not None:
        line["category"] = draft.code(at("category"), kind, cause if cause.text.strip() else row.cell("format"))
    line["quantity"] = draft.decimal(at("quantity"), row.cell("quantity"))
    draft.lot(at("lot_number"), row.cell("lot"), line, "lot_number")
    moment = draft.time(at("occurred_at"), row.cell("time"))
    line["occurred_at"] = draft.ctx.at(moment) if moment else None
    line["note"] = draft.text(at("note"), cause)
    return line


def _waste_petrin(page: PageRead, draft: Draft) -> None:
    block = page.block("waste_petrin")
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("waste_production"), "rows_disagree")
    for index, row in enumerate(block.rows):
        if not row.is_blank():
            _waste_line(page, draft, row, "waste_production", f"{page.page_id}:waste_petrin:{index}", "waste_production")


def _waste_finished(page: PageRead, draft: Draft) -> None:
    block = page.block("waste_finished")
    if block is None:
        return
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:waste_finished:{index}"
        line = _waste_line(page, draft, row, "waste_packing", ref, None)
        line["category"] = "product"
        line["product_id"] = draft.code(
            path("waste_packing", "waste_lines", ref, "product_id"), "finished_product", row.cell("format"),
            prefer=draft.ctx.default_product_id,
        )
        draft.fabrication_losses.append(line)


def _mold_washes(page: PageRead, draft: Draft) -> None:
    block = page.block("mold_washes")
    if block is None:
        return
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        ref = f"{page.page_id}:mold_washes:{index}"
        at = partial(path, "waste_production", "mold_washes", ref)
        wash = draft.add_row("waste_production", "mold_washes", ref, {"mold_id": None, "washed_at": None, "state": None})
        wash["mold_id"] = draft.code(at("mold_id"), "mold", row.cell("mold"))
        moment = draft.time(at("washed_at"), row.cell("time"))
        wash["washed_at"] = draft.ctx.at(moment) if moment else None
        wash["state"] = draft.text(at("state"), row.cell("state"))


def _staffing(page: PageRead, draft: Draft) -> None:
    block = page.block("staffing")
    row = next((r for r in block.rows if not r.is_blank()), None) if block else None
    if row is None:
        return
    staffing = draft.single("staffing", "staffing")
    for key in ("control_room", "petrin", "semoule", "broyage"):
        staffing[key] = draft.integer(path("staffing", "staffing", "-", key), row.cell(key))
