from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from core.domain.result import Err, Ok, Result

VALID_REPORT_TYPES = {"daily", "conditionnement"}

# A report is a team's claim about a shift until a supervisor accepts it. Only
# `validated` is official — from Phase 5 it is also the only status that posts
# stock, which is why `draft` and `rejected` have no path to it except back
# through `submitted`.
REPORT_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"validated", "rejected"},
    # Re-opening a rejected report returns it to the team as a fresh revision.
    "rejected": {"draft"},
    "validated": set(),
}


@dataclass(frozen=True)
class ProductionReport:
    id: str
    of_id: str
    report_type: str
    report_date: datetime.date
    status: str
    revision: int
    team: str | None = None
    work_center_id: str | None = None
    # Which physical machine within work_center_id ran this shift. Opaque
    # reference into maintenance.equipment -- a line can carry more than one
    # machine at once, so the line alone cannot tell them apart for productivity
    # reporting. Set at creation only, same as work_center_id/team/shift, and
    # required before a report can be submitted -- see submit_report.
    equipment_id: str | None = None
    shift: str | None = None
    created_by: str | None = None
    submitted_at: datetime.datetime | None = None
    validated_by: str | None = None
    validated_at: datetime.datetime | None = None
    rejection_reason: str | None = None


# Where in the process material was lost. A closed set, because these are the
# stages the plant's own form names and the OF consolidation groups by; free text
# would let one typo split a category in two without anyone noticing.
#
# `raw_material`, `press`, `pouring`, `cross` (the plant's own name for what was
# briefly called "cutting"/découpe), `kneading` (pétrin) and
# `finished_product_conditioning` (PF cdt) are daily-report stages, `product` and
# `packaging` packing-report stages, and `WASTE_CATEGORIES_BY_REPORT_TYPE` is what
# enforces that -- a packing report cannot claim semoule was spilt before the press.
WASTE_CATEGORIES = (
    "raw_material",
    "press",
    "pouring",
    "cross",
    "kneading",
    "finished_product_conditioning",
    "product",
    "packaging",
)

WASTE_CATEGORIES_BY_REPORT_TYPE = {
    "daily": ("raw_material", "press", "pouring", "cross", "kneading", "finished_product_conditioning"),
    "conditionnement": ("product", "packaging"),
}


@dataclass(frozen=True)
class WasteLine:
    """One kind of waste on one report.

    Naming the product is the whole point: a category has no unit, an item does.
    "Déchet emballage 5" is unreadable; "Scotch 5 pièces" is a fact.

    A waste line moves no stock. The material was already deducted when it was
    poured or consumed, and the finished product only ever enters stock at the
    good quantity -- so a line records what was lost, never a second withdrawal.
    """

    category: str
    product_id: str | None = None
    quantity: float = 0
    note: str | None = None
    # Only ever the order the shift typed them in. Nothing is derived from it.
    line_order: int = 0


@dataclass(frozen=True)
class DowntimeLine:
    """One stoppage on one report.

    A shift can stop more than once for more than one reason, so this is a list
    rather than a `downtime_minutes`/`downtime_reason` pair -- the same move
    `report_waste_lines` already made for déchets.
    """

    motif: str | None = None
    minutes: int = 0
    note: str | None = None
    # Only ever the order the shift typed them in. Nothing is derived from it.
    line_order: int = 0


@dataclass(frozen=True)
class SemolinaLine:
    """One quality of semoule poured into one report.

    The plant runs more than one quality (semoule extra, semoule courante, and
    so on) and a shift can pour a mix of them, so this is a list rather than a
    column, the same move `report_waste_lines` already made for déchets.

    Unlike rebroyat, which still shares the report's one `raw_material_location_id`,
    each line names its own store: different qualities are routinely kept in
    different silos, and a report-wide location would force a lie onto whichever
    quality wasn't stored there.
    """

    product_id: str | None = None
    quantity: float = 0
    location_id: str | None = None
    # Only ever the order the shift typed them in. Nothing is derived from it.
    line_order: int = 0


@dataclass(frozen=True)
class DailyReportDetail:
    dough_quantity: float = 0
    # Feeds yield and consolidation only — see the migration comment; it posts no stock.
    finished_product_quantity: float = 0
    regrind_quantity: float = 0
    # The stored litre figure -- every downstream reader (consolidation, the
    # cockpit) expects this. The frontend derives it from water_percentage
    # rather than the operator typing a meter reading, because the plant doses
    # water as a percentage of the semoule poured, not in litres.
    water_quantity: float = 0
    # The operator's real input: water dosed as a percentage of the semoule
    # poured this shift. 0 means "not entered." Recorded for future recipe
    # statistics too -- see PRODUCTION_RECIPE_STATISTICS_PLAN.md.
    water_percentage: float = 0
    fuel_quantity: float = 0
    # Which fournisseur this shift's fioul came from. Fuel is never posted to
    # stock (see the daily_reports migration comment), so this is informational
    # only -- there is no lot or purchase order behind it, just the plant's own
    # record of who delivered it, because more than one supplier can deliver it.
    fuel_supplier_id: str | None = None
    # Gasoil (diesel) -- a separate fuel from fuel_quantity (fioul), tracked
    # alongside it rather than folded into it.
    gasoil_quantity: float = 0
    # Same informational purpose as fuel_supplier_id, for gasoil's own fournisseur.
    gasoil_supplier_id: str | None = None
    electricity_quantity: float = 0
    # Débit de semoule: how fast semoule was fed into the line, tonnes/hour.
    # Recorded only, for the same future statistics.
    semolina_flow_rate: float = 0
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None
    production_minutes: int = 0
    # Arrêts. A list rather than a minutes/reason pair, so a shift can record
    # more than one stoppage and more than one reason -- see DowntimeLine.
    downtime_lines: tuple[DowntimeLine, ...] = ()
    # Semoule poured into this shift, one line per quality. Each line leaves
    # stock on validation, from its own location.
    semolina_lines: tuple[SemolinaLine, ...] = ()
    # Rebroyat's own store. Kept separate from the semoule lines' locations
    # because rebroyat is deliberately not a list — see regrind_input_product_id.
    raw_material_location_id: str | None = None
    # Rebroyat poured back into the mix. A raw material like any other: it leaves
    # stock on validation. Distinct from regrind_quantity, which is what this
    # shift *produced* as rebroyat. Stays a single field, unlike semoule: there is
    # only ever one rebroyat product tenant-wide (see regrind_service.py), so a
    # list would have nothing to enumerate.
    regrind_input_quantity: float = 0
    regrind_input_product_id: str | None = None
    # Informational only: the scrap record _record_regrind_scrap opens for this
    # figure always uses the tenant's one rebroyat product (production.regrind_
    # defaults, input_product_id IS NULL), never this field -- letting a report
    # name a different product here used to be how a purchased raw material's
    # identity (and its own unit, e.g. tonnes) ended up on a rebroyat scrap
    # record meant to be weighed in kg. Kept only for the OF-consolidation
    # display (of_consolidation_service.py).
    regrind_product_id: str | None = None
    # Which mold this shift ran. Named per report, not on the OF: an order can
    # span several shifts and several molds over its life.
    mold_id: str | None = None
    # Déchets. A list rather than a column per category, so a shift can record
    # scotch, or two kinds of film, or nothing at all.
    waste_lines: tuple[WasteLine, ...] = ()


@dataclass(frozen=True)
class ConditionnementReportDetail:
    # Phase 9, decision 17. Two figures, because this column was carrying two
    # meanings: `finished_product_quantity` is the tonnage off the scale, which
    # feeds yield and consolidation, and `packets_counted` is what the line
    # tallied -- and from decision 18 the tally, not the tonnage, is what
    # validation posts into stock.
    finished_product_quantity: float = 0
    packets_counted: float = 0
    film_quantity: float = 0
    carton_quantity: float = 0
    tape_quantity: float = 0
    machine_speed: float | None = None
    production_minutes: int = 0
    downtime_minutes: int = 0
    downtime_reason: str | None = None
    lot_number: str | None = None
    dlc_date: datetime.date | None = None
    # Which packaging products these figures consume, and the stores involved. The
    # finished product is the OF's own product and is deliberately not repeated.
    film_product_id: str | None = None
    carton_product_id: str | None = None
    tape_product_id: str | None = None
    # Which fournisseur each packaging item came from. Informational only, like
    # fuel/gasoil_supplier_id on the daily report: film, carton and ruban can each
    # come from more than one supplier, and stock itself does not split by
    # supplier, so this is the report's own record of who delivered the batch
    # actually consumed rather than a stock lot reference.
    film_supplier_id: str | None = None
    carton_supplier_id: str | None = None
    tape_supplier_id: str | None = None
    packaging_location_id: str | None = None
    finished_goods_location_id: str | None = None
    # The daily report whose output this run packaged. Always optional: a team
    # may file conditionnement before that day's daily report exists, or
    # package previously stored product with no same-shift daily report at
    # all. Not a stock target -- it powers traceability (qc's inspection hint)
    # rather than gating what can be posted.
    daily_report_id: str | None = None
    waste_lines: tuple[WasteLine, ...] = ()


DAILY_QUANTITY_FIELDS = (
    "regrind_input_quantity",
    "dough_quantity",
    "finished_product_quantity",
    "regrind_quantity",
    "water_quantity",
    "water_percentage",
    "fuel_quantity",
    "gasoil_quantity",
    "electricity_quantity",
    "semolina_flow_rate",
)


def validate_semolina_lines(lines: tuple[SemolinaLine, ...]) -> Result[None]:
    """Check a report's semoule list.

    A negative quantity is not a pour, it is a typo. Naming the quality is *not*
    required here — only at submit, alongside the other stock targets — so a
    team can still save a half-typed draft.

    The same product may appear twice on purpose: two separate pours of the same
    quality, poured at different points in the shift, are two events. The
    consolidation sums them, so nothing downstream cares.
    """
    for line in lines:
        if line.quantity < 0:
            return Err("INVALID_QUANTITY", "a semolina quantity cannot be negative")
    return Ok(None)


def validate_waste_lines(lines: tuple[WasteLine, ...], *, report_type: str) -> Result[None]:
    """Check a report's déchet list.

    Two rules here, and one deliberately absent:

    * a category the report type does not have is refused outright -- a packing
      report claiming semoule was spilt at the press describes a stage it never
      ran, and would land in the OF's raw-material total;
    * a negative quantity is not waste, it is a typo;
    * naming the item is *not* required here. It is required to submit, alongside
      the stock targets, so a team can still save a half-typed draft.

    The same item may appear twice in one category on purpose: two spills of the
    same film at different hours are two events, and merging them would lose the
    notes that tell them apart. The consolidation sums them, so nothing
    downstream cares.
    """
    allowed = WASTE_CATEGORIES_BY_REPORT_TYPE.get(report_type)
    if allowed is None:
        return Err("INVALID_REPORT_TYPE", f"report_type must be one of {sorted(VALID_REPORT_TYPES)}")

    for line in lines:
        if line.category not in allowed:
            return Err(
                "INVALID_WASTE_CATEGORY",
                f"a {report_type} report has no {line.category!r} waste; expected one of {list(allowed)}",
            )
        if line.quantity < 0:
            return Err("INVALID_QUANTITY", "a waste quantity cannot be negative")
    return Ok(None)


def validate_downtime_lines(lines: tuple[DowntimeLine, ...]) -> Result[None]:
    """Check a report's arrêt list.

    Each line keeps the same strictness the single field used to have: a
    stoppage of zero minutes is not a stoppage, and one with minutes but no
    motif cannot be judged by whoever reads the report later.
    """
    for line in lines:
        if line.minutes < 0:
            return Err("INVALID_DURATION", "a downtime line cannot have negative minutes")
        if line.minutes > 0 and not (line.motif or "").strip():
            return Err("MISSING_DOWNTIME_REASON", "a downtime line needs a motif when it records minutes")
    return Ok(None)


def downtime_total_minutes(lines: tuple[DowntimeLine, ...]) -> int:
    """Total minutes lost across every arrêt on the report."""
    return sum(line.minutes for line in lines)


def waste_total_by_category(lines: tuple[WasteLine, ...]) -> dict[str, float]:
    """Waste per stage, for the categories this set of lines actually used.

    Deliberately not a total across categories: those quantities are in whatever
    unit each item is stocked in, and adding kilos of dough to counts of cartons
    produces a number that means nothing.
    """
    totals: dict[str, float] = {}
    for line in lines:
        totals[line.category] = totals.get(line.category, 0.0) + line.quantity
    return totals


def transition_report(report: ProductionReport, new_status: str) -> Result[ProductionReport]:
    if new_status not in REPORT_TRANSITIONS.get(report.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move report from {report.status} to {new_status}")
    return Ok(replace(report, status=new_status))


def validate_daily_detail(detail: DailyReportDetail) -> Result[None]:
    """Check a daily report's figures for internal sense.

    Deliberately permissive about the plant's reality: a shift that produced
    nothing is a legitimate report, and a raw-material shortfall never blocks
    anything here — the report records what physically happened.
    """
    for field in DAILY_QUANTITY_FIELDS:
        if getattr(detail, field) < 0:
            return Err("INVALID_QUANTITY", f"{field} cannot be negative")
    if detail.water_percentage > 100:
        return Err("INVALID_QUANTITY", "water_percentage cannot exceed 100")
    if detail.production_minutes < 0:
        return Err("INVALID_DURATION", "production_minutes cannot be negative")
    if detail.start_time is not None and detail.end_time is not None and detail.end_time < detail.start_time:
        # A shift crossing midnight is real, but it is entered as two reports —
        # one per report_date — so within one report the end never precedes the start.
        return Err("INVALID_TIME_RANGE", "end_time cannot be before start_time")
    downtime_check = validate_downtime_lines(detail.downtime_lines)
    if isinstance(downtime_check, Err):
        return downtime_check
    semolina_check = validate_semolina_lines(detail.semolina_lines)
    if isinstance(semolina_check, Err):
        return semolina_check
    return validate_waste_lines(detail.waste_lines, report_type="daily")


CONDITIONNEMENT_QUANTITY_FIELDS = (
    "finished_product_quantity",
    "packets_counted",
    "film_quantity",
    "carton_quantity",
    "tape_quantity",
)


def validate_conditionnement_detail(detail: ConditionnementReportDetail) -> Result[None]:
    """Check a packing report's figures for internal sense.

    As permissive as the daily report about what the plant reports — a shift that
    packed nothing is legitimate — but a DLC needs both halves: a lot number
    without an expiry date, or the reverse, cannot become a usable lot.
    """
    for field in CONDITIONNEMENT_QUANTITY_FIELDS:
        if getattr(detail, field) < 0:
            return Err("INVALID_QUANTITY", f"{field} cannot be negative")
    if detail.machine_speed is not None and detail.machine_speed < 0:
        return Err("INVALID_QUANTITY", "machine_speed cannot be negative")
    if detail.production_minutes < 0:
        return Err("INVALID_DURATION", "production_minutes cannot be negative")
    if detail.downtime_minutes < 0:
        return Err("INVALID_DURATION", "downtime_minutes cannot be negative")
    if detail.downtime_minutes > 0 and not (detail.downtime_reason or "").strip():
        return Err("MISSING_DOWNTIME_REASON", "a downtime reason is required when downtime minutes are recorded")

    has_lot = bool((detail.lot_number or "").strip())
    if has_lot != (detail.dlc_date is not None):
        return Err("INCOMPLETE_DLC", "a lot number and its DLC date must be given together")
    return validate_waste_lines(detail.waste_lines, report_type="conditionnement")


def validate_daily_stock_targets(detail: DailyReportDetail) -> Result[None]:
    """Everything a daily report needs before it can post stock.

    Kept separate from `validate_daily_detail` on purpose: a team must be able to
    save a half-finished draft, so completeness is only demanded when the report
    leaves them for the validation desk.
    """
    for line in detail.semolina_lines:
        if line.quantity <= 0:
            continue
        if not (line.product_id or "").strip():
            return Err("MISSING_STOCK_TARGET", "each semolina line must name the product it consumed")
        if not (line.location_id or "").strip():
            return Err("MISSING_STOCK_TARGET", "each semolina line must name the store it came out of")
    if detail.regrind_input_quantity > 0:
        if not (detail.regrind_input_product_id or "").strip():
            return Err("MISSING_STOCK_TARGET", "the rebroyat poured in must name the product it consumed")
        if not (detail.raw_material_location_id or "").strip():
            return Err("MISSING_STOCK_TARGET", "the rebroyat poured in must name the store it came out of")
    return validate_waste_products(detail.waste_lines)


def validate_waste_products(lines: tuple[WasteLine, ...]) -> Result[None]:
    """Every déchet figure on a submitted report has to say what it is.

    Held back from `validate_waste_lines` for the same reason the stock targets
    are: a team saving a half-typed draft should not be stopped, but a report
    arriving at the validation desk with an unlabelled quantity cannot be judged
    -- the validator has no way to know whether 5 is five kilos or five packets.
    """
    for line in lines:
        if line.quantity > 0 and not (line.product_id or "").strip():
            return Err("MISSING_WASTE_PRODUCT", "a waste line must name the item that was lost")
    return Ok(None)


def validate_conditionnement_stock_targets(detail: ConditionnementReportDetail) -> Result[None]:
    """Everything a conditionnement report needs before it can post stock."""
    # Keyed to the tally rather than the tonnage since decision 18: the packets
    # are what move, so they are what need somewhere to move to. A report with a
    # tonnage and no packets posts no finished product and needs no store -- the
    # ecart is what makes that visible, not a refusal here.
    if detail.packets_counted > 0 and not (detail.finished_goods_location_id or "").strip():
        return Err("MISSING_STOCK_TARGET", "the finished product must name the store it goes into")

    for quantity_field, product_field, label in (
        ("film_quantity", "film_product_id", "film"),
        ("carton_quantity", "carton_product_id", "carton"),
        ("tape_quantity", "tape_product_id", "tape"),
    ):
        if getattr(detail, quantity_field) > 0:
            if not (getattr(detail, product_field) or "").strip():
                return Err("MISSING_STOCK_TARGET", f"the {label} figure must name the product it consumed")
            if not (detail.packaging_location_id or "").strip():
                return Err("MISSING_STOCK_TARGET", "packaging figures must name the store they came out of")
    return validate_waste_products(detail.waste_lines)


def validate_report_header(*, report_type: str, of_id: str) -> Result[None]:
    if report_type not in VALID_REPORT_TYPES:
        return Err("INVALID_REPORT_TYPE", f"report_type must be one of {sorted(VALID_REPORT_TYPES)}")
    if not of_id.strip():
        return Err("MISSING_OF", "a report must belong to a work order")
    return Ok(None)
