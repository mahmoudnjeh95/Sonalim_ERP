"""What a machine's history reads from other modules -- only through their api/ services.

Production (stops of validated shifts, running minutes) and warehouse (FIFO cost of the
parts issued to a job) are optional dependencies of maintenance: when one is not
installed its reader is None and the history says "non disponible" instead of failing.
The production reader is a protocol so HistoryService can be tested with a fake one.
"""
from __future__ import annotations

import datetime
from typing import Protocol

import psycopg


class ProductionReadings(Protocol):
    def stops(
        self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date, equipment_id: str | None = None
    ) -> list[dict]: ...

    def running_minutes(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[str, int]: ...


class ProductionServices:
    """`ProductionReadings` over production's own services (validated shifts only)."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def stops(
        self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date, equipment_id: str | None = None
    ) -> list[dict]:
        from modules.production.api.stops_analytics_service import StopsAnalyticsService

        return StopsAnalyticsService(self._connection).list_stops(
            tenant_id=tenant_id, date_from=date_from.isoformat(), date_to=date_to.isoformat(), equipment_id=equipment_id
        )

    def running_minutes(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[str, int]:
        from modules.production.api.machine_performance_service import MachinePerformanceService

        rows = MachinePerformanceService(self._connection).list_machine_performance(
            tenant_id=tenant_id, grain="year", date_from=date_from.isoformat(), date_to=date_to.isoformat()
        )
        minutes: dict[str, int] = {}
        for row in rows:
            minutes[row["equipment_id"]] = minutes.get(row["equipment_id"], 0) + int(row["production_minutes"])
        return minutes


def production_readings(connection: psycopg.Connection) -> ProductionReadings | None:
    """Production's readings, or None when the production module is not installed."""
    try:
        import modules.production.api.stops_analytics_service  # noqa: F401
    except ImportError:
        return None
    return ProductionServices(connection)


def job_parts_costs(
    connection: psycopg.Connection, tenant_id: str, job_numbers: list[str]
) -> dict[str, tuple[float, float]] | None:
    """(cost XOF, unvalued quantity) of what left stock for each job (`maintenance:<number>`,
    the reference PartsService.approve issues under); None without the warehouse module."""
    try:
        from modules.warehouse.api.valuation_service import ValuationService
    except ImportError:
        return None
    if not job_numbers:
        return {}
    references = {f"maintenance:{number}": number for number in job_numbers}
    costs = ValuationService(connection).costs_of_references(tenant_id=tenant_id, references=list(references))
    return {references[reference]: (value["cost"], value["unvalued_quantity"]) for reference, value in costs.items()}
