"""Payout batches for an approved run: bank files per bank template, mobile money per operator,
cash sheets with the note-and-coin count. Generated batches can be regenerated until one is
confirmed; confirming every batch is what lets the run be marked paid (RunService.mark_paid)."""
from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.payroll.api.company import company_header
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.run_state import lock_run, locked, not_found
from modules.payroll.domain.payouts import (
    XOF_DENOMINATIONS, billetage, render_bank_csv, render_mobile_csv, split_net, validate_bank_template,
)

_BATCH_COLUMNS = ("b.id, b.run_id, b.method, b.group_key, b.status, b.file_name, b.total, b.line_count, "
                  "b.generated_by, b.generated_at, b.confirmed_by, b.confirmed_at")


def _slug(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", key).strip("-").lower() or "batch"


class PayoutService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # -- bank file templates ----------------------------------------------------------------
    def list_templates(self, *, tenant_id: str) -> list[dict[str, Any]]:
        return fetch_all(self.connection, "SELECT id, bank_name, delimiter, include_header, columns FROM payroll.bank_file_templates "
                                          "WHERE tenant_id = %s ORDER BY bank_name", (tenant_id,))

    def _template(self, tenant_id: str, template_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, "SELECT id, bank_name, delimiter, include_header, columns FROM payroll.bank_file_templates "
                                          "WHERE tenant_id = %s AND id = %s", (tenant_id, template_id))

    def _save_template(self, tenant_id: str, template_id: str | None, clean: dict[str, Any], actor_id: str) -> Result[str]:
        try:
            with self.connection.transaction():
                if template_id is None:
                    template_id = str(ULID())
                    self.connection.execute(
                        "INSERT INTO payroll.bank_file_templates (id, tenant_id, bank_name, delimiter, include_header, columns, created_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (template_id, tenant_id, clean["bank_name"], clean["delimiter"], clean["include_header"], Jsonb(clean["columns"]), actor_id))
                else:
                    self.connection.execute(
                        "UPDATE payroll.bank_file_templates SET bank_name = %s, delimiter = %s, include_header = %s, columns = %s WHERE id = %s",
                        (clean["bank_name"], clean["delimiter"], clean["include_header"], Jsonb(clean["columns"]), template_id))
        except psycopg.errors.UniqueViolation:
            return Err("DUPLICATE_TEMPLATE", f"{clean['bank_name']} already has a template", f"{clean['bank_name']} a déjà un modèle")
        return Ok(template_id)

    def create_template(self, *, tenant_id: str, actor_id: str, values: dict[str, Any]) -> Result[dict[str, Any]]:
        checked = validate_bank_template(values)
        if isinstance(checked, Err):
            return checked
        saved = self._save_template(tenant_id, None, checked.value, actor_id)
        if isinstance(saved, Err):
            return saved
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="bank_file_template.created",
                     entity_type="bank_file_template", entity_id=saved.value, payload=checked.value)
        return Ok(self._template(tenant_id, saved.value))

    def update_template(self, *, tenant_id: str, actor_id: str, template_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._template(tenant_id, template_id)
        if current is None:
            return Err("NOT_FOUND", "bank file template not found", "modèle de fichier bancaire introuvable")
        checked = validate_bank_template({**current, **changes})
        if isinstance(checked, Err):
            return checked
        saved = self._save_template(tenant_id, template_id, checked.value, actor_id)
        if isinstance(saved, Err):
            return saved
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="bank_file_template.updated",
                     entity_type="bank_file_template", entity_id=template_id, payload={"changes": jsonable(changes)})
        return Ok(self._template(tenant_id, template_id))

    def delete_template(self, *, tenant_id: str, actor_id: str, template_id: str) -> Result[dict[str, Any]]:
        current = self._template(tenant_id, template_id)
        if current is None:
            return Err("NOT_FOUND", "bank file template not found", "modèle de fichier bancaire introuvable")
        self.connection.execute("DELETE FROM payroll.bank_file_templates WHERE id = %s", (template_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="bank_file_template.deleted",
                     entity_type="bank_file_template", entity_id=template_id, payload=current)
        return Ok({"id": template_id})

    # -- batches ----------------------------------------------------------------------------------
    def list_batches(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection, f"SELECT {_BATCH_COLUMNS} FROM payroll.payout_batches b WHERE b.tenant_id = %s AND b.run_id = %s "
                                                   "ORDER BY b.method, b.group_key", (tenant_id, run_id)))

    def _batch(self, tenant_id: str, batch_id: str, *, lock: bool = False) -> dict[str, Any] | None:
        return fetch_one(self.connection, f"SELECT {_BATCH_COLUMNS}, r.period FROM payroll.payout_batches b JOIN payroll.runs r ON r.id = b.run_id "
                                          "WHERE b.tenant_id = %s AND b.id = %s" + (" FOR UPDATE OF b" if lock else ""), (tenant_id, batch_id))

    def _lines(self, batch_id: str) -> list[dict[str, Any]]:
        return fetch_all(self.connection, "SELECT employee_id, employee_no, full_name, details, amount FROM payroll.payout_lines "
                                          "WHERE batch_id = %s ORDER BY full_name", (batch_id,))

    def generate(self, *, tenant_id: str, actor_id: str, run_id: str) -> Result[list[dict[str, Any]]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] in ("paid", "reversed"):
            return locked(run["status"])
        if run["status"] != "approved":
            return Err("RUN_NOT_APPROVED", "payouts are generated for an approved run", "les paiements se génèrent pour une paie approuvée")
        confirmed = self.connection.execute("SELECT 1 FROM payroll.payout_batches WHERE run_id = %s AND status = 'confirmed' LIMIT 1", (run_id,)).fetchone()
        if confirmed is not None:
            return Err("PAYOUT_CONFIRMED", "a batch of this run is already confirmed; payouts can no longer be regenerated",
                       "un lot de cette paie est déjà confirmé ; les paiements ne peuvent plus être régénérés")
        self.connection.execute("DELETE FROM payroll.payout_batches WHERE run_id = %s", (run_id,))
        payslips = fetch_all(self.connection, "SELECT id, employee_id, employee_no, full_name, net, snapshot->'payment_methods' AS methods "
                                              "FROM payroll.payslips WHERE run_id = %s AND net > 0 ORDER BY full_name", (run_id,))
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        problems: list[tuple[str, Err]] = []
        for payslip in payslips:
            split = split_net(payslip["net"], payslip["methods"] or [])
            if isinstance(split, Err):
                problems.append((payslip["full_name"], split))
                continue
            for share in split.value:
                groups.setdefault((share.method, share.group_key), []).append(
                    {"payslip_id": payslip["id"], "employee_id": payslip["employee_id"], "employee_no": payslip["employee_no"],
                     "full_name": payslip["full_name"], "details": share.details, "amount": share.amount})
        if problems:
            return Err("PAYOUT_SPLIT_INVALID", "; ".join(f"{name}: {err.message}" for name, err in problems),
                       "; ".join(f"{name} : {err.message_fr}" for name, err in problems))
        for (method, key), lines in sorted(groups.items()):
            batch_id = str(ULID())
            file_name = f"paie-{run['period']:%Y-%m}-{method}-{_slug(key)}.csv"
            self.connection.execute(
                "INSERT INTO payroll.payout_batches (id, tenant_id, run_id, method, group_key, file_name, total, line_count, generated_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (batch_id, tenant_id, run_id, method, key, file_name, sum(line["amount"] for line in lines), len(lines), actor_id))
            for line in lines:
                self.connection.execute(
                    "INSERT INTO payroll.payout_lines (id, tenant_id, batch_id, payslip_id, employee_id, employee_no, full_name, details, amount) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(ULID()), tenant_id, batch_id, line["payslip_id"], line["employee_id"], line["employee_no"], line["full_name"],
                     Jsonb(line["details"]), line["amount"]))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payout_batches.generated",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"batches": len(groups), "total": int(sum(payslip["net"] for payslip in payslips))})
        return Ok(self.list_batches(tenant_id=tenant_id, run_id=run_id))

    def confirm_batch(self, *, tenant_id: str, actor_id: str, batch_id: str) -> Result[dict[str, Any]]:
        batch = self._batch(tenant_id, batch_id, lock=True)
        if batch is None:
            return Err("NOT_FOUND", "payout batch not found", "lot de paiement introuvable")
        if batch["status"] == "confirmed":
            return Err("PAYOUT_CONFIRMED", "this batch is already confirmed", "ce lot est déjà confirmé")
        self.connection.execute("UPDATE payroll.payout_batches SET status = 'confirmed', confirmed_by = %s, confirmed_at = NOW() WHERE id = %s",
                                (actor_id, batch_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payout_batch.confirmed", entity_type="payout_batch",
                     entity_id=batch_id, payload={"from_status": "generated", "to_status": "confirmed", "total": int(batch["total"])})
        return Ok(jsonable(self._batch(tenant_id, batch_id)))

    def batch_file(self, *, tenant_id: str, batch_id: str) -> Result[tuple[str, str]]:
        batch = self._batch(tenant_id, batch_id)
        if batch is None:
            return Err("NOT_FOUND", "payout batch not found", "lot de paiement introuvable")
        lines = self._lines(batch_id)
        if batch["method"] == "cash":
            return Err("PAYOUT_INVALID", "a cash batch is paid from the printed cash sheet", "un lot en espèces se paie avec la feuille de caisse imprimée")
        if batch["method"] == "mobile_money":
            return Ok((batch["file_name"], render_mobile_csv(lines)))
        template = fetch_one(self.connection, "SELECT bank_name, delimiter, include_header, columns FROM payroll.bank_file_templates "
                                              "WHERE tenant_id = %s AND bank_name = %s", (tenant_id, batch["group_key"]))
        if template is None:
            return Err("TEMPLATE_MISSING", f"no bank file template for {batch['group_key']}; add one in the payouts tab",
                       f"aucun modèle de fichier bancaire pour {batch['group_key']} ; ajoutez-en un dans l'onglet paiements")
        return Ok((batch["file_name"], render_bank_csv(template, lines, batch["period"])))

    def cash_sheet(self, *, tenant_id: str, batch_id: str) -> Result[dict[str, Any]]:
        batch = self._batch(tenant_id, batch_id)
        if batch is None:
            return Err("NOT_FOUND", "payout batch not found", "lot de paiement introuvable")
        if batch["method"] != "cash":
            return Err("PAYOUT_INVALID", "only a cash batch has a cash sheet", "seul un lot en espèces a une feuille de caisse")
        lines = []
        totals = {str(value): 0 for value in XOF_DENOMINATIONS}
        remainder_total = 0
        for line in self._lines(batch_id):
            counts, remainder = billetage(line["amount"])
            for value, count in counts.items():
                totals[str(value)] += count
            remainder_total += int(remainder)
            lines.append({"employee_no": line["employee_no"], "full_name": line["full_name"], "amount": int(line["amount"]),
                          "counts": {str(value): count for value, count in counts.items()}, "remainder": int(remainder)})
        return Ok({"batch": jsonable({key: value for key, value in batch.items() if key != "period"}), "period": batch["period"].isoformat(),
                   "company": company_header(self.connection, tenant_id), "denominations": list(XOF_DENOMINATIONS), "lines": lines,
                   "totals": {"amount": int(batch["total"]), "counts": totals, "remainder": remainder_total}})
