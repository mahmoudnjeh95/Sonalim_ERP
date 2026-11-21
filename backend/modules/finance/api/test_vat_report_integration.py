"""VAT report: sales by rate from invoice and credit-note lines, collected / deductible / payable from the ledger."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ulid import ULID

from modules.finance.api.vat_report_service import VatReportService

D = Decimal
T = "vat-report-t"
DAY = datetime.date(2026, 3, 10)
RANGE = (datetime.date(2026, 3, 1), datetime.date(2026, 3, 31))


def _invoice(db, status, lines, day=DAY):
    invoice_id = str(ULID())
    db.execute("INSERT INTO finance.invoices (id, tenant_id, partner_id, amount, status, invoice_date) VALUES (%s, %s, 'p', 0, %s, %s)",
               (invoice_id, T, status, day))
    for base, rate in lines:
        db.execute("INSERT INTO finance.invoice_lines (id, tenant_id, invoice_id, product_id, quantity, unit_price, amount, vat_rate) "
                   "VALUES (%s, %s, %s, 'prod', 1, %s, %s, %s)", (str(ULID()), T, invoice_id, base, base, rate))
    return invoice_id


def _entry(db, account, debit, credit, day=DAY, status="posted"):
    entry_id = str(ULID())
    db.execute("INSERT INTO finance.journal_entries (id, tenant_id, journal_code, entry_date, period, label, status, created_by) "
               "VALUES (%s, %s, 'VT', %s, %s, 'x', 'draft', 'a')", (entry_id, T, day, day.replace(day=1)))
    db.execute("INSERT INTO finance.journal_lines (id, tenant_id, entry_id, line_no, account_code, debit, credit) VALUES (%s, %s, %s, 1, %s, %s, %s)",
               (str(ULID()), T, entry_id, account, debit, credit))
    if status != "draft":  # lines are frozen once an entry is posted
        db.execute("UPDATE finance.journal_entries SET status = %s, number = %s, posted_at = NOW() WHERE id = %s", (status, entry_id, entry_id))


def _rules(db):
    db.execute("INSERT INTO finance.fiscal_years (id, tenant_id, year, start_date, end_date, created_by) VALUES ('fy', %s, 2026, '2026-01-01', '2026-12-31', 'a')", (T,))
    for month in (3, 5):
        db.execute("INSERT INTO finance.periods (tenant_id, period, fiscal_year_id) VALUES (%s, %s, 'fy')", (T, datetime.date(2026, month, 1)))
    db.execute("INSERT INTO finance.journals (tenant_id, code, name, journal_type) VALUES (%s, 'VT', 'Sales', 'sales')", (T,))
    for code in ("443", "445"):
        db.execute("INSERT INTO finance.accounts (tenant_id, code, name, class_no, account_type) VALUES (%s, %s, 'VAT', 4, 'liability')", (T, code))
    for source, debit, credit in (("invoice", None, "443"), ("purchase_invoice", "445", None)):
        db.execute("INSERT INTO finance.posting_rules (id, tenant_id, source, source_kind, code, debit_account_code, credit_account_code) "
                   "VALUES (%s, %s, %s, 'vat', '*', %s, %s)", (str(ULID()), T, source, debit, credit))


def test_sales_by_rate_counts_issued_invoices_net_of_credit_notes(db):
    invoice_id = _invoice(db, "issued", [(10000, 18), (5000, 0)])
    _invoice(db, "draft", [(99999, 18)])
    _invoice(db, "paid", [(1000, 18)], day=datetime.date(2026, 4, 2))  # outside the period
    db.execute("INSERT INTO finance.credit_notes (id, tenant_id, number, invoice_id, partner_id, source_id, credit_date, amount, currency) "
               "VALUES ('cn1', %s, 'AV1', %s, 'p', 's', %s, 2360, 'XOF')", (T, invoice_id, DAY))
    db.execute("INSERT INTO finance.credit_note_lines (id, credit_note_id, product_id, quantity, unit_price, amount, vat_rate) "
               "VALUES ('cnl1', 'cn1', 'prod', 1, 2000, 2000, 18)")
    rows = VatReportService(db).sales_by_rate(tenant_id=T, date_from=RANGE[0], date_to=RANGE[1])
    assert rows == [{"vat_rate": D("18.00"), "base": D("8000.00"), "vat": D("1440.00"), "exempt": False},
                    {"vat_rate": D("0.00"), "base": D("5000.00"), "vat": D("0.00"), "exempt": True}]


def test_ledger_payable_is_collected_minus_deductible(db):
    _rules(db)
    _entry(db, "443", 0, 1800)
    _entry(db, "443", 200, 0)                       # credit note reverses part of it
    _entry(db, "445", 500, 0)
    _entry(db, "445", 0, 900, status="draft")       # drafts never count
    _entry(db, "443", 0, 7777, day=datetime.date(2026, 5, 1))  # outside the period
    report = VatReportService(db).report(tenant_id=T, date_from=RANGE[0], date_to=RANGE[1])
    assert report["ledger"]["collected"] == D(1600) and report["ledger"]["deductible"] == D(500)
    assert report["ledger"]["payable"] == D(1100) and report["warnings"] == []


def test_missing_rules_warn_instead_of_failing(db):
    report = VatReportService(db).report(tenant_id="vat-report-none", date_from=RANGE[0], date_to=RANGE[1])
    assert report["warnings"] == ["NO_COLLECTED_VAT_ACCOUNT", "NO_DEDUCTIBLE_VAT_ACCOUNT"]
    assert report["ledger"]["payable"] is None and report["sales_by_rate"] == []
