"""The day sheet: one line's Daily and Conditionnement reports on a single grid.

It mirrors the plant's Excel day sheet: sections Consommation MP -> Production ->
Déchets -> Conditionnement -> Énergie, one column per shift plus a total. The
month recap is the same grid with one column per product instead, so nothing
here knows what a column stands for -- a report only says which column it falls
in.

Everything is added up in the units the Excel prints (tonnes of semoule and of
finished product, litres of water and fuel, kilos of déchet), which the caller
restates each figure into before it gets here. A cell nobody reported on stays
absent rather than 0: "no report for that shift" and "reported 0" are different
facts, and the sheet shows them differently.
"""
from __future__ import annotations

from dataclasses import dataclass, field

KG_PER_TONNE = 1000.0

# The order the sheet prints its sections in.
SECTIONS = ("material", "production", "waste", "packing", "energy")


@dataclass
class SheetRow:
    section: str
    key: str
    # What a screen calls the row: a product, or a déchet kind, for the rows that
    # exist once per product/kind; the fixed rows are named by `key` alone.
    ref: str | None = None
    name: str | None = None
    unit: str | None = None
    by_column: dict[str, float] = field(default_factory=dict)
    # A ratio's total is not the sum of its cells (kilos an hour over the day is
    # the day's kilos over the day's hours), so it is set outright -- including to
    # None, when there is nothing to divide.
    fixed_total: float | None = None
    total_is_fixed: bool = False

    def add(self, column: str, value: float) -> None:
        self.by_column[column] = self.by_column.get(column, 0.0) + value

    @property
    def total(self) -> float | None:
        if self.total_is_fixed:
            return self.fixed_total
        return sum(self.by_column.values()) if self.by_column else None

    def to_dict(self) -> dict:
        return {
            "section": self.section,
            "key": self.key,
            "ref": self.ref,
            "name": self.name,
            "unit": self.unit,
            "by_column": self.by_column,
            "total": self.total,
        }


@dataclass(frozen=True)
class DailyFact:
    """One Daily report, its figures already in the sheet's units."""

    column: str
    water_l: float = 0.0
    production_minutes: float = 0.0
    downtime_minutes: float = 0.0
    regrind_t: float = 0.0
    fuel_l: float = 0.0
    gasoil_l: float = 0.0
    electricity_kwh: float = 0.0
    generator_hours: float = 0.0
    # (product id, product name, tonnes) per quality poured.
    semolina: tuple[tuple[str | None, str | None, float], ...] = ()
    # (category, kilos) -- the daily form records déchet in raw kilos.
    waste_kg: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class PackingFact:
    """One Conditionnement report, its figures already in the sheet's units."""

    column: str
    product_id: str | None = None
    product_name: str | None = None
    finished_t: float = 0.0
    packets: float = 0.0
    film: float = 0.0
    carton: float = 0.0
    waste_carton: float = 0.0
    scotch: float = 0.0
    ruban: float = 0.0
    # (category, product id, product name, quantity in `unit`, unit)
    waste: tuple[tuple[str, str | None, str | None, float, str | None], ...] = ()


def _percent(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole or whole <= 0:
        return None
    return part / whole * 100


def build_rows(
    daily: list[DailyFact],
    packing: list[PackingFact],
    *,
    packaging_units: dict[str, str | None] | None = None,
    yield_by_column: bool = False,
) -> list[SheetRow]:
    """The sheet's rows in print order.

    `packaging_units` names the unit each packaging row is in (film, carton,
    scotch, ruban) -- the caller restated every report's quantity into it.

    The yield is what was conditioned over what went into fabrication. Read per
    column it only means something when a column holds a whole run, as a product's
    column does on the month recap: a shift's packing lags its production, so one
    shift's tonnes conditioned are not that shift's tonnes fabricated. The day
    sheet therefore asks for the total only (`yield_by_column=False`).
    """
    units = packaging_units or {}

    semolina: dict[str | None, SheetRow] = {}
    total_mp = SheetRow("material", "total_mp", unit="T")
    regrind = SheetRow("material", "regrind", unit="T")
    total_fab = SheetRow("material", "total_fab", unit="T")
    water = SheetRow("production", "water", unit="l")
    production_hours = SheetRow("production", "production_hours", unit="h")
    downtime_hours = SheetRow("production", "downtime_hours", unit="h")
    hourly_output = SheetRow("production", "hourly_output", unit="kg/h")
    waste: dict[str, SheetRow] = {}
    total_waste = SheetRow("waste", "total_waste", unit="kg")
    electricity = SheetRow("energy", "electricity", unit="kWh")
    fuel = SheetRow("energy", "fuel", unit="l")
    gasoil = SheetRow("energy", "gasoil", unit="l")
    generator_hours = SheetRow("energy", "generator_hours", unit="h")

    for fact in daily:
        column = fact.column
        # Every report puts a cell in each row it fills in, even a 0: the
        # column then reads as "reported nothing", not as "no report".
        for row, value in (
            (total_mp, 0.0),
            (regrind, fact.regrind_t),
            (water, fact.water_l),
            (production_hours, fact.production_minutes / 60),
            (downtime_hours, fact.downtime_minutes / 60),
            (total_waste, 0.0),
            (electricity, fact.electricity_kwh),
            (fuel, fact.fuel_l),
            (gasoil, fact.gasoil_l),
            (generator_hours, fact.generator_hours),
        ):
            row.add(column, value)
        for product_id, name, tonnes in fact.semolina:
            row = semolina.setdefault(product_id, SheetRow("material", "semolina", ref=product_id, name=name, unit="T"))
            row.add(column, tonnes)
            total_mp.add(column, tonnes)
        for category, kilos in fact.waste_kg:
            waste.setdefault(category, SheetRow("waste", "waste", ref=category, unit="kg")).add(column, kilos)
            total_waste.add(column, kilos)

    for column, value in total_mp.by_column.items():
        total_fab.add(column, value + regrind.by_column.get(column, 0.0))

    # Kilos an hour, per column and for the whole sheet. A column with no hours
    # worked has no rate, and the sheet says so rather than dividing by zero.
    for column, hours in production_hours.by_column.items():
        if hours > 0 and column in total_fab.by_column:
            hourly_output.by_column[column] = total_fab.by_column[column] * KG_PER_TONNE / hours
    total_hours, total_material = production_hours.total, total_fab.total
    hourly_output.total_is_fixed = True
    if total_hours and total_hours > 0 and total_material is not None:
        hourly_output.fixed_total = total_material * KG_PER_TONNE / total_hours

    finished: dict[str | None, SheetRow] = {}
    total_finished = SheetRow("packing", "total_finished", unit="T")
    yield_row = SheetRow("packing", "yield", unit="%", total_is_fixed=True)
    packets = SheetRow("packing", "packets", unit="ea")
    film = SheetRow("packing", "film", unit=units.get("film"))
    carton = SheetRow("packing", "carton", unit=units.get("carton"))
    waste_carton = SheetRow("packing", "waste_carton", unit=units.get("carton"))
    scotch = SheetRow("packing", "scotch", unit=units.get("scotch"))
    ruban = SheetRow("packing", "ruban", unit=units.get("ruban"))
    packing_waste: dict[tuple[str, str | None], SheetRow] = {}

    for fact in packing:
        column = fact.column
        row = finished.setdefault(
            fact.product_id, SheetRow("packing", "finished", ref=fact.product_id, name=fact.product_name, unit="T")
        )
        row.add(column, fact.finished_t)
        for target, value in (
            (total_finished, fact.finished_t),
            (packets, fact.packets),
            (film, fact.film),
            (carton, fact.carton),
            (waste_carton, fact.waste_carton),
            (scotch, fact.scotch),
            (ruban, fact.ruban),
        ):
            target.add(column, value)
        for category, product_id, name, quantity, unit in fact.waste:
            packing_waste.setdefault(
                (category, product_id), SheetRow("packing", "packing_waste", ref=category, name=name, unit=unit)
            ).add(column, quantity)

    yield_row.fixed_total = _percent(total_finished.total, total_fab.total)
    if yield_by_column:
        for column, tonnes in total_finished.by_column.items():
            share = _percent(tonnes, total_fab.by_column.get(column))
            if share is not None:
                yield_row.by_column[column] = share

    # A finished product's own row is named by the product; keep the rows of one
    # kind together and stable, largest first, so the sheet does not reshuffle
    # from one day to the next as quantities change.
    def ranked(rows) -> list[SheetRow]:
        return sorted(rows, key=lambda r: (-(r.total or 0.0), r.name or "", r.ref or ""))

    rows: list[SheetRow] = [
        *ranked(semolina.values()),
        total_mp,
        regrind,
        total_fab,
        water,
        production_hours,
        downtime_hours,
        hourly_output,
        *sorted(waste.values(), key=lambda r: r.ref or ""),
        total_waste,
        *ranked(finished.values()),
        total_finished,
        yield_row,
        packets,
        film,
        carton,
        waste_carton,
        scotch,
        ruban,
        *ranked(packing_waste.values()),
        electricity,
        fuel,
        gasoil,
        generator_hours,
    ]
    # The per-product and per-kind rows only exist once something was reported;
    # the fixed ones are printed whatever happened.
    return [r for r in rows if r.by_column or r.key in _ALWAYS]


# The rows every sheet prints, even with nothing behind them, so the layout
# stays the Excel's whatever was reported.
_ALWAYS = frozenset(
    {
        "total_mp", "regrind", "total_fab",
        "water", "production_hours", "downtime_hours", "hourly_output",
        "total_waste",
        "total_finished", "yield", "packets", "film", "carton", "waste_carton", "scotch", "ruban",
        "electricity", "fuel", "gasoil", "generator_hours",
    }
)
