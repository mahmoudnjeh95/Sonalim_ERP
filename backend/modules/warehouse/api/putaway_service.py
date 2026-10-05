from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService
from modules.warehouse.domain.entities import Location
from modules.warehouse.domain.putaway import PutawayRule, rank_candidates

_RULE_COLUMNS = "id, tenant_id, site_id, product_id, target_location_id, created_by, created_at"


def _rule_from_row(row) -> PutawayRule:
    return PutawayRule(id=row[0], tenant_id=row[1], site_id=row[2], product_id=row[3], target_location_id=row[4], created_by=row[5], created_at=row[6])


class PutAwayService:
    """Suggests where freshly-received or provisionally-stored stock should
    actually live, and confirms the move as an ordinary transfer -- put-away
    is a transfer that happens after receiving, not a change to how
    receiving itself posts stock."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._locations = LocationService(connection)
        self._stock = StockService(connection)

    def suggest_locations(
        self, *, tenant_id: str, site_id: str, product_id: str, exclude_location_id: str | None = None
    ) -> list[Location]:
        rule_row = self._connection.execute(
            "SELECT target_location_id FROM warehouse.putaway_rules WHERE tenant_id = %s AND site_id = %s AND product_id = %s",
            (tenant_id, site_id, product_id),
        ).fetchone()
        rule_location_id = rule_row[0] if rule_row else None

        same_product_rows = self._connection.execute(
            """
            SELECT DISTINCT si.location_id
            FROM warehouse.stock_items si
            JOIN warehouse.locations l ON l.id = si.location_id AND l.tenant_id = si.tenant_id
            WHERE si.tenant_id = %s AND si.product_id = %s AND l.site_id = %s AND l.location_type = 'bin' AND si.quantity_on_hand > 0
            """,
            (tenant_id, product_id, site_id),
        ).fetchall()
        same_product_location_ids = [row[0] for row in same_product_rows]

        empty_bin_rows = self._connection.execute(
            """
            SELECT l.id
            FROM warehouse.locations l
            WHERE l.tenant_id = %s AND l.site_id = %s AND l.location_type = 'bin'
                AND NOT EXISTS (
                    SELECT 1 FROM warehouse.stock_items si
                    WHERE si.tenant_id = l.tenant_id AND si.location_id = l.id AND si.quantity_on_hand != 0
                )
            """,
            (tenant_id, site_id),
        ).fetchall()
        empty_bin_ids = [row[0] for row in empty_bin_rows]

        ranked_ids = rank_candidates(
            rule_location_id=rule_location_id,
            same_product_location_ids=same_product_location_ids,
            empty_bin_ids=empty_bin_ids,
            exclude_location_id=exclude_location_id,
        )
        locations_by_id = {loc.id: loc for loc in self._locations.get_locations_by_ids(tenant_id=tenant_id, location_ids=ranked_ids)}
        return [locations_by_id[location_id] for location_id in ranked_ids if location_id in locations_by_id]

    def create_rule(
        self, *, tenant_id: str, actor_id: str, site_id: str, product_id: str, target_location_id: str
    ) -> Result[PutawayRule]:
        target_row = self._connection.execute(
            "SELECT site_id, location_type FROM warehouse.locations WHERE id = %s AND tenant_id = %s",
            (target_location_id, tenant_id),
        ).fetchone()
        if target_row is None:
            return Err(
                "NOT_FOUND", f"location {target_location_id} not found", f"emplacement {target_location_id} introuvable"
            )
        if target_row[0] != site_id:
            return Err(
                "CROSS_SITE_TARGET",
                "the target location must belong to the given site",
                "l'emplacement cible doit appartenir au site indiqué",
            )
        if target_row[1] != "bin":
            return Err("INVALID_TARGET", "the target location must be a bin", "l'emplacement cible doit être un casier")

        existing = self._connection.execute(
            "SELECT id FROM warehouse.putaway_rules WHERE tenant_id = %s AND site_id = %s AND product_id = %s",
            (tenant_id, site_id, product_id),
        ).fetchone()
        rule_id = existing[0] if existing else str(ULID())
        if existing:
            self._connection.execute(
                "UPDATE warehouse.putaway_rules SET target_location_id = %s, created_by = %s, created_at = NOW() WHERE id = %s",
                (target_location_id, actor_id, rule_id),
            )
        else:
            self._connection.execute(
                """
                INSERT INTO warehouse.putaway_rules (id, tenant_id, site_id, product_id, target_location_id, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (rule_id, tenant_id, site_id, product_id, target_location_id, actor_id),
            )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="putaway_rule.set",
            entity_type="putaway_rule", entity_id=rule_id,
            payload={"site_id": site_id, "product_id": product_id, "target_location_id": target_location_id},
        )
        row = self._connection.execute(f"SELECT {_RULE_COLUMNS} FROM warehouse.putaway_rules WHERE id = %s", (rule_id,)).fetchone()
        return Ok(_rule_from_row(row))

    def list_rules(self, *, tenant_id: str, site_id: str | None = None) -> list[PutawayRule]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if site_id is not None:
            clauses.append("site_id = %s")
            params.append(site_id)
        rows = self._connection.execute(
            f"SELECT {_RULE_COLUMNS} FROM warehouse.putaway_rules WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_rule_from_row(row) for row in rows]

    def delete_rule(self, *, tenant_id: str, actor_id: str, rule_id: str) -> Result[None]:
        row = self._connection.execute(
            "SELECT product_id, site_id FROM warehouse.putaway_rules WHERE id = %s AND tenant_id = %s", (rule_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"put-away rule {rule_id} not found", f"règle de rangement {rule_id} introuvable")
        self._connection.execute("DELETE FROM warehouse.putaway_rules WHERE id = %s AND tenant_id = %s", (rule_id, tenant_id))
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="putaway_rule.deleted",
            entity_type="putaway_rule", entity_id=rule_id, payload={"product_id": row[0], "site_id": row[1]},
        )
        return Ok(None)

    def confirm_putaway(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        site_id: str,
        product_id: str,
        from_location_id: str,
        to_location_id: str,
        quantity: float,
        correlation_id: str,
    ) -> Result[None]:
        suggestions = self.suggest_locations(
            tenant_id=tenant_id, site_id=site_id, product_id=product_id, exclude_location_id=from_location_id
        )
        followed_suggestion = len(suggestions) > 0 and suggestions[0].id == to_location_id

        transfer_result = self._stock.transfer_stock(
            tenant_id=tenant_id,
            product_id=product_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            quantity=quantity,
            correlation_id=correlation_id,
            reference="putaway",
            actor_id=actor_id,
        )
        if isinstance(transfer_result, Err):
            return transfer_result

        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="putaway.confirmed",
            entity_type="stock_item", entity_id=f"{to_location_id}:{product_id}",
            payload={
                "from_location_id": from_location_id,
                "to_location_id": to_location_id,
                "quantity": quantity,
                "followed_suggestion": followed_suggestion,
            },
        )
        publish_event(
            self._connection,
            event_type="warehouse.putaway.confirmed",
            producer="warehouse",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "product_id": product_id,
                "from_location_id": from_location_id,
                "to_location_id": to_location_id,
                "quantity": quantity,
                "followed_suggestion": followed_suggestion,
            },
        )
        return Ok(None)
