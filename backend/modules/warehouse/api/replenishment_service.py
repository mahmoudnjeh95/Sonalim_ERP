from __future__ import annotations

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.warehouse.domain.replenishment import (
    ReorderRule,
    ReplenishmentProposal,
    needs_replenishment,
    proposal_quantity,
    validate_proposal_decision,
    validate_rule,
)

SYSTEM_ACTOR = "system:replenishment"

_RULE_COLUMNS = (
    "id, tenant_id, product_id, site_id, reorder_point, order_up_to, min_order_quantity, preferred_supplier_id, "
    "is_active, created_by, created_at"
)
_PROPOSAL_COLUMNS = (
    "id, tenant_id, rule_id, product_id, site_id, available_at_proposal, quantity, supplier_id, status, created_at, "
    "decided_by, decided_at, closed_at"
)


def _rule_from_row(row) -> ReorderRule:
    return ReorderRule(
        id=row[0], tenant_id=row[1], product_id=row[2], site_id=row[3], reorder_point=float(row[4]),
        order_up_to=float(row[5]), min_order_quantity=float(row[6]), preferred_supplier_id=row[7], is_active=row[8],
        created_by=row[9], created_at=row[10],
    )


def _proposal_from_row(row) -> ReplenishmentProposal:
    return ReplenishmentProposal(
        id=row[0], tenant_id=row[1], rule_id=row[2], product_id=row[3], site_id=row[4],
        available_at_proposal=float(row[5]), quantity=float(row[6]), supplier_id=row[7], status=row[8], created_at=row[9],
        decided_by=row[10], decided_at=row[11], closed_at=row[12],
    )


def _duplicate_rule() -> Err:
    return Err(
        "DUPLICATE_RULE",
        "this product already has a reorder rule for that scope",
        "ce produit a déjà une règle de réapprovisionnement pour ce périmètre",
    )


class ReplenishmentService:
    """Min/max reorder rules and the proposals they raise. Warehouse decides
    *that* something must be ordered and how much; procurement, on the
    approval event, decides *how* (the draft purchase order)."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # --- Rules ------------------------------------------------------------------------

    def list_rules(self, *, tenant_id: str) -> list[ReorderRule]:
        rows = self._connection.execute(
            f"SELECT {_RULE_COLUMNS} FROM warehouse.reorder_rules WHERE tenant_id = %s ORDER BY created_at DESC, id DESC",
            (tenant_id,),
        ).fetchall()
        return [_rule_from_row(row) for row in rows]

    def _get_rule(self, *, tenant_id: str, rule_id: str, for_update: bool = False) -> Result[ReorderRule]:
        lock = " FOR UPDATE" if for_update else ""
        row = self._connection.execute(
            f"SELECT {_RULE_COLUMNS} FROM warehouse.reorder_rules WHERE id = %s AND tenant_id = %s{lock}", (rule_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"reorder rule {rule_id} not found", f"règle de réapprovisionnement {rule_id} introuvable")
        return Ok(_rule_from_row(row))

    def _scope_taken(self, *, tenant_id: str, product_id: str, site_id: str | None, except_id: str | None = None) -> bool:
        row = self._connection.execute(
            """
            SELECT id FROM warehouse.reorder_rules
            WHERE tenant_id = %s AND product_id = %s AND COALESCE(site_id, '') = COALESCE(%s, '')
            """,
            (tenant_id, product_id, site_id),
        ).fetchone()
        return row is not None and row[0] != except_id

    def create_rule(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        product_id: str,
        reorder_point: float,
        order_up_to: float,
        site_id: str | None = None,
        min_order_quantity: float = 0,
        preferred_supplier_id: str | None = None,
    ) -> Result[ReorderRule]:
        validation = validate_rule(reorder_point=reorder_point, order_up_to=order_up_to, min_order_quantity=min_order_quantity)
        if isinstance(validation, Err):
            return validation
        if self._scope_taken(tenant_id=tenant_id, product_id=product_id, site_id=site_id):
            return _duplicate_rule()
        rule_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO warehouse.reorder_rules
                (id, tenant_id, product_id, site_id, reorder_point, order_up_to, min_order_quantity, preferred_supplier_id, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (rule_id, tenant_id, product_id, site_id, reorder_point, order_up_to, min_order_quantity, preferred_supplier_id, actor_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="reorder_rule.created",
            entity_type="reorder_rule", entity_id=rule_id,
            payload={"product_id": product_id, "site_id": site_id, "reorder_point": reorder_point, "order_up_to": order_up_to},
        )
        return self._get_rule(tenant_id=tenant_id, rule_id=rule_id)

    def update_rule(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        rule_id: str,
        reorder_point: float | None = None,
        order_up_to: float | None = None,
        min_order_quantity: float | None = None,
        preferred_supplier_id: str | None = None,
        is_active: bool | None = None,
    ) -> Result[ReorderRule]:
        current = self._get_rule(tenant_id=tenant_id, rule_id=rule_id, for_update=True)
        if isinstance(current, Err):
            return current
        rule = current.value
        updated = {
            "reorder_point": reorder_point if reorder_point is not None else rule.reorder_point,
            "order_up_to": order_up_to if order_up_to is not None else rule.order_up_to,
            "min_order_quantity": min_order_quantity if min_order_quantity is not None else rule.min_order_quantity,
            "preferred_supplier_id": preferred_supplier_id if preferred_supplier_id is not None else rule.preferred_supplier_id,
            "is_active": is_active if is_active is not None else rule.is_active,
        }
        validation = validate_rule(
            reorder_point=updated["reorder_point"], order_up_to=updated["order_up_to"], min_order_quantity=updated["min_order_quantity"]
        )
        if isinstance(validation, Err):
            return validation
        self._connection.execute(
            """
            UPDATE warehouse.reorder_rules
            SET reorder_point = %s, order_up_to = %s, min_order_quantity = %s, preferred_supplier_id = %s, is_active = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (updated["reorder_point"], updated["order_up_to"], updated["min_order_quantity"], updated["preferred_supplier_id"],
             updated["is_active"], rule_id, tenant_id),
        )
        changes = {
            key: value
            for key, value in {
                "reorder_point": reorder_point, "order_up_to": order_up_to, "min_order_quantity": min_order_quantity,
                "preferred_supplier_id": preferred_supplier_id, "is_active": is_active,
            }.items()
            if value is not None
        }
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="reorder_rule.updated",
            entity_type="reorder_rule", entity_id=rule_id, payload=changes,
        )
        return self._get_rule(tenant_id=tenant_id, rule_id=rule_id)

    def delete_rule(self, *, tenant_id: str, actor_id: str, rule_id: str) -> Result[None]:
        """A rule with proposal history is deactivated rather than deleted --
        the proposals point at it and are the record of what was ordered."""
        current = self._get_rule(tenant_id=tenant_id, rule_id=rule_id, for_update=True)
        if isinstance(current, Err):
            return current
        has_history = self._connection.execute(
            "SELECT 1 FROM warehouse.replenishment_proposals WHERE rule_id = %s LIMIT 1", (rule_id,)
        ).fetchone()
        if has_history:
            return Err(
                "RULE_HAS_HISTORY",
                "this rule has proposals -- deactivate it instead",
                "cette règle a des propositions -- désactivez-la plutôt",
            )
        self._connection.execute("DELETE FROM warehouse.reorder_rules WHERE id = %s AND tenant_id = %s", (rule_id, tenant_id))
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="reorder_rule.deleted",
            entity_type="reorder_rule", entity_id=rule_id,
            payload={"product_id": current.value.product_id, "site_id": current.value.site_id},
        )
        return Ok(None)

    # --- Evaluation -------------------------------------------------------------------

    def available_quantity(self, *, tenant_id: str, product_id: str, site_id: str | None) -> float:
        """What can still be promised -- on hand less reserved, quarantine
        excluded -- over the rule's scope."""
        site_clause = "AND l.site_id = %s" if site_id is not None else ""
        params: list[object] = [tenant_id, product_id]
        if site_id is not None:
            params.append(site_id)
        row = self._connection.execute(
            f"""
            SELECT COALESCE(SUM(si.quantity_on_hand - si.quantity_reserved), 0)
            FROM warehouse.stock_items si
            JOIN warehouse.locations l ON l.id = si.location_id AND l.tenant_id = si.tenant_id
            WHERE si.tenant_id = %s AND si.product_id = %s AND NOT COALESCE(l.is_blocked, FALSE) {site_clause}
            """,
            params,
        ).fetchone()
        return float(row[0])

    def evaluate(self, *, tenant_id: str, actor_id: str = SYSTEM_ACTOR) -> dict[str, list[ReplenishmentProposal]]:
        """One pass over the tenant's active rules: close approved proposals
        whose stock has arrived (availability back above the reorder point),
        then raise a proposal for every breached rule with nothing pending."""
        rules = [rule for rule in self.list_rules(tenant_id=tenant_id) if rule.is_active]
        created: list[ReplenishmentProposal] = []
        fulfilled: list[ReplenishmentProposal] = []
        core = CoreService(self._connection)

        for rule in rules:
            available = self.available_quantity(tenant_id=tenant_id, product_id=rule.product_id, site_id=rule.site_id)
            pending = self._connection.execute(
                f"""
                SELECT {_PROPOSAL_COLUMNS} FROM warehouse.replenishment_proposals
                WHERE rule_id = %s AND status IN ('open', 'approved') FOR UPDATE
                """,
                (rule.id,),
            ).fetchone()

            if pending is not None:
                proposal = _proposal_from_row(pending)
                if proposal.status == "approved" and not needs_replenishment(available=available, reorder_point=rule.reorder_point):
                    self._connection.execute(
                        "UPDATE warehouse.replenishment_proposals SET status = 'fulfilled', closed_at = NOW() WHERE id = %s",
                        (proposal.id,),
                    )
                    record_audit(
                        self._connection, tenant_id=tenant_id, actor_id=actor_id, action="replenishment_proposal.fulfilled",
                        entity_type="replenishment_proposal", entity_id=proposal.id, payload={"available": available},
                    )
                    fulfilled.append(self._get_proposal_row(proposal.id))
                continue

            if not needs_replenishment(available=available, reorder_point=rule.reorder_point):
                continue
            uom = core.get_product_uom(tenant_id, rule.product_id)
            quantity = proposal_quantity(
                available=available, order_up_to=rule.order_up_to, min_order_quantity=rule.min_order_quantity,
                integer_only=bool(uom and uom.is_integer_only),
            )
            proposal_id = str(ULID())
            self._connection.execute(
                """
                INSERT INTO warehouse.replenishment_proposals
                    (id, tenant_id, rule_id, product_id, site_id, available_at_proposal, quantity, supplier_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (proposal_id, tenant_id, rule.id, rule.product_id, rule.site_id, available, quantity, rule.preferred_supplier_id),
            )
            record_audit(
                self._connection, tenant_id=tenant_id, actor_id=actor_id, action="replenishment_proposal.created",
                entity_type="replenishment_proposal", entity_id=proposal_id,
                payload={"rule_id": rule.id, "product_id": rule.product_id, "available": available, "quantity": quantity},
            )
            created.append(self._get_proposal_row(proposal_id))
        return {"created": created, "fulfilled": fulfilled}

    def tenants_with_active_rules(self) -> list[str]:
        rows = self._connection.execute("SELECT DISTINCT tenant_id FROM warehouse.reorder_rules WHERE is_active").fetchall()
        return [row[0] for row in rows]

    # --- Proposals --------------------------------------------------------------------

    def _get_proposal_row(self, proposal_id: str) -> ReplenishmentProposal:
        return _proposal_from_row(
            self._connection.execute(
                f"SELECT {_PROPOSAL_COLUMNS} FROM warehouse.replenishment_proposals WHERE id = %s", (proposal_id,)
            ).fetchone()
        )

    def list_proposals(self, *, tenant_id: str, status: str | None = None) -> list[ReplenishmentProposal]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"SELECT {_PROPOSAL_COLUMNS} FROM warehouse.replenishment_proposals WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, id DESC LIMIT 500",
            params,
        ).fetchall()
        return [_proposal_from_row(row) for row in rows]

    def _get_open_proposal(self, *, tenant_id: str, proposal_id: str) -> Result[ReplenishmentProposal]:
        row = self._connection.execute(
            f"SELECT {_PROPOSAL_COLUMNS} FROM warehouse.replenishment_proposals WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (proposal_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"proposal {proposal_id} not found", f"proposition {proposal_id} introuvable")
        proposal = _proposal_from_row(row)
        decision = validate_proposal_decision(proposal.status)
        if isinstance(decision, Err):
            return decision
        return Ok(proposal)

    def approve_proposal(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        proposal_id: str,
        correlation_id: str,
        quantity: float | None = None,
        supplier_id: str | None = None,
    ) -> Result[ReplenishmentProposal]:
        """Hands the proposal to procurement. The approver may adjust the
        quantity or supplier first -- the proposal is a suggestion, and the
        approved figures are what gets ordered and audited."""
        current = self._get_open_proposal(tenant_id=tenant_id, proposal_id=proposal_id)
        if isinstance(current, Err):
            return current
        proposal = current.value
        final_quantity = quantity if quantity is not None else proposal.quantity
        if final_quantity <= 0:
            return Err("INVALID_QUANTITY", "quantity must be positive", "la quantité doit être positive")
        uom = CoreService(self._connection).get_product_uom(tenant_id, proposal.product_id)
        if uom is None:
            return Err("NOT_FOUND", f"product {proposal.product_id} has no unit", f"le produit {proposal.product_id} n'a pas d'unité")
        final_supplier = supplier_id if supplier_id is not None else proposal.supplier_id

        self._connection.execute(
            """
            UPDATE warehouse.replenishment_proposals
            SET status = 'approved', quantity = %s, supplier_id = %s, decided_by = %s, decided_at = NOW()
            WHERE id = %s
            """,
            (final_quantity, final_supplier, actor_id, proposal_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="replenishment_proposal.approved",
            entity_type="replenishment_proposal", entity_id=proposal_id,
            payload={"quantity": final_quantity, "supplier_id": final_supplier, "proposed_quantity": proposal.quantity},
        )
        publish_event(
            self._connection,
            event_type="warehouse.replenishment.approved",
            producer="warehouse",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "proposal_id": proposal_id,
                "product_id": proposal.product_id,
                "uom_id": uom.id,
                "quantity": final_quantity,
                "supplier_id": final_supplier,
                "site_id": proposal.site_id,
            },
        )
        return Ok(self._get_proposal_row(proposal_id))

    def dismiss_proposal(self, *, tenant_id: str, actor_id: str, proposal_id: str) -> Result[ReplenishmentProposal]:
        """Dismissing frees the rule: if availability is still at or below the
        reorder point, the next evaluation raises a fresh proposal."""
        current = self._get_open_proposal(tenant_id=tenant_id, proposal_id=proposal_id)
        if isinstance(current, Err):
            return current
        self._connection.execute(
            """
            UPDATE warehouse.replenishment_proposals
            SET status = 'dismissed', decided_by = %s, decided_at = NOW(), closed_at = NOW()
            WHERE id = %s
            """,
            (actor_id, proposal_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="replenishment_proposal.dismissed",
            entity_type="replenishment_proposal", entity_id=proposal_id, payload={"quantity": current.value.quantity},
        )
        return Ok(self._get_proposal_row(proposal_id))

