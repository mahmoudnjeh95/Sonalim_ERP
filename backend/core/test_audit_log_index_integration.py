"""The audit log can be read one entity at a time without scanning it all."""
from __future__ import annotations


def test_audit_log_has_the_per_entity_index(db):
    row = db.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'core' AND indexname = 'core_audit_log_entity_idx'"
    ).fetchone()
    assert row is not None
    assert "(tenant_id, entity_type, entity_id, occurred_at)" in row[0]
