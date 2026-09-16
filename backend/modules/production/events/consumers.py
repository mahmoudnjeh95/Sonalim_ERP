from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.production.api.regrind_service import ScrapService

CONSUMER_NAME = "production.qc_non_conformity_dispositioned"


def _handle_non_conformity_dispositioned(connection: psycopg.Connection, envelope: dict) -> None:
    """Turn a quality disposition into production's own scrap record.

    This is the module boundary doing its job. The pasta pulled out of a rejected
    packet goes back to rebroyat, but `scrap_records` belongs to production and qc
    may not write into it — so qc publishes what it decided and production reacts,
    the same shape as procurement's receipt feeding warehouse.

    Only the regrind lines become scrap. Film, carton and tape are déchet: they are
    reported by component on the non-conformity, and deliberately not deducted or
    scrapped again here, because their stock already left when the conditionnement
    report was validated.

    Idempotency is handled by the consumer registry, which records
    (event_id, consumer) in events.processed_events before committing — so a
    redelivery of this event writes no second scrap record.
    """
    payload = envelope["payload"]
    tenant_id = envelope["tenant_id"]
    non_conformity_id = payload["non_conformity_id"]
    of_id = payload["of_id"]
    product_id = payload["product_id"]

    scrap_service = ScrapService(connection)
    for line in payload.get("lines", []):
        if line.get("disposition") != "regrind":
            continue

        result = scrap_service.record_scrap(
            tenant_id=tenant_id,
            actor_id="system:qc-disposition-consumer",
            work_order_id=of_id,
            scrap_type="non_conformity",
            product_id=product_id,
            quantity=line["quantity"],
            source_note=f"non-conformity {non_conformity_id}",
        )
        if isinstance(result, Err):
            raise RuntimeError(
                f"failed to record rebroyat scrap for non-conformity {non_conformity_id}: {result.message}"
            )


register(CONSUMER_NAME, "qc.non_conformity.dispositioned", _handle_non_conformity_dispositioned)
