"""Monthly inputs (bonus, canteen…), salary advances and loans — the one-off lines of a payslip.

Writes need payroll.manage_inputs (checked by the routes). What an approved or paid run already
deducted is frozen (RUN_LOCKED); a change that touches a calculated run sends it back to draft.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_state import EDITABLE, invalidate, lock_run, locked, not_found
from modules.payroll.domain.inputs import OneOffInput
from modules.payroll.domain.loans import instalment_schedule
from modules.payroll.domain.rules import ADVANCE, LOAN, SYSTEM_COMPONENTS

INPUT_FORMULAS = ("fixed", "qty_x_rate", "per_day")
_INPUT_COLUMNS = "id, run_id, employee_id, employee_no, full_name, component_code, qty, amount, note, created_by, created_at"
_ADVANCE_SELECT = """
    SELECT a.id, a.employee_id, a.employee_no, a.full_name, a.amount, a.requested_on, a.deduct_period, a.status,
           a.approved_by, a.approved_at, a.note, a.deducted_payslip_id, a.created_by, a.created_at,
           r.id AS deducted_run_id, r.period AS deducted_period, r.status AS deducted_run_status
    FROM payroll.advances a
    LEFT JOIN payroll.payslips p ON p.id = a.deducted_payslip_id
    LEFT JOIN payroll.runs r ON r.id = p.run_id
"""
_LOAN_COLUMNS = "id, employee_id, employee_no, full_name, principal, instalment_count, first_period, status, note, created_by, created_at"


def _invalid(english: str, french: str) -> Err:
    return Err("INPUT_INVALID", english, french)


def _amount_problem(qty: Decimal | None, amount: Decimal | None) -> Err | None:
    if qty is None and amount is None:
        return _invalid("give a quantity or an amount", "indiquez une quantité ou un montant")
    if (qty is not None and qty < 0) or (amount is not None and amount < 0):
        return _invalid("quantities and amounts are not negative", "les quantités et montants ne sont pas négatifs")
    if amount is not None and amount != amount.to_integral_value():
        return _invalid("the amount is in whole francs", "le montant s'exprime en francs entiers")
    return None


def _money_problem(amount: Decimal, name_en: str, name_fr: str) -> Err | None:
    if amount is None or amount <= 0 or amount != amount.to_integral_value():
        return _invalid(f"the {name_en} is a positive whole number of francs", f"le {name_fr} est un nombre entier positif de francs")
    return None


def _period_problem(period: datetime.date) -> Err | None:
    if period.day != 1:
        return _invalid("a payroll month is the first day of the month", "un mois de paie est le premier jour du mois")
    return None


class InputService:
    def __init__(self, connection: psycopg.Connection, *, snapshots: Any = None) -> None:
        self.connection = connection
        self.snapshots = snapshots if snapshots is not None else PayrollSnapshotService(connection)

    # -- shared checks ------------------------------------------------------------------------
    def _employee(self, tenant_id: str, period: datetime.date, employee_id: str) -> dict[str, Any] | None:
        found = self.snapshots.employees_for_period(tenant_id=tenant_id, period=period, employee_ids=[employee_id])
        return found[0] if found else None

    @staticmethod
    def _no_contract(period: datetime.date) -> Err:
        return Err("NOT_FOUND", f"this employee has no contract in {period:%Y-%m}", f"cet employé n'a pas de contrat en {period:%m/%Y}")

    def _typed_components(self, tenant_id: str, period: datetime.date) -> Result[dict[str, Any]]:
        rule_sets = RuleSetService(self.connection)
        in_force = rule_sets.in_force(tenant_id=tenant_id, period=period)
        if isinstance(in_force, Err):
            return in_force
        rules = rule_sets.load(tenant_id=tenant_id, rule_set_id=in_force.value["id"])
        return Ok({component.code: component for component in rules.components
                   if component.kind in ("earning", "deduction") and component.formula_type in INPUT_FORMULAS
                   and component.code not in SYSTEM_COMPONENTS})

    def _release(self, payslip_id: str | None) -> Err | None:
        """Frozen once an approved/paid run deducted it; a calculated run that took it goes back to draft."""
        if payslip_id is None:
            return None
        run = fetch_one(self.connection, "SELECT r.id, r.status FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id WHERE p.id = %s", (payslip_id,))
        if run is None:
            return None
        if run["status"] in ("approved", "paid"):
            return Err("RUN_LOCKED", "an approved run already deducted it; it can no longer change",
                       "une paie approuvée l'a déjà retenu ; il ne peut plus changer")
        invalidate(self.connection, run["id"])
        return None

    # -- monthly inputs -----------------------------------------------------------------------
    def input_components(self, *, tenant_id: str, run_id: str) -> Result[list[dict[str, Any]]]:
        run = fetch_one(self.connection, "SELECT period FROM payroll.runs WHERE tenant_id = %s AND id = %s", (tenant_id, run_id))
        if run is None:
            return not_found()
        typed = self._typed_components(tenant_id, run["period"])
        if isinstance(typed, Err):
            return typed
        return Ok([jsonable({"code": c.code, "name_en": c.name_en, "name_fr": c.name_fr, "kind": c.kind,
                             "formula_type": c.formula_type, "default_amount": c.default_amount})
                   for c in sorted(typed.value.values(), key=lambda item: (item.display_order, item.code))])

    def list_run_inputs(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection, f"SELECT {_INPUT_COLUMNS} FROM payroll.run_inputs WHERE tenant_id = %s AND run_id = %s ORDER BY full_name, component_code",
                                  (tenant_id, run_id)))

    def _input(self, tenant_id: str, input_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, f"SELECT {_INPUT_COLUMNS} FROM payroll.run_inputs WHERE tenant_id = %s AND id = %s", (tenant_id, input_id))

    def _check_input(self, tenant_id: str, period: datetime.date, code: str, qty, amount) -> Err | None:
        problem = _amount_problem(qty, amount)
        if problem is not None:
            return problem
        typed = self._typed_components(tenant_id, period)
        if isinstance(typed, Err):
            return typed
        if code not in typed.value:
            return _invalid(f"{code} cannot be typed as a monthly input", f"{code} ne se saisit pas en variable du mois")
        return None

    def add_run_input(self, *, tenant_id: str, actor_id: str, run_id: str, employee_id: str, component_code: str,
                      qty: Decimal | None = None, amount: Decimal | None = None, note: str | None = None) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        code = component_code.strip().upper()
        problem = self._check_input(tenant_id, run["period"], code, qty, amount)
        if problem is not None:
            return problem
        employee = self._employee(tenant_id, run["period"], employee_id)
        if employee is None:
            return self._no_contract(run["period"])
        input_id = str(ULID())
        self.connection.execute(
            "INSERT INTO payroll.run_inputs (id, tenant_id, run_id, employee_id, employee_no, full_name, component_code, qty, amount, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (input_id, tenant_id, run_id, employee_id, employee["employee_no"], employee["full_name"], code, qty, amount, note, actor_id),
        )
        invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="run_input.created", entity_type="run_input",
                     entity_id=input_id, payload=jsonable({"run_id": run_id, "employee_id": employee_id, "component_code": code, "qty": qty, "amount": amount}))
        return Ok(jsonable(self._input(tenant_id, input_id)))

    def update_run_input(self, *, tenant_id: str, actor_id: str, input_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._input(tenant_id, input_id)
        if current is None:
            return Err("NOT_FOUND", "input not found", "variable introuvable")
        unknown = sorted(set(changes) - {"component_code", "qty", "amount", "note"})
        if unknown:
            return _invalid(f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        run = lock_run(self.connection, tenant_id, current["run_id"])
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        merged = {key: current[key] for key in ("component_code", "qty", "amount", "note")} | changes
        code = str(merged["component_code"]).strip().upper()
        problem = self._check_input(tenant_id, run["period"], code, merged["qty"], merged["amount"])
        if problem is not None:
            return problem
        self.connection.execute("UPDATE payroll.run_inputs SET component_code = %s, qty = %s, amount = %s, note = %s WHERE id = %s",
                                (code, merged["qty"], merged["amount"], merged["note"], input_id))
        invalidate(self.connection, current["run_id"])
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="run_input.updated", entity_type="run_input",
                     entity_id=input_id, payload={"changes": jsonable(changes)})
        return Ok(jsonable(self._input(tenant_id, input_id)))

    def delete_run_input(self, *, tenant_id: str, actor_id: str, input_id: str) -> Result[dict[str, Any]]:
        current = self._input(tenant_id, input_id)
        if current is None:
            return Err("NOT_FOUND", "input not found", "variable introuvable")
        run = lock_run(self.connection, tenant_id, current["run_id"])
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        self.connection.execute("DELETE FROM payroll.run_inputs WHERE id = %s", (input_id,))
        invalidate(self.connection, current["run_id"])
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="run_input.deleted", entity_type="run_input",
                     entity_id=input_id, payload=jsonable({key: current[key] for key in ("run_id", "employee_id", "component_code", "qty", "amount")}))
        return Ok({"id": input_id})

    def run_inputs_by_employee(self, *, tenant_id: str, run_id: str) -> dict[str, list[OneOffInput]]:
        grouped: dict[str, list[OneOffInput]] = {}
        rows = fetch_all(self.connection, "SELECT id, employee_id, component_code, qty, amount FROM payroll.run_inputs WHERE tenant_id = %s AND run_id = %s ORDER BY created_at, id",
                         (tenant_id, run_id))
        for row in rows:
            grouped.setdefault(row["employee_id"], []).append(
                OneOffInput(component_code=row["component_code"], qty=row["qty"], amount=row["amount"], source_kind="input", source_id=row["id"]))
        return grouped

    # -- advances -----------------------------------------------------------------------------
    def list_advances(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["a.tenant_id = %s"], [tenant_id]
        if status:
            clauses.append("a.status = %s")
            params.append(status)
        return jsonable(fetch_all(self.connection, _ADVANCE_SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY a.deduct_period DESC, a.full_name", params))

    def _advance(self, tenant_id: str, advance_id: str, *, lock: bool = False) -> dict[str, Any] | None:
        sql = "SELECT * FROM payroll.advances WHERE tenant_id = %s AND id = %s" + (" FOR UPDATE" if lock else "")
        return fetch_one(self.connection, sql, (tenant_id, advance_id))

    def _advance_view(self, tenant_id: str, advance_id: str) -> dict[str, Any]:
        return jsonable(fetch_one(self.connection, _ADVANCE_SELECT + " WHERE a.tenant_id = %s AND a.id = %s", (tenant_id, advance_id)))

    def create_advance(self, *, tenant_id: str, actor_id: str, employee_id: str, amount: Decimal, requested_on: datetime.date,
                       deduct_period: datetime.date, note: str | None = None) -> Result[dict[str, Any]]:
        problem = _money_problem(amount, "amount", "montant") or _period_problem(deduct_period)
        if problem is not None:
            return problem
        employee = self._employee(tenant_id, deduct_period, employee_id)
        if employee is None:
            return self._no_contract(deduct_period)
        advance_id = str(ULID())
        self.connection.execute(
            "INSERT INTO payroll.advances (id, tenant_id, employee_id, employee_no, full_name, amount, requested_on, deduct_period, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (advance_id, tenant_id, employee_id, employee["employee_no"], employee["full_name"], amount, requested_on, deduct_period, note, actor_id),
        )
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="advance.created", entity_type="advance", entity_id=advance_id,
                     payload=jsonable({"employee_id": employee_id, "amount": amount, "deduct_period": deduct_period}))
        return Ok(self._advance_view(tenant_id, advance_id))

    def update_advance(self, *, tenant_id: str, actor_id: str, advance_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._advance(tenant_id, advance_id, lock=True)
        if current is None:
            return Err("NOT_FOUND", "advance not found", "avance introuvable")
        if current["status"] == "cancelled":
            return _invalid("a cancelled advance cannot change", "une avance annulée ne peut plus changer")
        unknown = sorted(set(changes) - {"amount", "requested_on", "deduct_period", "note"})
        if unknown:
            return _invalid(f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        released = self._release(current["deducted_payslip_id"])
        if released is not None:
            return released
        merged = {key: current[key] for key in ("amount", "requested_on", "deduct_period", "note")} | changes
        problem = _money_problem(merged["amount"], "amount", "montant") or _period_problem(merged["deduct_period"])
        if problem is not None:
            return problem
        self.connection.execute("UPDATE payroll.advances SET amount = %s, requested_on = %s, deduct_period = %s, note = %s WHERE id = %s",
                                (merged["amount"], merged["requested_on"], merged["deduct_period"], merged["note"], advance_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="advance.updated", entity_type="advance",
                     entity_id=advance_id, payload={"changes": jsonable(changes)})
        return Ok(self._advance_view(tenant_id, advance_id))

    def approve_advance(self, *, tenant_id: str, actor_id: str, advance_id: str) -> Result[dict[str, Any]]:
        current = self._advance(tenant_id, advance_id, lock=True)
        if current is None:
            return Err("NOT_FOUND", "advance not found", "avance introuvable")
        if current["status"] != "requested":
            return _invalid("only a requested advance can be approved", "seule une avance demandée peut être approuvée")
        self.connection.execute("UPDATE payroll.advances SET status = 'approved', approved_by = %s, approved_at = NOW() WHERE id = %s", (actor_id, advance_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="advance.approved", entity_type="advance",
                     entity_id=advance_id, payload={"from_status": "requested", "to_status": "approved"})
        return Ok(self._advance_view(tenant_id, advance_id))

    def cancel_advance(self, *, tenant_id: str, actor_id: str, advance_id: str) -> Result[dict[str, Any]]:
        current = self._advance(tenant_id, advance_id, lock=True)
        if current is None:
            return Err("NOT_FOUND", "advance not found", "avance introuvable")
        if current["status"] == "cancelled":
            return _invalid("this advance is already cancelled", "cette avance est déjà annulée")
        released = self._release(current["deducted_payslip_id"])
        if released is not None:
            return released
        self.connection.execute("UPDATE payroll.advances SET status = 'cancelled', deducted_payslip_id = NULL WHERE id = %s", (advance_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="advance.cancelled", entity_type="advance",
                     entity_id=advance_id, payload={"from_status": current["status"], "to_status": "cancelled"})
        return Ok(self._advance_view(tenant_id, advance_id))

    # -- loans --------------------------------------------------------------------------------
    def list_loans(self, *, tenant_id: str, status: str | None = None, loan_id: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s"], [tenant_id]
        if status:
            clauses.append("status = %s")
            params.append(status)
        if loan_id:
            clauses.append("id = %s")
            params.append(loan_id)
        loans = fetch_all(self.connection, f"SELECT {_LOAN_COLUMNS} FROM payroll.loans WHERE {' AND '.join(clauses)} ORDER BY first_period DESC, full_name", params)
        instalments = fetch_all(
            self.connection,
            """
            SELECT i.id, i.loan_id, i.seq, i.period, i.amount, r.id AS run_id, r.status AS run_status
            FROM payroll.loan_instalments i
            JOIN payroll.loans l ON l.id = i.loan_id
            LEFT JOIN payroll.payslips p ON p.id = i.payslip_id
            LEFT JOIN payroll.runs r ON r.id = p.run_id
            WHERE l.tenant_id = %s
            ORDER BY i.loan_id, i.seq
            """,
            (tenant_id,),
        )
        by_loan: dict[str, list[dict[str, Any]]] = {}
        for item in instalments:
            item["deducted"] = item["run_status"] in ("approved", "paid")
            by_loan.setdefault(item["loan_id"], []).append(item)
        for loan in loans:
            loan["instalments"] = by_loan.get(loan["id"], [])
            loan["remaining"] = (sum((item["amount"] for item in loan["instalments"] if not item["deducted"]), Decimal(0))
                                 if loan["status"] == "active" else Decimal(0))
        return jsonable(loans)

    def _loan(self, tenant_id: str, loan_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, f"SELECT {_LOAN_COLUMNS} FROM payroll.loans WHERE tenant_id = %s AND id = %s FOR UPDATE", (tenant_id, loan_id))

    def _schedule(self, tenant_id: str, loan_id: str, principal: Decimal, count: int, first_period: datetime.date) -> None:
        for item in instalment_schedule(principal, count, first_period):
            self.connection.execute("INSERT INTO payroll.loan_instalments (id, tenant_id, loan_id, seq, period, amount) VALUES (%s, %s, %s, %s, %s, %s)",
                                    (str(ULID()), tenant_id, loan_id, item.seq, item.period, item.amount))

    @staticmethod
    def _loan_problem(principal: Decimal, count: int, first_period: datetime.date) -> Err | None:
        problem = _money_problem(principal, "principal", "capital") or _period_problem(first_period)
        if problem is not None:
            return problem
        if count < 1 or principal < count:
            return _invalid("a loan has at least one instalment of at least one franc", "un prêt a au moins une échéance d'au moins un franc")
        return None

    def create_loan(self, *, tenant_id: str, actor_id: str, employee_id: str, principal: Decimal, instalment_count: int,
                    first_period: datetime.date, note: str | None = None) -> Result[dict[str, Any]]:
        problem = self._loan_problem(principal, instalment_count, first_period)
        if problem is not None:
            return problem
        employee = self._employee(tenant_id, first_period, employee_id)
        if employee is None:
            return self._no_contract(first_period)
        loan_id = str(ULID())
        self.connection.execute(
            "INSERT INTO payroll.loans (id, tenant_id, employee_id, employee_no, full_name, principal, instalment_count, first_period, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (loan_id, tenant_id, employee_id, employee["employee_no"], employee["full_name"], principal, instalment_count, first_period, note, actor_id),
        )
        self._schedule(tenant_id, loan_id, principal, instalment_count, first_period)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="loan.created", entity_type="loan", entity_id=loan_id,
                     payload=jsonable({"employee_id": employee_id, "principal": principal, "instalment_count": instalment_count, "first_period": first_period}))
        return Ok(self.list_loans(tenant_id=tenant_id, loan_id=loan_id)[0])

    def _release_instalments(self, loan_id: str) -> Err | None:
        taken = fetch_all(self.connection, "SELECT r.id, r.status FROM payroll.loan_instalments i JOIN payroll.payslips p ON p.id = i.payslip_id "
                                           "JOIN payroll.runs r ON r.id = p.run_id WHERE i.loan_id = %s", (loan_id,))
        if any(run["status"] in ("approved", "paid") for run in taken):
            return Err("RUN_LOCKED", "instalments were already deducted; cancel the loan and open a new one for the balance",
                       "des échéances ont déjà été retenues ; annulez le prêt et ouvrez-en un nouveau pour le solde")
        for run in taken:
            invalidate(self.connection, run["id"])
        return None

    def update_loan(self, *, tenant_id: str, actor_id: str, loan_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._loan(tenant_id, loan_id)
        if current is None:
            return Err("NOT_FOUND", "loan not found", "prêt introuvable")
        if current["status"] == "cancelled":
            return _invalid("a cancelled loan cannot change", "un prêt annulé ne peut plus changer")
        unknown = sorted(set(changes) - {"principal", "instalment_count", "first_period", "note"})
        if unknown:
            return _invalid(f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        merged = {key: current[key] for key in ("principal", "instalment_count", "first_period", "note")} | changes
        problem = self._loan_problem(merged["principal"], int(merged["instalment_count"]), merged["first_period"])
        if problem is not None:
            return problem
        released = self._release_instalments(loan_id)
        if released is not None:
            return released
        self.connection.execute("DELETE FROM payroll.loan_instalments WHERE loan_id = %s", (loan_id,))
        self.connection.execute("UPDATE payroll.loans SET principal = %s, instalment_count = %s, first_period = %s, note = %s WHERE id = %s",
                                (merged["principal"], merged["instalment_count"], merged["first_period"], merged["note"], loan_id))
        self._schedule(tenant_id, loan_id, merged["principal"], int(merged["instalment_count"]), merged["first_period"])
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="loan.updated", entity_type="loan", entity_id=loan_id,
                     payload={"changes": jsonable(changes)})
        return Ok(self.list_loans(tenant_id=tenant_id, loan_id=loan_id)[0])

    def cancel_loan(self, *, tenant_id: str, actor_id: str, loan_id: str) -> Result[dict[str, Any]]:
        current = self._loan(tenant_id, loan_id)
        if current is None:
            return Err("NOT_FOUND", "loan not found", "prêt introuvable")
        if current["status"] == "cancelled":
            return _invalid("this loan is already cancelled", "ce prêt est déjà annulé")
        calculated = fetch_all(self.connection, "SELECT DISTINCT r.id FROM payroll.loan_instalments i JOIN payroll.payslips p ON p.id = i.payslip_id "
                                                "JOIN payroll.runs r ON r.id = p.run_id WHERE i.loan_id = %s AND r.status = 'calculated'", (loan_id,))
        for run in calculated:
            invalidate(self.connection, run["id"])
        # instalments an approved run deducted stay as history; the open ones go
        self.connection.execute("DELETE FROM payroll.loan_instalments WHERE loan_id = %s AND payslip_id IS NULL", (loan_id,))
        self.connection.execute("UPDATE payroll.loans SET status = 'cancelled' WHERE id = %s", (loan_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="loan.cancelled", entity_type="loan", entity_id=loan_id,
                     payload={"from_status": "active", "to_status": "cancelled"})
        return Ok(self.list_loans(tenant_id=tenant_id, loan_id=loan_id)[0])

    # -- what the engine is offered ---------------------------------------------------------------
    def due_deductions(self, *, tenant_id: str, period: datetime.date, employee_ids: list[str],
                       settle_ids: set[str]) -> dict[str, list[OneOffInput]]:
        if not employee_ids:
            return {}
        settle = sorted(settle_ids)
        grouped: dict[str, list[OneOffInput]] = {}

        def add(employee_id: str, item: OneOffInput) -> None:
            grouped.setdefault(employee_id, []).append(item)

        carried = fetch_all(
            self.connection,
            """
            SELECT cf.id, cf.employee_id, cf.component_code, cf.amount
            FROM payroll.carry_forwards cf
            JOIN payroll.payslips p ON p.id = cf.source_payslip_id
            JOIN payroll.runs r ON r.id = p.run_id
            WHERE cf.tenant_id = %s AND cf.consumed_by_payslip_id IS NULL AND r.status IN ('approved', 'paid')
              AND cf.employee_id = ANY(%s::text[])
            ORDER BY cf.created_at, cf.id
            """,
            (tenant_id, employee_ids),
        )
        for row in carried:
            add(row["employee_id"], OneOffInput(row["component_code"], amount=row["amount"], source_kind="carry_forward", source_id=row["id"]))
        instalments = fetch_all(
            self.connection,
            """
            SELECT i.id, l.employee_id, i.amount
            FROM payroll.loan_instalments i JOIN payroll.loans l ON l.id = i.loan_id
            WHERE l.tenant_id = %s AND l.status = 'active' AND i.payslip_id IS NULL AND l.employee_id = ANY(%s::text[])
              AND (i.period <= %s OR l.employee_id = ANY(%s::text[]))
            ORDER BY i.period, i.seq
            """,
            (tenant_id, employee_ids, period, settle),
        )
        for row in instalments:
            add(row["employee_id"], OneOffInput(LOAN, amount=row["amount"], source_kind="loan_instalment", source_id=row["id"]))
        advances = fetch_all(
            self.connection,
            """
            SELECT id, employee_id, amount FROM payroll.advances
            WHERE tenant_id = %s AND status = 'approved' AND deducted_payslip_id IS NULL AND employee_id = ANY(%s::text[])
              AND (deduct_period <= %s OR employee_id = ANY(%s::text[]))
            ORDER BY deduct_period, created_at
            """,
            (tenant_id, employee_ids, period, settle),
        )
        for row in advances:
            add(row["employee_id"], OneOffInput(ADVANCE, amount=row["amount"], source_kind="advance", source_id=row["id"]))
        return grouped
