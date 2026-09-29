"""Give the demo tenant a SYSCOHADA ledger and post the seeded payroll run(s) and invoices into it.

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_finance_ledger.py --dry-run
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_finance_ledger.py

Idempotent — a second run adds nothing:
1. grants the demo user the seven ledger permissions;
2. installs the chart, the journals and the default posting rules (all `to_confirm`);
3. opens the fiscal years the data falls in (and the current one);
4. adds `to_confirm` rules sending AMO contributions to 433, for the contribution codes the seeded runs
   actually use whose code contains "AMO" — the codes belong to payroll, so they are printed for the
   accountant to check, like every other rule;
5. posts every seeded payroll run that got past calculation through the path the worker uses
   (`post_for_event` with a `payroll.run.approved` envelope, then `paid` / `reversed` when the run is),
   and replays the tenant's `finance.invoice.issued` / `paid` outbox envelopes, oldest first;
6. records and prints every refusal (it then shows on the run page and on the Entries screen).

Dev shortcut, not a business rule: the seeded rule set is a draft, so the demo run cannot be approved;
a `calculated` run is posted as if approved so the ledger screens hold a real payroll entry. The run's
own status is not touched. Reading `payroll.runs` and `events.outbox` directly is allowed here only
because this is a dev seeder, like the other scripts in this folder.
"""
from __future__ import annotations

import datetime

from ulid import ULID

from core.domain.result import Err
from modules.finance.api import payroll_ledger_service
from modules.finance.api.chart_setup_service import ChartSetupService
from modules.finance.api.ledger_event_postings import post_for_event, source_of
from modules.finance.api.period_service import PeriodService
from modules.finance.api.posting_failure_service import PostingFailureService
from modules.finance.api.posting_rule_service import PostingRuleService
from scripts.seed_common import TENANT, actor_id, run

LEDGER_PERMISSIONS = [
    "finance.view_ledger",
    "finance.manage_entries",
    "finance.admin_entries",
    "finance.manage_accounts",
    "finance.admin_accounts",
    "finance.admin_periods",
    "finance.manage_posting_rules",
]
POSTED_RUN_STATUSES = ("calculated", "approved", "paid", "reversed")
AMO_ACCOUNTS = {"employee_contribution": (None, "433"), "employer_contribution": ("664", "433")}


def amo_rules(posting_lines: list[dict]) -> list[tuple[str, str, str | None, str]]:
    """(source_kind, code, debit, credit) for each AMO contribution code the run uses, once each."""
    rules: list[tuple[str, str, str | None, str]] = []
    for line in posting_lines:
        kind, code = line["source_kind"], str(line["code"])
        if kind in AMO_ACCOUNTS and "AMO" in code.upper():
            debit, credit = AMO_ACCOUNTS[kind]
            rule = (kind, code, debit, credit)
            if rule not in rules:
                rules.append(rule)
    return rules


def _envelope(event_type: str, payload: dict, occurred_at: datetime.datetime) -> dict:
    return {
        "event_id": str(ULID()),
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": occurred_at.isoformat(),
        "producer": "seed",
        "tenant_id": TENANT,
        "correlation_id": str(ULID()),
        "causation_id": None,
        "payload": payload,
    }


def _post(conn, envelope: dict) -> bool:
    result = post_for_event(conn, envelope)
    source_module, source_id, source_kind = source_of(envelope)
    if isinstance(result, Err):
        PostingFailureService(conn).record(
            tenant_id=TENANT, source_module=source_module, source_id=source_id,
            source_kind=source_kind, envelope=envelope, err=result,
        )
        print(f"  REFUSED {envelope['event_type']} {source_id}: {result.code} — {result.message}")
        return False
    for entry in result.value:
        print(f"  {entry['number']:<18} {entry['journal_code']:<4} {entry['entry_date']} {entry['label']} ({int(entry['total_debit'])} F CFA)")
    return True


def work(conn, args) -> int:
    actor = actor_id(conn)
    for permission in LEDGER_PERMISSIONS:
        conn.execute(
            "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (actor, permission),
        )
    print("setup:", ChartSetupService(conn).ensure_defaults(tenant_id=TENANT, actor_id=actor))

    runs = conn.execute(
        "SELECT id, period, status FROM payroll.runs WHERE tenant_id = %s AND status = ANY(%s) ORDER BY period, id",
        (TENANT, list(POSTED_RUN_STATUSES)),
    ).fetchall()
    invoice_envelopes = [
        row[0]
        for row in conn.execute(
            """
            SELECT payload FROM events.outbox
            WHERE tenant_id = %s AND event_type IN ('finance.invoice.issued', 'finance.invoice.paid')
            ORDER BY created_at
            """,
            (TENANT,),
        ).fetchall()
    ]

    years = {datetime.date.today().year} | {period.year for _, period, _ in runs}
    years |= {datetime.datetime.fromisoformat(envelope["occurred_at"]).year for envelope in invoice_envelopes}
    periods = PeriodService(conn)
    for year in sorted(years):
        opened = periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=year)
        print(f"fiscal year {year}:", "opened" if not isinstance(opened, Err) else opened.code)

    payroll_api = payroll_ledger_service.PAYROLL_API_FACTORY(conn)
    rules = PostingRuleService(conn)
    for run_id, _, _ in runs:
        for kind, code, debit, credit in amo_rules(payroll_api.posting_lines(tenant_id=TENANT, run_id=run_id)):
            created = rules.create_rule(
                tenant_id=TENANT, actor_id=actor, source="payroll", source_kind=kind, code=code,
                debit_account_code=debit, credit_account_code=credit,
            )
            print(f"AMO rule {kind} {code}:", "added" if not isinstance(created, Err) else created.code)

    refused = 0
    for run_id, period, status in runs:
        print(f"payroll run {run_id} ({period:%m/%Y}, {status})")
        last_day = payroll_ledger_service.last_day_of(period)
        at = datetime.datetime.combine(min(last_day, datetime.date.today()), datetime.time(12, 0), datetime.timezone.utc)
        payload = {"run_id": run_id, "period": period.isoformat(), "run_type": "regular"}
        steps = ["payroll.run.approved"]
        if status in ("paid", "reversed"):
            steps.append("payroll.run.paid")
        if status == "reversed":
            steps.append("payroll.run.reversed")
        for event_type in steps:
            refused += not _post(conn, _envelope(event_type, payload, at))

    print(f"invoices: {len(invoice_envelopes)} event(s) to replay")
    for envelope in invoice_envelopes:
        refused += not _post(conn, envelope)

    print("\nposting rules (to be ticked by the accountant):")
    for rule in rules.list_rules(tenant_id=TENANT):
        print(
            f"  {rule['source']:<8} {rule['source_kind']:<22} {rule['code']:<10} "
            f"D {rule['debit_account_code'] or '-':<5} C {rule['credit_account_code'] or '-':<5} "
            f"{rule['journal_code'] or '':<4} {rule['status']}"
        )
    print(f"\n{len(runs)} payroll run(s), {len(invoice_envelopes)} invoice event(s), {refused} refusal(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run("Seed the SYSCOHADA ledger of the demo tenant and post its payroll and invoices.", work))
