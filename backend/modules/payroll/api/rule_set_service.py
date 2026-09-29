"""Rule sets: the payroll country, the effective-dated rule tables, and their confirmation.

A draft rule set is edited in place (payroll.manage_rules). Confirming it (payroll.confirm_rules)
checks it is complete and freezes it: every change is then refused with RULESET_LOCKED, because
payslips are computed from it. Table and column names below are constants, never user input.
"""
from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.domain.rule_validation import (
    COUNTRY,
    check_complete,
    relief_from_parameters,
    validate_component,
    validate_contribution,
    validate_overtime_rate,
    validate_rule_set_header,
    validate_seniority_step,
    validate_severance_step,
    validate_tax_bracket,
    validate_tax_relief,
)
from modules.payroll.domain.rules import (
    ComponentRule,
    ContributionRule,
    FamilyRelief,
    OvertimeRate,
    ProfessionalRelief,
    RuleSet,
    SeniorityStep,
    SeveranceStep,
    TaxBracket,
)


@dataclass(frozen=True)
class ChildSpec:
    table: str
    columns: tuple[str, ...]
    validate: Callable[[dict[str, Any]], Result[dict[str, Any]]]
    order_by: str
    label_en: str
    label_fr: str
    json_columns: tuple[str, ...] = ()


CHILD_KINDS: dict[str, ChildSpec] = {
    "components": ChildSpec(
        "payroll.components",
        ("code", "name_en", "name_fr", "kind", "taxable", "contributable", "formula_type", "base_ref",
         "default_amount", "default_rate", "display_order", "payslip_section", "declaration_code"),
        validate_component, "display_order, code", "component", "rubrique"),
    "contributions": ChildSpec(
        "payroll.contributions",
        ("code", "name_en", "name_fr", "base", "employee_rate", "employer_rate", "ceiling_monthly",
         "deductible_from_taxable", "declaration_code", "liability_account_code", "display_order"),
        validate_contribution, "display_order, code", "contribution", "cotisation"),
    "tax_brackets": ChildSpec(
        "payroll.tax_brackets", ("tax_code", "lower_bound", "upper_bound", "rate", "annualised"),
        validate_tax_bracket, "tax_code, lower_bound", "tax bracket", "tranche d'impôt"),
    "tax_reliefs": ChildSpec(
        "payroll.tax_reliefs", ("tax_code", "kind", "parameters"),
        validate_tax_relief, "tax_code, kind", "tax relief", "abattement", json_columns=("parameters",)),
    "seniority_scale": ChildSpec(
        "payroll.seniority_scale", ("years_from", "percent"),
        validate_seniority_step, "years_from", "seniority step", "palier d'ancienneté"),
    "overtime_rates": ChildSpec(
        "payroll.overtime_rates", ("band_code", "multiplier"),
        validate_overtime_rate, "band_code", "overtime rate", "taux d'heures supplémentaires"),
    "severance_scale": ChildSpec(
        "payroll.severance_scale", ("years_from", "percent_per_year"),
        validate_severance_step, "years_from", "severance step", "palier d'indemnité de licenciement"),
}

HEADER_COLUMNS = (
    "country", "name", "valid_from", "round_to", "round_mode", "tax_round_to", "tax_round_mode",
    "working_days_per_month", "working_hours_per_month", "settlement_reference_months", "notes",
)
_HEADER_SELECT = (
    f"SELECT id, status, confirmed_by, confirmed_at, created_by, created_at, {', '.join(HEADER_COLUMNS)} "
    "FROM payroll.rule_sets"
)


def _not_found(what_en: str, what_fr: str) -> Err:
    return Err("NOT_FOUND", f"{what_en} not found", f"{what_fr} introuvable")


def _locked() -> Err:
    return Err("RULESET_LOCKED", "a confirmed rule set cannot be changed; copy it to a new draft or reopen it",
               "un jeu de règles confirmé ne peut pas être modifié ; copiez-le en brouillon ou rouvrez-le")


def _duplicate(spec: ChildSpec) -> Err:
    return Err("DUPLICATE_RULE", f"duplicate {spec.label_en} in this rule set", f"{spec.label_fr} en double dans ce jeu de règles")


def _duplicate_start(clean: dict[str, Any]) -> Err:
    country, start = clean["country"], clean["valid_from"]
    return Err("DUPLICATE_RULESET", f"a {country} rule set already starts in {start:%Y-%m}",
               f"un jeu de règles {country} commence déjà en {start:%m/%Y}")


class RuleSetService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # -- payroll country and employer identifiers -------------------------------------------
    def get_settings(self, *, tenant_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            "SELECT tenant_id, country, company_address, employer_inps_no, employer_tax_id FROM payroll.settings WHERE tenant_id = %s",
            (tenant_id,),
        )

    def save_settings(self, *, tenant_id: str, actor_id: str, country: str, company_address: str | None = None,
                      employer_inps_no: str | None = None, employer_tax_id: str | None = None) -> Result[dict[str, Any]]:
        code = (country or "").strip().upper()
        if not COUNTRY.match(code):
            return Err("RULE_INVALID", "country is a two-letter ISO code (e.g. ML)", "le pays est un code ISO à deux lettres (ex. ML)")
        self.connection.execute(
            """
            INSERT INTO payroll.settings (tenant_id, country, company_address, employer_inps_no, employer_tax_id, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                country = EXCLUDED.country, company_address = EXCLUDED.company_address,
                employer_inps_no = EXCLUDED.employer_inps_no, employer_tax_id = EXCLUDED.employer_tax_id,
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (tenant_id, code, company_address, employer_inps_no, employer_tax_id, actor_id),
        )
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_settings.updated",
                     entity_type="payroll_settings", entity_id=tenant_id,
                     payload={"country": code, "company_address": company_address,
                              "employer_inps_no": employer_inps_no, "employer_tax_id": employer_tax_id})
        return Ok(self.get_settings(tenant_id=tenant_id))

    # -- rule set headers ------------------------------------------------------------------------
    def _header(self, tenant_id: str, rule_set_id: str, *, lock: bool = False) -> dict[str, Any] | None:
        return fetch_one(self.connection, _HEADER_SELECT + " WHERE tenant_id = %s AND id = %s" + (" FOR UPDATE" if lock else ""),
                         (tenant_id, rule_set_id))

    def list_rule_sets(self, *, tenant_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection, _HEADER_SELECT + " WHERE tenant_id = %s ORDER BY country, valid_from DESC", (tenant_id,)))

    def get_rule_set(self, *, tenant_id: str, rule_set_id: str) -> dict[str, Any] | None:
        header = self._header(tenant_id, rule_set_id)
        if header is None:
            return None
        document = jsonable(header)
        for kind in CHILD_KINDS:
            document[kind] = self.list_children(tenant_id=tenant_id, rule_set_id=rule_set_id, kind=kind)
        return document

    def create_rule_set(self, *, tenant_id: str, actor_id: str, country: str, name: str, valid_from: datetime.date,
                        working_days_per_month, working_hours_per_month, round_to: int = 1, round_mode: str = "half_up",
                        tax_round_to: int = 1, tax_round_mode: str = "half_up", settlement_reference_months: int = 12,
                        notes: str | None = None) -> Result[dict[str, Any]]:
        checked = validate_rule_set_header({
            "country": country, "name": name, "valid_from": valid_from, "round_to": round_to, "round_mode": round_mode,
            "tax_round_to": tax_round_to, "tax_round_mode": tax_round_mode,
            "working_days_per_month": working_days_per_month, "working_hours_per_month": working_hours_per_month,
            "settlement_reference_months": settlement_reference_months, "notes": notes,
        })
        if isinstance(checked, Err):
            return checked
        clean = checked.value
        rule_set_id = str(ULID())
        try:
            with self.connection.transaction():
                self.connection.execute(
                    f"INSERT INTO payroll.rule_sets (id, tenant_id, created_by, {', '.join(HEADER_COLUMNS)}) "
                    f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(HEADER_COLUMNS))})",
                    (rule_set_id, tenant_id, actor_id, *(clean[column] for column in HEADER_COLUMNS)),
                )
        except psycopg.errors.UniqueViolation:
            return _duplicate_start(clean)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.created",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"country": clean["country"], "valid_from": clean["valid_from"].isoformat(), "name": clean["name"]})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id))

    def update_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] == "confirmed":
            return _locked()
        unknown = sorted(set(changes) - set(HEADER_COLUMNS))
        if unknown:
            return Err("RULE_INVALID", f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        checked = validate_rule_set_header({**{column: header[column] for column in HEADER_COLUMNS}, **changes})
        if isinstance(checked, Err):
            return checked
        clean = checked.value
        try:
            with self.connection.transaction():
                self.connection.execute(
                    f"UPDATE payroll.rule_sets SET {', '.join(f'{column} = %s' for column in HEADER_COLUMNS)} WHERE id = %s",
                    (*(clean[column] for column in HEADER_COLUMNS), rule_set_id),
                )
        except psycopg.errors.UniqueViolation:
            return _duplicate_start(clean)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.updated",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"changes": jsonable({column: clean[column] for column in changes})})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id))

    def delete_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str) -> Result[dict[str, Any]]:
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] == "confirmed":
            return _locked()
        try:
            with self.connection.transaction():
                self.connection.execute("DELETE FROM payroll.rule_sets WHERE id = %s", (rule_set_id,))
        except psycopg.errors.ForeignKeyViolation:
            return Err("RULESET_IN_USE", "payroll runs were calculated with this rule set; it cannot be deleted",
                       "des paies ont été calculées avec ce jeu de règles ; il ne peut pas être supprimé")
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.deleted",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"country": header["country"], "valid_from": header["valid_from"].isoformat(),
                              "name": header["name"], "status": header["status"]})
        return Ok({"id": rule_set_id})

    def copy_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str, valid_from: datetime.date,
                      name: str) -> Result[dict[str, Any]]:
        source = self._header(tenant_id, rule_set_id)
        if source is None:
            return _not_found("rule set", "jeu de règles")
        kept = {column: source[column] for column in HEADER_COLUMNS if column not in ("name", "valid_from")}
        created = self.create_rule_set(tenant_id=tenant_id, actor_id=actor_id, name=name, valid_from=valid_from, **kept)
        if isinstance(created, Err):
            return created
        new_id = created.value["id"]
        for spec in CHILD_KINDS.values():
            rows = fetch_all(self.connection, f"SELECT {', '.join(spec.columns)} FROM {spec.table} WHERE rule_set_id = %s", (rule_set_id,))
            for row in rows:
                self._insert_child(tenant_id, new_id, spec, row)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.copied",
                     entity_type="rule_set", entity_id=new_id, payload={"from_rule_set_id": rule_set_id})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=new_id))

    def confirm_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str) -> Result[dict[str, Any]]:
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] == "confirmed":
            return Err("RULESET_LOCKED", "this rule set is already confirmed", "ce jeu de règles est déjà confirmé")
        problems = check_complete(self.load(tenant_id=tenant_id, rule_set_id=rule_set_id))
        if problems:
            return Err("RULESET_INCOMPLETE", "; ".join(english for english, _ in problems), "; ".join(french for _, french in problems))
        # clock_timestamp, not NOW(): approval compares it with the run's calculation time, and both
        # may happen inside one transaction (tests, seed scripts).
        self.connection.execute(
            "UPDATE payroll.rule_sets SET status = 'confirmed', confirmed_by = %s, confirmed_at = clock_timestamp() WHERE id = %s",
            (actor_id, rule_set_id),
        )
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.confirmed",
                     entity_type="rule_set", entity_id=rule_set_id, payload={"from_status": "draft", "to_status": "confirmed"})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id))

    def reopen_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str) -> Result[dict[str, Any]]:
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] != "confirmed":
            return Err("RULE_INVALID", "this rule set is already a draft", "ce jeu de règles est déjà un brouillon")
        used = fetch_one(
            self.connection,
            "SELECT period FROM payroll.runs WHERE rule_set_id = %s AND status IN ('approved', 'paid') ORDER BY period LIMIT 1",
            (rule_set_id,),
        )
        if used is not None:
            return Err("RULESET_IN_USE", f"the {used['period']:%Y-%m} run was approved with this rule set; copy it to a new draft instead",
                       f"la paie de {used['period']:%m/%Y} a été approuvée avec ce jeu de règles ; copiez-le plutôt en brouillon")
        self.connection.execute(
            "UPDATE payroll.rule_sets SET status = 'draft', confirmed_by = NULL, confirmed_at = NULL WHERE id = %s", (rule_set_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.reopened",
                     entity_type="rule_set", entity_id=rule_set_id, payload={"from_status": "confirmed", "to_status": "draft"})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id))

    # -- rule rows --------------------------------------------------------------------------------
    def list_children(self, *, tenant_id: str, rule_set_id: str, kind: str) -> list[dict[str, Any]]:
        spec = CHILD_KINDS[kind]
        return jsonable(fetch_all(
            self.connection,
            f"SELECT id, {', '.join(spec.columns)} FROM {spec.table} WHERE tenant_id = %s AND rule_set_id = %s ORDER BY {spec.order_by}",
            (tenant_id, rule_set_id),
        ))

    def _child(self, tenant_id: str, spec: ChildSpec, row_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, f"SELECT id, rule_set_id, {', '.join(spec.columns)} FROM {spec.table} WHERE tenant_id = %s AND id = %s",
                         (tenant_id, row_id))

    def _insert_child(self, tenant_id: str, rule_set_id: str, spec: ChildSpec, clean: dict[str, Any]) -> str:
        row_id = str(ULID())
        values = [Jsonb(clean[column]) if column in spec.json_columns else clean[column] for column in spec.columns]
        self.connection.execute(
            f"INSERT INTO {spec.table} (id, tenant_id, rule_set_id, {', '.join(spec.columns)}) "
            f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(spec.columns))})",
            (row_id, tenant_id, rule_set_id, *values),
        )
        return row_id

    def _editable(self, tenant_id: str, rule_set_id: str, kind: str) -> Result[ChildSpec]:
        spec = CHILD_KINDS.get(kind)
        if spec is None:
            return _not_found(f"rule table {kind}", f"table de règles {kind}")
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] == "confirmed":
            return _locked()
        return Ok(spec)

    def add_child(self, *, tenant_id: str, actor_id: str, rule_set_id: str, kind: str, values: dict[str, Any]) -> Result[dict[str, Any]]:
        editable = self._editable(tenant_id, rule_set_id, kind)
        if isinstance(editable, Err):
            return editable
        spec = editable.value
        checked = spec.validate(values)
        if isinstance(checked, Err):
            return checked
        try:
            with self.connection.transaction():
                row_id = self._insert_child(tenant_id, rule_set_id, spec, checked.value)
        except psycopg.errors.UniqueViolation:
            return _duplicate(spec)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.row_added",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"kind": kind, "row_id": row_id, "values": jsonable(checked.value)})
        return Ok(jsonable(self._child(tenant_id, spec, row_id)))

    def update_child(self, *, tenant_id: str, actor_id: str, rule_set_id: str, kind: str, row_id: str,
                     changes: dict[str, Any]) -> Result[dict[str, Any]]:
        editable = self._editable(tenant_id, rule_set_id, kind)
        if isinstance(editable, Err):
            return editable
        spec = editable.value
        current = self._child(tenant_id, spec, row_id)
        if current is None or current["rule_set_id"] != rule_set_id:
            return _not_found(spec.label_en, spec.label_fr)
        checked = spec.validate({**{column: current[column] for column in spec.columns}, **changes})
        if isinstance(checked, Err):
            return checked
        clean = checked.value
        values = [Jsonb(clean[column]) if column in spec.json_columns else clean[column] for column in spec.columns]
        try:
            with self.connection.transaction():
                self.connection.execute(
                    f"UPDATE {spec.table} SET {', '.join(f'{column} = %s' for column in spec.columns)} WHERE id = %s",
                    (*values, row_id),
                )
        except psycopg.errors.UniqueViolation:
            return _duplicate(spec)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.row_updated",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"kind": kind, "row_id": row_id, "changes": jsonable({c: clean[c] for c in changes if c in clean})})
        return Ok(jsonable(self._child(tenant_id, spec, row_id)))

    def delete_child(self, *, tenant_id: str, actor_id: str, rule_set_id: str, kind: str, row_id: str) -> Result[dict[str, Any]]:
        editable = self._editable(tenant_id, rule_set_id, kind)
        if isinstance(editable, Err):
            return editable
        spec = editable.value
        current = self._child(tenant_id, spec, row_id)
        if current is None or current["rule_set_id"] != rule_set_id:
            return _not_found(spec.label_en, spec.label_fr)
        self.connection.execute(f"DELETE FROM {spec.table} WHERE id = %s", (row_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.row_deleted",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"kind": kind, "row_id": row_id, "row": jsonable({c: current[c] for c in spec.columns})})
        return Ok({"id": row_id})

    # -- what the engine reads --------------------------------------------------------------------
    def load(self, *, tenant_id: str, rule_set_id: str) -> RuleSet | None:
        header = self._header(tenant_id, rule_set_id)
        if header is None:
            return None
        rows = {
            kind: fetch_all(self.connection,
                            f"SELECT {', '.join(spec.columns)} FROM {spec.table} WHERE tenant_id = %s AND rule_set_id = %s ORDER BY {spec.order_by}",
                            (tenant_id, rule_set_id))
            for kind, spec in CHILD_KINDS.items()
        }
        reliefs = [relief_from_parameters(row["tax_code"], row["kind"], row["parameters"]) for row in rows["tax_reliefs"]]
        return RuleSet(
            id=header["id"], country=header["country"], valid_from=header["valid_from"], status=header["status"],
            round_to=header["round_to"], round_mode=header["round_mode"],
            tax_round_to=header["tax_round_to"], tax_round_mode=header["tax_round_mode"],
            working_days_per_month=header["working_days_per_month"],
            working_hours_per_month=header["working_hours_per_month"],
            settlement_reference_months=header["settlement_reference_months"],
            components=tuple(ComponentRule(**row) for row in rows["components"]),
            contributions=tuple(ContributionRule(**row) for row in rows["contributions"]),
            tax_brackets=tuple(TaxBracket(tax_code=row["tax_code"], lower=row["lower_bound"], upper=row["upper_bound"],
                                          rate=row["rate"], annualised=row["annualised"]) for row in rows["tax_brackets"]),
            family_reliefs=tuple(relief for relief in reliefs if isinstance(relief, FamilyRelief)),
            professional_reliefs=tuple(relief for relief in reliefs if isinstance(relief, ProfessionalRelief)),
            seniority_scale=tuple(SeniorityStep(**row) for row in rows["seniority_scale"]),
            overtime_rates=tuple(OvertimeRate(**row) for row in rows["overtime_rates"]),
            severance_scale=tuple(SeveranceStep(**row) for row in rows["severance_scale"]),
        )

    def in_force(self, *, tenant_id: str, period: datetime.date) -> Result[dict[str, Any]]:
        settings = self.get_settings(tenant_id=tenant_id)
        if settings is None:
            return Err("RULESET_MISSING", "set the payroll country first (Payroll → Rules)",
                       "renseignez d'abord le pays de paie (Paie → Règles)")
        country = settings["country"]
        row = fetch_one(
            self.connection,
            _HEADER_SELECT + " WHERE tenant_id = %s AND country = %s AND valid_from <= %s ORDER BY valid_from DESC LIMIT 1",
            (tenant_id, country, period),
        )
        if row is None:
            return Err("RULESET_MISSING", f"no {country} rule set applies to {period:%Y-%m}",
                       f"aucun jeu de règles {country} ne s'applique à {period:%m/%Y}")
        return Ok(row)
