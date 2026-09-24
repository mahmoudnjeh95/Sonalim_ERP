"""Contrôle des paramètres: one row per instrument-group entry on a QC report."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.qc.api.quality_service import QualityReportService
from modules.qc.api.test_qc_flow_integration import TENANT, _ok, _quality_report, env, of  # noqa: F401


def test_saving_a_parameter_entry_round_trips(db, env, of):
    report = _quality_report(db, env, of)
    saved = QualityReportService(db).save_parameter_entry(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        group_key="sechage", entry_label="07h38", fields={"temperature_c": 78.4, "delta": 7.1},
    )
    assert isinstance(saved, Ok), getattr(saved, "message", "")

    entries = QualityReportService(db).list_parameters(tenant_id=TENANT, report_id=report.id)
    assert len(entries) == 1
    assert entries[0]["group_key"] == "sechage"
    assert entries[0]["entry_label"] == "07h38"
    assert entries[0]["fields"]["temperature_c"] == 78.4


def test_saving_an_entry_for_an_unknown_field_is_rejected(db, env, of):
    report = _quality_report(db, env, of)
    result = QualityReportService(db).save_parameter_entry(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        group_key="sechage", entry_label="07h38", fields={"not_a_field": 1},
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_FIELD"


def test_deleting_an_entry_removes_it(db, env, of):
    report = _quality_report(db, env, of)
    saved = _ok(QualityReportService(db).save_parameter_entry(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        group_key="presse", entry_label="4132", fields={"pression": 114},
    ))
    QualityReportService(db).delete_parameter_entry(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, entry_id=saved["id"])
    assert QualityReportService(db).list_parameters(tenant_id=TENANT, report_id=report.id) == []
