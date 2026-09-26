"""Employment contracts: create, edit, activate, end and amend. The one-signed-contract-per-day
rule is checked here first (a readable refusal) and enforced again by the database
(hr_contracts_no_overlap, migration 0007)."""
from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload, execute_guarded, iso_dates, missing_reference
from modules.hr.domain.contract import (
    COLUMNS,
    ContractComponent,
    ContractPeriod,
    ContractTerms,
    end_status,
    overlap_refusal,
    overlapping,
    validate_terms,
)
from modules.hr.domain.employee import END_REASONS
from modules.hr.domain.sensitive import CONTRACT_WRITE_FIELDS

_NOT_FOUND = Err("NOT_FOUND", "contract not found", "contrat introuvable")
_OVERLAP_GUARD = {
    "hr_contracts_no_overlap": Err(
        "CONTRACT_OVERLAP", "the employee already has a signed contract on those days", "l'employé a déjà un contrat signé sur ces jours"
    )
}
# An edit may change everything but the person and the contract an amendment replaced.
_EDITABLE = {name for name in COLUMNS if name not in ("employee_id", "amends_contract_id")} | {"components"}
_AMENDABLE = {"contract_type", "end_date", "weekly_hours", "base_salary", "pay_frequency", "position_id", "grade_id", "components"}
_C_COLUMNS = ", ".join(f"c.{name}" for name in COLUMNS)
_SELECT = f"""
    SELECT c.id, {_C_COLUMNS}, c.currency, e.first_name || ' ' || e.last_name, p.title, g.code
    FROM hr.contracts c
    JOIN hr.employees e ON e.id = c.employee_id
    LEFT JOIN hr.positions p ON p.id = c.position_id
    LEFT JOIN hr.grades g ON g.id = c.grade_id
"""
# salary mirrors base_salary for the legacy payroll screen; every new contract is in XOF.
_INSERT = f"INSERT INTO hr.contracts (id, tenant_id, {', '.join(COLUMNS)}, salary, currency) VALUES ({', '.join(['%s'] * (len(COLUMNS) + 4))})"
_UPDATE = "UPDATE hr.contracts SET " + ", ".join(f"{name} = %s" for name in COLUMNS) + ", salary = %s WHERE id = %s AND tenant_id = %s"


def _components_of(values) -> tuple[ContractComponent, ...]:
    return tuple(value if isinstance(value, ContractComponent) else ContractComponent(**value) for value in (values or ()))


class ContractService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # ---- reads ----------------------------------------------------------------------------------

    def list_contracts(self, tenant_id: str, employee_id: str | None = None) -> list[dict]:
        params: list[object] = [tenant_id]
        clause = "WHERE c.tenant_id = %s"
        if employee_id:
            clause += " AND c.employee_id = %s"
            params.append(employee_id)
        rows = self.connection.execute(f"{_SELECT} {clause} ORDER BY c.start_date DESC, c.created_at DESC", params).fetchall()
        return self._records(rows)

    def get_contract(self, *, tenant_id: str, contract_id: str) -> dict | None:
        rows = self.connection.execute(f"{_SELECT} WHERE c.tenant_id = %s AND c.id = %s", (tenant_id, contract_id)).fetchall()
        records = self._records(rows)
        return records[0] if records else None

    def _records(self, rows) -> list[dict]:
        components = self._components([row[0] for row in rows])
        count = len(COLUMNS)
        records: list[dict] = []
        for row in rows:
            terms = dict(zip(COLUMNS, row[1 : 1 + count]))
            currency, employee_name, position_title, grade_code = row[1 + count :]
            records.append(
                {
                    "id": row[0],
                    **iso_dates(terms),
                    "currency": currency,
                    "employee_name": employee_name,
                    "position_title": position_title,
                    "grade_code": grade_code,
                    "components": [
                        {"component_code": item.component_code, "amount": item.amount, "rate": item.rate} for item in components.get(row[0], ())
                    ],
                }
            )
        return records

    def _components(self, contract_ids: Sequence[str]) -> dict[str, tuple[ContractComponent, ...]]:
        if not contract_ids:
            return {}
        rows = self.connection.execute(
            "SELECT contract_id, component_code, amount, rate FROM hr.contract_components WHERE contract_id = ANY(%s) ORDER BY component_code",
            (list(contract_ids),),
        ).fetchall()
        found: dict[str, list[ContractComponent]] = {}
        for contract_id, code, amount, rate in rows:
            found.setdefault(contract_id, []).append(ContractComponent(component_code=code, amount=amount, rate=rate))
        return {contract_id: tuple(items) for contract_id, items in found.items()}

    def _locked_terms(self, tenant_id: str, contract_id: str) -> ContractTerms | None:
        row = self.connection.execute(
            f"SELECT {', '.join(COLUMNS)} FROM hr.contracts WHERE id = %s AND tenant_id = %s FOR UPDATE", (contract_id, tenant_id)
        ).fetchone()
        if row is None:
            return None
        return ContractTerms(*row, components=self._components([contract_id]).get(contract_id, ()))

    # ---- checks ---------------------------------------------------------------------------------

    def _check_employee(self, tenant_id: str, employee_id: str) -> Err | None:
        """The employee exists and has not left. Locking the row serialises two writes on the
        same person's contracts."""
        row = self.connection.execute(
            "SELECT status FROM hr.employees WHERE id = %s AND tenant_id = %s FOR UPDATE", (employee_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "employee not found", "employé introuvable")
        if row[0] == "terminated":
            return Err(
                "EMPLOYEE_TERMINATED",
                "this employee has left; a new contract needs a new hire",
                "cet employé est sorti ; un nouveau contrat demande une nouvelle embauche",
            )
        return None

    def _check_references(self, tenant_id: str, terms: ContractTerms) -> Err | None:
        return missing_reference(self.connection, "hr.positions", tenant_id, terms.position_id, "position", "poste") or missing_reference(
            self.connection, "hr.grades", tenant_id, terms.grade_id, "grade", "catégorie"
        )

    def _check_overlap(self, tenant_id: str, contract_id: str, terms: ContractTerms) -> Err | None:
        rows = self.connection.execute(
            "SELECT id, start_date, end_date, status FROM hr.contracts WHERE tenant_id = %s AND employee_id = %s",
            (tenant_id, terms.employee_id),
        ).fetchall()
        candidate = ContractPeriod(id=contract_id, start_date=terms.start_date, end_date=terms.end_date, status=terms.status)
        clash = overlapping(candidate, [ContractPeriod(*row) for row in rows])
        return None if clash is None else overlap_refusal(clash)

    # ---- writes ---------------------------------------------------------------------------------

    def _write_components(self, tenant_id: str, contract_id: str, components: Sequence[ContractComponent]) -> None:
        self.connection.execute("DELETE FROM hr.contract_components WHERE contract_id = %s AND tenant_id = %s", (contract_id, tenant_id))
        for component in components:
            self.connection.execute(
                "INSERT INTO hr.contract_components (id, tenant_id, contract_id, component_code, amount, rate) VALUES (%s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, contract_id, component.component_code, component.amount, component.rate),
            )

    def _insert(self, *, tenant_id: str, actor_id: str, terms: ContractTerms) -> Result[str]:
        contract_id = str(ULID())
        refused = self._check_overlap(tenant_id, contract_id, terms)
        if refused:
            return refused
        refused = execute_guarded(
            self.connection,
            _INSERT,
            (contract_id, tenant_id, *(getattr(terms, name) for name in COLUMNS), terms.base_salary, "XOF"),
            _OVERLAP_GUARD,
        )
        if refused:
            return refused
        self._write_components(tenant_id, contract_id, terms.components)
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="contract.created",
            entity_type="contract",
            entity_id=contract_id,
            payload={
                "employee_id": terms.employee_id,
                "contract_type": terms.contract_type,
                "start_date": terms.start_date.isoformat(),
                "end_date": terms.end_date.isoformat() if terms.end_date else None,
                "status": terms.status,
                "amends_contract_id": terms.amends_contract_id,
                "sensitive_set": [name for name in CONTRACT_WRITE_FIELDS if getattr(terms, name)],
            },
        )
        return Ok(contract_id)

    def _close(
        self, *, tenant_id: str, actor_id: str, contract_id: str, current: ContractTerms, end_date: datetime.date, end_reason: str
    ) -> None:
        to_status = end_status(end_reason)
        self.connection.execute(
            "UPDATE hr.contracts SET end_date = %s, end_reason = %s, status = %s WHERE id = %s AND tenant_id = %s",
            (end_date, end_reason, to_status, contract_id, tenant_id),
        )
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="contract.ended",
            entity_type="contract",
            entity_id=contract_id,
            payload={
                "from_status": current.status,
                "to_status": to_status,
                "end_date": end_date.isoformat(),
                "end_reason": end_reason,
                "agreed_end_date": current.end_date.isoformat() if current.end_date else None,
            },
        )

    def create_contract(self, *, tenant_id: str, actor_id: str, terms: ContractTerms) -> Result[dict]:
        if terms.status not in ("draft", "active"):
            return Err("INVALID_STATUS", "a new contract is a draft or active", "un nouveau contrat est brouillon ou actif")
        if terms.end_reason is not None or terms.amends_contract_id is not None:
            return Err(
                "INVALID_CONTRACT",
                "a new contract has no end reason and amends nothing; use end or amend",
                "un nouveau contrat n'a ni motif de fin ni avenant ; utilisez la fin de contrat ou l'avenant",
            )
        validated = validate_terms(terms)
        if isinstance(validated, Err):
            return validated
        refused = self._check_employee(tenant_id, terms.employee_id) or self._check_references(tenant_id, validated.value)
        if refused:
            return refused
        inserted = self._insert(tenant_id=tenant_id, actor_id=actor_id, terms=validated.value)
        if isinstance(inserted, Err):
            return inserted
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=inserted.value))

    def update_contract(self, *, tenant_id: str, actor_id: str, contract_id: str, changes: Mapping[str, object]) -> Result[dict]:
        """Edit in place (hr.admin_contracts): any term, whatever the status."""
        unknown = sorted(set(changes) - _EDITABLE)
        if unknown:
            return Err("INVALID_CONTRACT", f"these fields cannot be edited: {', '.join(unknown)}", f"ces champs ne sont pas modifiables : {', '.join(unknown)}")
        current = self._locked_terms(tenant_id, contract_id)
        if current is None:
            return _NOT_FOUND
        updates = dict(changes)
        if "components" in updates:
            updates["components"] = _components_of(updates["components"])
        validated = validate_terms(replace(current, **updates))
        if isinstance(validated, Err):
            return validated
        candidate = validated.value
        refused = self._check_references(tenant_id, candidate) or self._check_overlap(tenant_id, contract_id, candidate)
        if refused:
            return refused
        refused = execute_guarded(
            self.connection,
            _UPDATE,
            (*(getattr(candidate, name) for name in COLUMNS), candidate.base_salary, contract_id, tenant_id),
            _OVERLAP_GUARD,
        )
        if refused:
            return refused
        if "components" in updates:
            self._write_components(tenant_id, contract_id, candidate.components)
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="contract.updated",
            entity_type="contract",
            entity_id=contract_id,
            payload=change_payload(asdict(current), asdict(candidate), CONTRACT_WRITE_FIELDS),
        )
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=contract_id))

    def activate_contract(self, *, tenant_id: str, actor_id: str, contract_id: str) -> Result[dict]:
        current = self._locked_terms(tenant_id, contract_id)
        if current is None:
            return _NOT_FOUND
        if current.status != "draft":
            return Err("INVALID_TRANSITION", "only a draft contract can be activated", "seul un contrat brouillon peut être activé")
        refused = self._check_employee(tenant_id, current.employee_id) or self._check_overlap(
            tenant_id, contract_id, replace(current, status="active")
        )
        if refused:
            return refused
        refused = execute_guarded(
            self.connection, "UPDATE hr.contracts SET status = 'active' WHERE id = %s AND tenant_id = %s", (contract_id, tenant_id), _OVERLAP_GUARD
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="contract.activated",
            entity_type="contract", entity_id=contract_id, payload={"from_status": "draft", "to_status": "active"},
        )
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=contract_id))

    def end_contract(
        self, *, tenant_id: str, actor_id: str, contract_id: str, end_date: datetime.date, end_reason: str
    ) -> Result[dict]:
        current = self._locked_terms(tenant_id, contract_id)
        if current is None:
            return _NOT_FOUND
        if current.status != "active":
            return Err("INVALID_TRANSITION", "only an active contract can be ended", "seul un contrat actif peut prendre fin")
        if end_reason == "amended" or end_reason not in END_REASONS:
            return Err(
                "INVALID_END_REASON",
                "choose why the contract ends (an amendment ends it through the amendment itself)",
                "choisissez le motif de fin (un avenant y met fin de lui-même)",
            )
        if end_date < current.start_date:
            return Err("INVALID_DATES", "a contract cannot end before it starts", "un contrat ne peut pas finir avant de commencer")
        if current.end_date is not None and end_date > current.end_date:
            return Err(
                "INVALID_DATES",
                "a contract cannot end after its agreed end date; record an amendment to extend it",
                "un contrat ne peut pas finir après sa date de fin prévue ; faites un avenant pour le prolonger",
            )
        self._close(tenant_id=tenant_id, actor_id=actor_id, contract_id=contract_id, current=current, end_date=end_date, end_reason=end_reason)
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=contract_id))

    def amend_contract(
        self, *, tenant_id: str, actor_id: str, contract_id: str, effective_date: datetime.date, changes: Mapping[str, object]
    ) -> Result[dict]:
        """An avenant: the current terms end the day before `effective_date` and a new active
        contract carries them on from that day with `changes` applied. The trial period is not
        carried over; the allowances are, unless `changes` replaces them."""
        unknown = sorted(set(changes) - _AMENDABLE)
        if unknown:
            return Err("INVALID_CONTRACT", f"an amendment cannot change: {', '.join(unknown)}", f"un avenant ne peut pas modifier : {', '.join(unknown)}")
        current = self._locked_terms(tenant_id, contract_id)
        if current is None:
            return _NOT_FOUND
        if current.status != "active":
            return Err("INVALID_TRANSITION", "only an active contract can be amended", "seul un contrat actif peut faire l'objet d'un avenant")
        if effective_date <= current.start_date or (current.end_date is not None and effective_date > current.end_date):
            return Err(
                "INVALID_DATES",
                "an amendment takes effect after the contract starts and before it ends",
                "un avenant prend effet après le début du contrat et avant sa fin",
            )
        updates = dict(changes)
        if "components" in updates:
            updates["components"] = _components_of(updates["components"])
        validated = validate_terms(
            replace(current, start_date=effective_date, trial_end_date=None, status="active", amends_contract_id=contract_id, end_reason=None, **updates)
        )
        if isinstance(validated, Err):
            return validated
        refused = self._check_employee(tenant_id, current.employee_id) or self._check_references(tenant_id, validated.value)
        if refused:
            return refused
        self._close(
            tenant_id=tenant_id, actor_id=actor_id, contract_id=contract_id, current=current,
            end_date=effective_date - datetime.timedelta(days=1), end_reason="amended",
        )
        inserted = self._insert(tenant_id=tenant_id, actor_id=actor_id, terms=validated.value)
        if isinstance(inserted, Err):
            return inserted
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=inserted.value))
