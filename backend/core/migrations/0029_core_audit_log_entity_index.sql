-- One entity's trail (GET /core/audit-log?entity_type=&entity_id=, and maintenance's
-- machine history rebuilding a machine's status changes) used to scan the whole log.
-- Schema only.
CREATE INDEX IF NOT EXISTS core_audit_log_entity_idx
    ON core.audit_log (tenant_id, entity_type, entity_id, occurred_at);
