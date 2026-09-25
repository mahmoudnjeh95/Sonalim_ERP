"""Shift and team names, and the arrêt vocabulary, configurable per tenant.

A report is filed by a team on a shift, and both were free text — so the same
shift arrived spelled three ways and nothing grouped. These are the lists the
report forms offer. The arrêt type, classification and motif live here too:
the frontend ships a built-in set of each, and these rows are the plant's own
additions to it.

Two rules shape the whole file:

* **A report keeps the label it was filed under.** Nothing here is a foreign key.
  Renaming "Matin" to "Équipe A" changes what tomorrow's report may choose and
  leaves last month's saying "Matin", which is what actually happened.
* **Retiring is not deleting.** An option that reports were filed under is
  deactivated rather than removed, so the list a supervisor sees stays current
  without making the archive unexplainable.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from ulid import ULID

from core.audit import record_audit
from core.db import get_connection
from core.domain.result import Err, err_detail, Ok, Result
from core.tenancy import TenantContext, require_permission, require_session

router = APIRouter(prefix="/core", tags=["core.report_options"])

VALID_KINDS = ("shift", "team", "downtime_type", "downtime_classification", "downtime_motif")

# Where a report stores each kind's label, so a name that reports were filed
# under can be retired instead of deleted. A table that is not installed is
# skipped -- see _is_in_use.
_LABEL_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "shift": (("production.production_reports", "shift"), ("qc.quality_reports", "shift")),
    "team": (("production.production_reports", "team"), ("qc.quality_reports", "team")),
    "downtime_type": (("production.report_downtime_lines", "downtime_type"),),
    "downtime_classification": (("production.report_downtime_lines", "classification"),),
    # A conditionnement report keeps its single motif on the report itself.
    "downtime_motif": (
        ("production.report_downtime_lines", "motif"),
        ("production.conditionnement_reports", "downtime_reason"),
    ),
}


class ReportOption(BaseModel):
    id: str
    kind: str
    label: str
    sort_order: int
    is_active: bool


class CreateReportOptionRequest(BaseModel):
    kind: str
    label: str
    sort_order: int = 0

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in VALID_KINDS:
            raise ValueError(f"kind must be one of {VALID_KINDS}")
        return value

    @field_validator("label")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label cannot be blank")
        return value.strip()


class UpdateReportOptionRequest(BaseModel):
    label: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None

    @field_validator("label")
    @classmethod
    def _non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("label cannot be blank")
        return value.strip() if value is not None else None


class ReportOptionsService:
    """The shift and team lists a tenant files reports against."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def list_options(
        self, *, tenant_id: str, kind: str | None = None, include_inactive: bool = False
    ) -> list[dict]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)
        if not include_inactive:
            clauses.append("is_active")
        rows = self._connection.execute(
            f"""
            SELECT id, kind, label, sort_order, is_active
            FROM core.report_options
            WHERE {' AND '.join(clauses)}
            ORDER BY kind, sort_order, label
            """,
            params,
        ).fetchall()
        return [
            {"id": row[0], "kind": row[1], "label": row[2], "sort_order": row[3], "is_active": row[4]}
            for row in rows
        ]

    def create_option(
        self, *, tenant_id: str, actor_id: str, kind: str, label: str, sort_order: int = 0
    ) -> Result[dict]:
        if kind not in VALID_KINDS:
            return Err("INVALID_KIND", f"kind must be one of {VALID_KINDS}", f"kind doit être l'un de {VALID_KINDS}")
        label = label.strip()
        if not label:
            return Err("INVALID_LABEL", "an option needs a name", "une option doit avoir un nom")

        existing = self._connection.execute(
            "SELECT id, is_active FROM core.report_options "
            "WHERE tenant_id = %s AND kind = %s AND lower(label) = lower(%s)",
            (tenant_id, kind, label),
        ).fetchone()
        if existing is not None:
            # Re-adding a name that was retired is how a supervisor brings a shift
            # back, so treat it as reactivation rather than a duplicate.
            if not existing[1]:
                return self.update_option(
                    tenant_id=tenant_id, actor_id=actor_id, option_id=existing[0], is_active=True
                )
            return Err("DUPLICATE_OPTION", f"a {kind} called {label!r} already exists", f"un {kind} nommé {label!r} existe déjà")

        option_id = str(ULID())
        self._connection.execute(
            "INSERT INTO core.report_options (id, tenant_id, kind, label, sort_order) VALUES (%s, %s, %s, %s, %s)",
            (option_id, tenant_id, kind, label, sort_order),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="report_option.created",
            entity_type="report_option",
            entity_id=option_id,
            payload={"kind": kind, "label": label, "sort_order": sort_order},
        )
        return Ok(self._read(tenant_id=tenant_id, option_id=option_id))

    def update_option(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        option_id: str,
        label: str | None = None,
        sort_order: int | None = None,
        is_active: bool | None = None,
    ) -> Result[dict]:
        current = self._connection.execute(
            "SELECT kind, label, sort_order, is_active FROM core.report_options WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (option_id, tenant_id),
        ).fetchone()
        if current is None:
            return Err("NOT_FOUND", f"report option {option_id} not found", f"option de rapport {option_id} introuvable")
        kind, current_label, current_sort, current_active = current

        new_label = current_label if label is None else label.strip()
        if not new_label:
            return Err("INVALID_LABEL", "an option needs a name", "une option doit avoir un nom")
        if new_label.lower() != current_label.lower():
            clash = self._connection.execute(
                "SELECT 1 FROM core.report_options "
                "WHERE tenant_id = %s AND kind = %s AND lower(label) = lower(%s) AND id <> %s",
                (tenant_id, kind, new_label, option_id),
            ).fetchone()
            if clash is not None:
                return Err(
                    "DUPLICATE_OPTION",
                    f"a {kind} called {new_label!r} already exists",
                    f"un {kind} nommé {new_label!r} existe déjà",
                )

        self._connection.execute(
            "UPDATE core.report_options SET label = %s, sort_order = %s, is_active = %s, updated_at = NOW() "
            "WHERE id = %s AND tenant_id = %s",
            (
                new_label,
                current_sort if sort_order is None else sort_order,
                current_active if is_active is None else is_active,
                option_id,
                tenant_id,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="report_option.updated",
            entity_type="report_option",
            entity_id=option_id,
            payload={
                "kind": kind,
                "label": new_label,
                "previous_label": current_label,
                "sort_order": current_sort if sort_order is None else sort_order,
                "is_active": current_active if is_active is None else is_active,
            },
        )
        return Ok(self._read(tenant_id=tenant_id, option_id=option_id))

    def delete_option(self, *, tenant_id: str, actor_id: str, option_id: str) -> Result[dict]:
        """Remove the option, or retire it if reports were filed under its name.

        Reports store the label, not a reference, so removing the row would not
        corrupt anything — but it would make the list of past shifts unexplainable
        to whoever reads the archive. Retiring keeps the history legible and takes
        the option off tomorrow's form all the same.
        """
        current = self._connection.execute(
            "SELECT kind, label FROM core.report_options WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (option_id, tenant_id),
        ).fetchone()
        if current is None:
            return Err("NOT_FOUND", f"report option {option_id} not found", f"option de rapport {option_id} introuvable")
        kind, label = current

        if self._is_in_use(tenant_id=tenant_id, kind=kind, label=label):
            result = self.update_option(
                tenant_id=tenant_id, actor_id=actor_id, option_id=option_id, is_active=False
            )
            if isinstance(result, Err):
                return result
            return Ok({"outcome": "retired", "option": result.value})

        self._connection.execute(
            "DELETE FROM core.report_options WHERE id = %s AND tenant_id = %s", (option_id, tenant_id)
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="report_option.deleted",
            entity_type="report_option",
            entity_id=option_id,
            payload={"kind": kind, "label": label},
        )
        return Ok({"outcome": "deleted", "option": {"id": option_id, "kind": kind, "label": label}})

    def _is_in_use(self, *, tenant_id: str, kind: str, label: str) -> bool:
        """Has any report been filed under this name?

        `core` deliberately does not import either module: it asks the tables by
        name, and skips one that is not installed rather than failing, so a
        deployment running without production or qc still gets to manage its
        lists. The existence check is `to_regclass` rather than a caught error —
        a failed statement would abort the caller's transaction along with it.
        """
        for table, column in _LABEL_COLUMNS[kind]:
            installed = self._connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()
            if installed is None or installed[0] is None:
                continue
            row = self._connection.execute(
                f"SELECT 1 FROM {table} WHERE tenant_id = %s AND lower({column}) = lower(%s) LIMIT 1",
                (tenant_id, label),
            ).fetchone()
            if row is not None:
                return True
        return False

    def _read(self, *, tenant_id: str, option_id: str) -> dict:
        row = self._connection.execute(
            "SELECT id, kind, label, sort_order, is_active FROM core.report_options WHERE id = %s AND tenant_id = %s",
            (option_id, tenant_id),
        ).fetchone()
        return {"id": row[0], "kind": row[1], "label": row[2], "sort_order": row[3], "is_active": row[4]}


def _err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code == "DUPLICATE_OPTION":
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _raise(result: Err) -> None:
    raise HTTPException(_err_status(result.code), err_detail(result))


@router.get("/report-options")
def list_report_options(
    kind: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    # Readable by anyone who can file a report — the form needs the list.
    tenant: TenantContext = Depends(require_session),
) -> list[dict]:
    with get_connection() as connection:
        return ReportOptionsService(connection).list_options(
            tenant_id=tenant.tenant_id, kind=kind, include_inactive=include_inactive
        )


@router.post("/report-options", status_code=status.HTTP_201_CREATED)
def create_report_option(
    body: CreateReportOptionRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_report_options")),
) -> dict:
    with get_connection() as connection:
        result = ReportOptionsService(connection).create_option(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            kind=body.kind,
            label=body.label,
            sort_order=body.sort_order,
        )
        if isinstance(result, Err):
            connection.rollback()
            _raise(result)
        connection.commit()
    return result.value


@router.patch("/report-options/{option_id}")
def update_report_option(
    option_id: str,
    body: UpdateReportOptionRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_report_options")),
) -> dict:
    with get_connection() as connection:
        result = ReportOptionsService(connection).update_option(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            option_id=option_id,
            label=body.label,
            sort_order=body.sort_order,
            is_active=body.is_active,
        )
        if isinstance(result, Err):
            connection.rollback()
            _raise(result)
        connection.commit()
    return result.value


@router.delete("/report-options/{option_id}")
def delete_report_option(
    option_id: str,
    tenant: TenantContext = Depends(require_permission("core.manage_report_options")),
) -> dict:
    """Remove the option, or retire it when reports already carry its name."""
    with get_connection() as connection:
        result = ReportOptionsService(connection).delete_option(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, option_id=option_id
        )
        if isinstance(result, Err):
            connection.rollback()
            _raise(result)
        connection.commit()
    return result.value
