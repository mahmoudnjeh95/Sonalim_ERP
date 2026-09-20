"""The ecart between what a tonnage should have packed and what was counted.

Phase 9, decisions 17-22. Two ecarts come out of here and they are the same
arithmetic with one term switched on:

* **Ecart de conditionnement** -- the estimate against the packets the line
  tallied, with no quality adjustment. It is complete the moment a report is
  validated, which is exactly why it is the one shown at the validation desk: it
  catches a mis-weigh or a miscount while the shift is still fresh.
* **Ecart net** -- the same, less what quality has taken off the market
  (decision 21). Shown on the OF and in the finished-goods warehouse, because
  non-conformities are usually raised days after the run.

Neither blocks anything. Phase 7 established that quality findings arrive after
production is over, so a blocking check here would fire on data that is not in
yet and would teach everyone to type past it.

**Where the parameters come from.** A validated report carries its own snapshot
of the net weight and packets-per-carton it was judged against (decision 20), so
editing a product's packaging next month cannot silently rewrite an ecart someone
already signed off. Only an unvalidated report falls back to the product's
current values, because it has no snapshot yet.

**Where the tonnage comes from (decision 25).** Not from the packing report --
it no longer carries one. The plant weighs a batch once, on the daily report the
line files before packaging, so `for_of` and `by_product` sum tonnage from the
OF's own validated daily reports instead. `for_report` never has one to show: a
single packing report has no natural share of an OF's daily tonnage to compare
itself against, so at that scope only `machine_carton_variance` stands.
"""

from __future__ import annotations

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.domain.packaging_estimate import (
    compute_variance,
    variance_to_json,
)

_VALIDATED = "status = 'validated'"


class PackagingTolerancePolicyService:
    """The percentage at which an ecart stops looking like rounding.

    Same shape as `qc.follow_up_policies` (decision 14): a tenant-wide default
    row with `product_id` NULL and an optional override per product. It colours a
    number and nothing more -- no validation path consults it, by decision 22.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def resolve_tolerance_percent(self, *, tenant_id: str, product_id: str | None) -> float | None:
        """Per-product override, else the tenant default, else None: with no
        tolerance configured an ecart is shown but not judged."""
        if product_id is not None:
            row = self._connection.execute(
                "SELECT tolerance_percent FROM production.packaging_tolerances "
                "WHERE tenant_id = %s AND product_id = %s",
                (tenant_id, product_id),
            ).fetchone()
            if row is not None:
                return float(row[0])

        row = self._connection.execute(
            "SELECT tolerance_percent FROM production.packaging_tolerances "
            "WHERE tenant_id = %s AND product_id IS NULL",
            (tenant_id,),
        ).fetchone()
        return float(row[0]) if row is not None else None

    def set_policy(
        self, *, tenant_id: str, actor_id: str, tolerance_percent: float, product_id: str | None = None
    ) -> Result[dict]:
        if tolerance_percent < 0:
            return Err("INVALID_TOLERANCE", "tolerance_percent cannot be negative")

        self._connection.execute(
            """
            INSERT INTO production.packaging_tolerances (id, tenant_id, product_id, tolerance_percent)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, product_id) DO UPDATE
                SET tolerance_percent = EXCLUDED.tolerance_percent, updated_at = NOW()
            """,
            (str(ULID()), tenant_id, product_id, tolerance_percent),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="packaging_tolerance.updated",
            entity_type="packaging_tolerance",
            entity_id=product_id or "tenant-default",
            payload={"product_id": product_id, "tolerance_percent": tolerance_percent},
        )
        return Ok({"product_id": product_id, "tolerance_percent": tolerance_percent})

    def list_policies(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT product_id, tolerance_percent FROM production.packaging_tolerances "
            "WHERE tenant_id = %s ORDER BY product_id NULLS FIRST",
            (tenant_id,),
        ).fetchall()
        return [
            {"product_id": product_id, "tolerance_percent": float(tolerance)} for product_id, tolerance in rows
        ]


class PackagingVarianceService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._core = CoreService(connection)
        self._tolerances = PackagingTolerancePolicyService(connection)

    # ---- parameters ------------------------------------------------------

    def _product_parameters(self, *, tenant_id: str, product_id: str) -> tuple[float | None, float | None]:
        """The product's packaging, through CoreService rather than a join.

        production has no business reading `core.products` directly; core is a
        declared dependency with a service, and every other cross-boundary read
        in this module goes the same way.
        """
        product = self._core.get_product(tenant_id, product_id)
        if product is None:
            return None, None
        return product.net_weight_grams, product.packets_per_carton

    def _packaging_format(self, *, tenant_id: str, product_id: str) -> str | None:
        """'packet' / 'carton' / 'sac', so a screen can name the counted unit.

        A sac is its own selling unit, so the panel must say "sacs", not "paquets".
        `None` for a product nobody has classified yet -- the screen then falls back
        to the generic packet wording rather than guessing.
        """
        classification = ProductClassificationService(self._connection).get_classification(
            tenant_id, product_id
        )
        return classification.packaging_format if classification is not None else None

    def _daily_tonnage(
        self,
        *,
        tenant_id: str,
        of_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> float | None:
        """The OF's declared tonnage, from its own validated daily reports (decision 25).

        No longer the packing report's own figure: the plant weighs a batch once,
        on the daily report the line files before packaging, and re-typing that
        number on the packing report was a second chance to mistype it, not a
        second measurement. `None` when the OF has no validated daily report to
        attribute a tonnage from yet, not a bare zero.

        `date_from`/`date_to` matter to `by_product`: a period-filtered view has
        to filter the tonnage side by the same window as the packets it is being
        compared against, or a report from outside the period would inflate a
        figure the period never claimed to include. `for_of` leaves them unset --
        it has no period, only the whole OF.
        """
        clauses = ["r.tenant_id = %s", "r.of_id = %s", "r.report_type = 'daily'", _VALIDATED]
        params: list[object] = [tenant_id, of_id]
        if date_from:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("r.report_date <= %s")
            params.append(date_to)

        row = self._connection.execute(
            f"""
            SELECT count(*), COALESCE(SUM(d.finished_product_quantity), 0)
            FROM production.production_reports r
            JOIN production.daily_reports d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            WHERE {" AND ".join(clauses)}
            """,
            tuple(params),
        ).fetchone()
        return float(row[1]) if row[0] > 0 else None

    # ---- ecart de conditionnement ---------------------------------------

    def for_report(self, *, tenant_id: str, report_id: str) -> Result[dict]:
        """One packing report, scale against counter. No quality adjustment.

        Deliberately available on a draft as well as a validated report: a team
        that can see the ecart while they are still typing can fix a transposed
        digit before it ever reaches the validation desk.

        Decision 25: tonnage is `None` here, always. A single packing report has
        no natural share of an OF's daily-reported tonnage to compare itself
        against -- that comparison only makes sense at OF scope, where cumulative
        tonnage meets cumulative packets on equal terms (`for_of`, below). At
        report scope, `machine_carton_variance` is the ecart that is actually
        scoped correctly to what this one report recorded.
        """
        row = self._connection.execute(
            """
            SELECT r.of_id, w.product_id, w.reference, r.report_date, r.status,
                   c.packets_counted, c.carton_quantity, c.waste_carton_quantity,
                   c.snapshot_net_weight_grams, c.snapshot_packets_per_carton
            FROM production.production_reports r
            JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            WHERE r.id = %s AND r.tenant_id = %s AND r.report_type = 'conditionnement'
            """,
            (report_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"conditionnement report {report_id} not found")

        (
            of_id,
            product_id,
            reference,
            report_date,
            report_status,
            packets_counted,
            carton_quantity,
            waste_carton_quantity,
            snapshot_weight,
            snapshot_per_carton,
        ) = row

        if snapshot_weight is not None:
            net_weight_grams: float | None = float(snapshot_weight)
            packets_per_carton = float(snapshot_per_carton) if snapshot_per_carton is not None else None
        else:
            net_weight_grams, packets_per_carton = self._product_parameters(
                tenant_id=tenant_id, product_id=product_id
            )

        variance = compute_variance(
            tonnage=None,
            net_weight_grams=net_weight_grams,
            packets_per_carton=packets_per_carton,
            counted_packets=float(packets_counted),
            counted_cartons=float(carton_quantity),
            waste_cartons=float(waste_carton_quantity),
            tolerance_percent=self._tolerances.resolve_tolerance_percent(
                tenant_id=tenant_id, product_id=product_id
            ),
        )

        return Ok(
            {
                "scope": "report",
                "report_id": report_id,
                "of_id": of_id,
                "of_reference": reference,
                "product_id": product_id,
                "packaging_format": self._packaging_format(tenant_id=tenant_id, product_id=product_id),
                "report_date": report_date.isoformat(),
                "report_status": report_status,
                # A snapshot means the figures were frozen at validation; without
                # one the ecart moves if someone edits the product, and the screen
                # should say so.
                "parameters_frozen": snapshot_weight is not None,
                **variance_to_json(variance),
            }
        )

    # ---- ecart net -------------------------------------------------------

    def for_of(self, *, tenant_id: str, of_id: str) -> Result[dict]:
        """The whole order: every validated packing report, less quality.

        Only validated reports count, for the same reason consolidation excludes
        the rest -- a draft is a team's working notes, and from Phase 5 a validated
        report is also what moved the stock this ecart is checking.

        Tonnage (decision 25) comes from the OF's own validated daily reports, not
        from summing the packing reports' figures -- they no longer carry one.
        """
        work_order = self._connection.execute(
            "SELECT product_id, reference FROM production.work_orders WHERE id = %s AND tenant_id = %s",
            (of_id, tenant_id),
        ).fetchone()
        if work_order is None:
            return Err("NOT_FOUND", f"work order {of_id} not found")
        product_id, reference = work_order

        totals = self._connection.execute(
            f"""
            SELECT
                count(*),
                COALESCE(SUM(c.packets_counted), 0),
                COALESCE(SUM(c.carton_quantity), 0),
                COALESCE(SUM(c.waste_carton_quantity), 0),
                CASE WHEN COUNT(DISTINCT c.snapshot_net_weight_grams) = 1
                     THEN MIN(c.snapshot_net_weight_grams) END,
                CASE WHEN COUNT(DISTINCT c.snapshot_packets_per_carton) = 1
                     THEN MIN(c.snapshot_packets_per_carton) END,
                COUNT(DISTINCT c.snapshot_net_weight_grams)
            FROM production.production_reports r
            JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.report_type = 'conditionnement' AND r.{_VALIDATED}
            """,
            (tenant_id, of_id),
        ).fetchone()

        report_count = int(totals[0])
        packets_counted, cartons = float(totals[1]), float(totals[2])
        waste_cartons = float(totals[3])
        agreed_weight, agreed_per_carton, distinct_weights = totals[4], totals[5], int(totals[6])
        tonnage = self._daily_tonnage(tenant_id=tenant_id, of_id=of_id)

        # When every validated report was frozen against the same parameters, use
        # them. When they disagree -- a net weight corrected mid-run -- fall back
        # to the product's current values and say so, rather than picking one
        # report's snapshot and presenting it as though it applied to all of them.
        parameters_varied = distinct_weights > 1
        if agreed_weight is not None and not parameters_varied:
            net_weight_grams: float | None = float(agreed_weight)
            packets_per_carton = float(agreed_per_carton) if agreed_per_carton is not None else None
        else:
            net_weight_grams, packets_per_carton = self._product_parameters(
                tenant_id=tenant_id, product_id=product_id
            )

        rejected = self._rejected(tenant_id=tenant_id, of_id=of_id, product_id=product_id)

        variance = compute_variance(
            tonnage=tonnage,
            net_weight_grams=net_weight_grams,
            packets_per_carton=packets_per_carton,
            counted_packets=packets_counted,
            counted_cartons=cartons,
            rejected_packets=rejected["subtractable"],
            undecided_packets=rejected["undecided"],
            waste_cartons=waste_cartons,
            tolerance_percent=self._tolerances.resolve_tolerance_percent(
                tenant_id=tenant_id, product_id=product_id
            ),
        )

        return Ok(
            {
                "scope": "work_order",
                "of_id": of_id,
                "of_reference": reference,
                "product_id": product_id,
                "packaging_format": self._packaging_format(tenant_id=tenant_id, product_id=product_id),
                "report_count": report_count,
                "parameters_varied": parameters_varied,
                "quality_available": rejected["available"],
                **variance_to_json(variance),
            }
        )

    def _rejected(self, *, tenant_id: str, of_id: str, product_id: str) -> dict:
        """Quality's subtraction, through qc's service -- never a join into its schema.

        qc is an optional dependency: a deployment without it still gets an ecart,
        just the gross one. `quality_available` says which of the two the caller is
        looking at, so a screen never labels a gross figure as net.
        """
        try:
            from modules.qc.api.non_conformity_service import NonConformityService
        except ImportError:  # pragma: no cover - qc is an optional dependency
            return {"subtractable": 0.0, "undecided": 0.0, "available": False}

        rejected = NonConformityService(self._connection).get_rejected_quantity_for_of(
            tenant_id=tenant_id, of_id=of_id, product_id=product_id
        )
        return {**rejected, "available": True}

    # ---- the finished-goods warehouse view -------------------------------

    def by_product(
        self, *, tenant_id: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        """Ecart net per finished product over a period, with its reports listed.

        Grouped by product rather than by day for the total, because quality
        attaches to an OF and not to a date -- an NC raised a week later cannot be
        pinned on the Tuesday shift. The per-report rows carry their own date, so a
        screen can still show the day breakdown; those are gross for the same
        reason, and are labelled that way.
        """
        clauses = ["r.tenant_id = %s", "r.report_type = 'conditionnement'", f"r.{_VALIDATED}"]
        params: list[object] = [tenant_id]
        if date_from:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("r.report_date <= %s")
            params.append(date_to)

        rows = self._connection.execute(
            f"""
            SELECT w.product_id, r.of_id, w.reference, r.id, r.report_date,
                   c.packets_counted, c.carton_quantity, c.waste_carton_quantity,
                   c.snapshot_net_weight_grams, c.snapshot_packets_per_carton
            FROM production.production_reports r
            JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            WHERE {" AND ".join(clauses)}
            ORDER BY w.product_id, r.report_date
            """,
            tuple(params),
        ).fetchall()

        grouped: dict[str, dict] = {}
        for (
            product_id,
            of_id,
            reference,
            report_id,
            report_date,
            packets,
            cartons,
            waste_cartons,
            snapshot_weight,
            snapshot_per_carton,
        ) in rows:
            bucket = grouped.setdefault(
                product_id,
                {
                    "product_id": product_id,
                    "packets": 0.0,
                    "cartons": 0.0,
                    "waste_cartons": 0.0,
                    "of_ids": set(),
                    "reports": [],
                    "weights": set(),
                },
            )
            bucket["packets"] += float(packets)
            bucket["cartons"] += float(cartons)
            bucket["waste_cartons"] += float(waste_cartons)
            bucket["of_ids"].add(of_id)
            bucket["weights"].add(float(snapshot_weight) if snapshot_weight is not None else None)

            weight = float(snapshot_weight) if snapshot_weight is not None else None
            per_carton = float(snapshot_per_carton) if snapshot_per_carton is not None else None
            if weight is None:
                weight, per_carton = self._product_parameters(tenant_id=tenant_id, product_id=product_id)
            # Decision 25: no per-report tonnage any more -- see for_report's docstring.
            bucket["reports"].append(
                {
                    "report_id": report_id,
                    "of_id": of_id,
                    "of_reference": reference,
                    "report_date": report_date.isoformat(),
                    **variance_to_json(
                        compute_variance(
                            tonnage=None,
                            net_weight_grams=weight,
                            packets_per_carton=per_carton,
                            counted_packets=float(packets),
                            counted_cartons=float(cartons),
                            waste_cartons=float(waste_cartons),
                        )
                    ),
                }
            )

        results: list[dict] = []
        for product_id, bucket in grouped.items():
            known_weights = {w for w in bucket["weights"] if w is not None}
            if len(known_weights) == 1 and None not in bucket["weights"]:
                net_weight_grams: float | None = next(iter(known_weights))
                packets_per_carton = bucket["reports"][0]["packets_per_carton"]
            else:
                net_weight_grams, packets_per_carton = self._product_parameters(
                    tenant_id=tenant_id, product_id=product_id
                )

            subtractable = 0.0
            undecided = 0.0
            quality_available = True
            # Decision 25: tonnage summed from each contributing OF's own daily
            # reports, not from the packing reports -- they no longer carry one.
            # An OF with no validated daily report yet simply contributes nothing,
            # rather than forcing the whole product's tonnage to be treated as unknown.
            tonnage_known = False
            tonnage_total = 0.0
            for of_id in bucket["of_ids"]:
                rejected = self._rejected(tenant_id=tenant_id, of_id=of_id, product_id=product_id)
                subtractable += rejected["subtractable"]
                undecided += rejected["undecided"]
                quality_available = quality_available and rejected["available"]

                of_tonnage = self._daily_tonnage(
                    tenant_id=tenant_id, of_id=of_id, date_from=date_from, date_to=date_to
                )
                if of_tonnage is not None:
                    tonnage_known = True
                    tonnage_total += of_tonnage

            variance = compute_variance(
                tonnage=tonnage_total if tonnage_known else None,
                net_weight_grams=net_weight_grams,
                packets_per_carton=packets_per_carton,
                counted_packets=bucket["packets"],
                counted_cartons=bucket["cartons"],
                rejected_packets=subtractable,
                undecided_packets=undecided,
                waste_cartons=bucket["waste_cartons"],
                tolerance_percent=self._tolerances.resolve_tolerance_percent(
                    tenant_id=tenant_id, product_id=product_id
                ),
            )
            results.append(
                {
                    "scope": "product",
                    "product_id": product_id,
                    "packaging_format": self._packaging_format(tenant_id=tenant_id, product_id=product_id),
                    "of_count": len(bucket["of_ids"]),
                    "report_count": len(bucket["reports"]),
                    "quality_available": quality_available,
                    **variance_to_json(variance),
                    "reports": bucket["reports"],
                }
            )

        # Ordered by packets rather than tonnage: tonnage is now often absent
        # (decision 25), and packets is the one total every row always has.
        results.sort(key=lambda row: row["counted_packets"], reverse=True)
        return results
