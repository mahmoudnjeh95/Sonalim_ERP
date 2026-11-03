"""hr.settings: the alert horizons, one row per tenant, empty until HR sets them."""
from __future__ import annotations

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload
from modules.hr.domain.alerts import HORIZON_KEYS, validate_horizons


class HrSettingsService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def get(self, tenant_id: str) -> dict:
        row = self.connection.execute(f"SELECT {', '.join(HORIZON_KEYS)} FROM hr.settings WHERE tenant_id = %s", (tenant_id,)).fetchone()
        return dict(zip(HORIZON_KEYS, row or (None,) * len(HORIZON_KEYS)))

    def save(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        contract_expiry_horizon_days: int | None,
        trial_end_horizon_days: int | None,
        document_expiry_horizon_days: int | None,
    ) -> Result[dict]:
        validated = validate_horizons(
            {
                "contract_expiry_horizon_days": contract_expiry_horizon_days,
                "trial_end_horizon_days": trial_end_horizon_days,
                "document_expiry_horizon_days": document_expiry_horizon_days,
            }
        )
        if isinstance(validated, Err):
            return validated
        before = self.get(tenant_id)
        values = validated.value
        self.connection.execute(
            """
            INSERT INTO hr.settings (tenant_id, contract_expiry_horizon_days, trial_end_horizon_days, document_expiry_horizon_days, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                contract_expiry_horizon_days = EXCLUDED.contract_expiry_horizon_days,
                trial_end_horizon_days = EXCLUDED.trial_end_horizon_days,
                document_expiry_horizon_days = EXCLUDED.document_expiry_horizon_days,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            (tenant_id, *(values[key] for key in HORIZON_KEYS), actor_id),
        )
        after = self.get(tenant_id)
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="hr_settings.updated",
            entity_type="hr_settings", entity_id=tenant_id, payload=change_payload(before, after),
        )
        return Ok(after)
