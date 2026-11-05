"""Go-live reset: wipes every operational/test record and keeps only the master data.

KEPT      users (and their profile photos), roles and permissions, products (and their
          classification / tags / attributes), UoMs, currencies, warehouse locations,
          suppliers, machines (maintenance.equipment, their photo maps and checkpoints,
          maintenance teams and preventive programs), work centers, molds, recipes,
          packaging BOMs, team rosters, shift windows, report options, waste types, the
          codes the paper scan learned from corrections, and every other configuration
          table.
WIPED     work orders (OF) and regrind orders (OFR), the legacy Daily/Conditionnement
          reports and the per-shift reports with everything under them, QC reports and
          non-conformities, stock moves and lots, cycle counts, purchasing, sales, CRM,
          finance, HR (and the shift-role to HR-position mapping, whose positions go with
          it), maintenance jobs (checks, entries, reviews, timeline) and parts requests,
          paper scans (fiche photos and what was read on them), in-app notifications, the
          audit log, the event outbox and the AI assistant history.
ZEROED    every stock quantity in warehouse.stock_items (the rows stay, so each
          product/location keeps its place -- only on-hand / reserved / in-production
          go to 0) and the OF-/OFR-/NC- numbering counters.
RESTARTED every maintenance program keeps its settings but is marked as generated
          through yesterday, so the next sweep raises jobs from today on instead of
          re-creating every past occurrence whose job was just wiped.
CUSTOMERS removed (they came from the sales/CRM demo data); suppliers stay. Pass
          --keep-customers to keep them.

Every table in the database must be classified below. A table that is not listed makes
the script stop, so a future migration cannot add a table that is silently kept or
silently wiped -- add it to the right list and re-run.

The wipe is one transaction; TRUNCATE is used without CASCADE, so if a table that is
being kept holds a foreign key into a table being wiped, PostgreSQL refuses and nothing
changes.

Usage (from backend/, or `docker compose exec app` on the server):
    python -m scripts.reset_operational_data --dry-run
    python -m scripts.reset_operational_data --confirm-database erp_prod

--dry-run does the whole wipe, prints what it removed, then rolls back. The real run
only proceeds when --confirm-database equals the database it is connected to. Take a
backup first (see docs/go-live-data-reset.md): this cannot be undone.
"""

from __future__ import annotations

import argparse
import sys

from psycopg import sql

from core.db import get_connection

# Tables emptied completely.
PURGE_TABLES = [
    "core.audit_log",
    "events.outbox",
    "events.processed_events",
    "crm.activities",
    "crm.contacts",
    "crm.leads",
    "crm.opportunities",
    "finance.invoices",
    "finance.invoice_payment_deltas",
    "finance.journal_entries",
    "finance.journal_lines",
    "finance.posting_failures",
    "hr.attendance_records",
    "hr.contract_components",
    "hr.contracts",
    "hr.departments",
    "hr.dependants",
    "hr.employees",
    "hr.employee_documents",
    "hr.payment_methods",
    "hr.leave_requests",
    "hr.payroll_items",
    "hr.payroll_runs",
    "hr.positions",
    "hr.clock_import_rows",
    "hr.clock_imports",
    "hr.clock_punches",
    "hr.leave_accruals",
    "hr.leave_balances",
    "hr.presence_days",
    "hr.presence_month_payroll_locks",
    "hr.presence_months",
    "hr.schedule_assignments",
    "payroll.advances",
    "payroll.carry_forwards",
    "payroll.final_settlements",
    "payroll.loan_instalments",
    "payroll.loans",
    "payroll.payout_batches",
    "payroll.payout_lines",
    "payroll.payslip_lines",
    "payroll.payslips",
    "payroll.run_inputs",
    "payroll.runs",
    "procurement.purchase_order_lines",
    "procurement.purchase_order_receipt_lines",
    "procurement.purchase_order_receipts",
    "procurement.purchase_orders",
    "procurement.purchase_invoices",
    "procurement.purchase_invoice_lines",
    "procurement.invoice_counters",
    "procurement.invoice_payment_deltas",
    "procurement.purchase_invoice_receipts",
    "procurement.purchase_invoice_attachments",
    "procurement.purchase_credit_notes",
    "procurement.purchase_credit_note_lines",
    "procurement.credit_note_counters",
    "sales.order_lines",
    "sales.orders",
    "qc.nc_dispositions",
    "qc.non_conformities",
    "qc.quality_follow_ups",
    "qc.quality_conformity_lines",
    "qc.quality_parameters",
    "qc.quality_report_details",
    "qc.quality_reports",
    "production.work_orders",
    "production.work_order_inputs",
    "production.regrind_batches",
    "production.regrind_batch_inputs",
    "production.scrap_records",
    "production.production_reports",
    "production.daily_reports",
    "production.conditionnement_reports",
    "production.report_downtime_lines",
    "production.report_revisions",
    "production.report_semolina_lines",
    "production.report_waste_lines",
    "production.shift_reports",
    "production.shift_report_sections",
    "production.shift_section_revisions",
    "production.shift_runs",
    "production.shift_run_semolina_lines",
    "production.shift_packing_rows",
    "production.shift_packet_checks",
    "production.shift_waste_lines",
    "production.shift_energy",
    "production.shift_mold_washes",
    "production.shift_silo_states",
    "production.shift_staffing",
    "production.shift_versements",
    "production.shift_rebroyat_versements",
    "production.machine_stops",
    "production.stock_release_lines",
    "production.ia_assistant_conversations",
    "production.ia_assistant_messages",
    # Configuration, but every row names an hr.positions id, and hr.positions is wiped above.
    "production.shift_role_positions",
    "scan.scan_sessions",
    "scan.scan_pages",
    "scan.scan_field_outcomes",
    "warehouse.stock_moves",
    "warehouse.lot_stock",
    "warehouse.lots",
    "warehouse.vouchers",
    "warehouse.voucher_lines",
    "warehouse.voucher_counters",
    "warehouse.document_attachments",
    # legacy: the inventory feature was replaced by cycle counts; no migration creates these any more,
    # but a database that applied the earlier 0020 still has them
    "warehouse.inventories",
    "warehouse.inventory_lines",
    "treasury.documents",
    "treasury.document_allocations",
    "treasury.document_payments",
    "treasury.document_counters",
    "treasury.instruments",
    "treasury.deposit_slips",
    "treasury.deposit_slip_items",
    "treasury.payment_orders",
    "treasury.invoice_payment_orders",
    "treasury.document_attachments",
    "treasury.user_notifications",
    "treasury.account_movements",
    "treasury.bank_statement_lines",
    "treasury.statement_imports",
    "warehouse.cycle_count_lines",
    "warehouse.cycle_counts",
    "warehouse.shipments",
    "warehouse.pick_list_lines",
    "warehouse.pick_lists",
    "warehouse.stock_reservations",
    "warehouse.cost_layer_consumptions",
    "warehouse.cost_layers",
    "warehouse.replenishment_proposals",
    "core.notifications",
    "maintenance.jobs",
    "maintenance.job_checks",
    "maintenance.check_entries",
    "maintenance.check_reviews",
    "maintenance.job_events",
    "maintenance.part_requests",
    "maintenance.part_request_lines",
]

# Tables that are edited in place rather than emptied (see purge()).
EDITED_TABLES = [
    "core.partners",
    "core.partner_tag_links",
    "core.sequences",
    "maintenance.programs",
    "warehouse.stock_items",
    "treasury.accounts",
]

# Master data and configuration: never touched.
KEPT_TABLES = [
    "warehouse.settings",
    "core.companies",
    "core.currencies",
    "core.exchange_rates",
    "core.module_migrations",
    "core.product_attribute_values",
    "core.product_attributes",
    "core.product_tag_links",
    "core.product_tags",
    "core.product_variant_values",
    "core.products",
    "core.refresh_tokens",
    "core.report_options",
    "core.role_permissions",
    "core.roles",
    "core.sessions",
    "core.uoms",
    "core.user_avatars",
    "core.user_permissions",
    "core.user_roles",
    "core.user_table_preferences",
    "core.users",
    "hr.clock_profiles",
    "hr.grades",
    "hr.leave_types",
    "hr.presence_settings",
    "hr.public_holidays",
    "hr.rotation_pattern_steps",
    "hr.rotation_patterns",
    "hr.settings",
    "hr.work_schedule_days",
    "hr.work_schedules",
    "finance.accounts",
    "finance.fiscal_years",
    "finance.journals",
    "finance.periods",
    "finance.posting_rules",
    "maintenance.equipment",
    "maintenance.equipment_views",
    "maintenance.checkpoints",
    "maintenance.checkpoint_parts",
    "maintenance.program_checkpoints",
    "maintenance.settings",
    "maintenance.teams",
    "maintenance.team_members",
    "payroll.bank_file_templates",
    "payroll.components",
    "payroll.contributions",
    "payroll.overtime_rates",
    "payroll.rule_sets",
    "payroll.seniority_scale",
    "payroll.settings",
    "payroll.severance_scale",
    "payroll.tax_brackets",
    "payroll.tax_reliefs",
    "qc.follow_up_policies",
    "production.molds",
    "production.packaging_bom_lines",
    "production.packaging_boms",
    "production.packaging_tolerances",
    "production.product_classifications",
    "production.recipe_lines",
    "production.recipes",
    "production.regrind_defaults",
    "production.resource_types",
    "production.shift_windows",
    "production.store_roles",
    "production.team_rotation",
    "production.waste_types",
    "production.waste_type_builtin_settings",
    "production.work_centers",
    "scan.scan_aliases",
    "warehouse.locations",
    "treasury.banks",
    "treasury.bank_branches",
    "treasury.settings",
    "procurement.invoice_settings",
    "treasury.alert_rules",
    "treasury.account_format_rules",
    "treasury.statement_profiles",
    "warehouse.stock_valuation",  # legacy: created by a dropped weighted-average migration, still present in databases that applied it
    "warehouse.sites",
    "warehouse.putaway_rules",
    "warehouse.product_barcodes",
    "warehouse.reorder_rules",
]

# Numbering counters restarted so the first real OF is OF-1, not OF-58.
RESET_SEQUENCES = ["production.work_orders", "production.regrind_orders", "qc.non_conformities"]


class ResetError(Exception):
    """The database is not in a state this script is willing to wipe."""


def _split(qualified: str) -> tuple[str, str]:
    schema, table = qualified.split(".", 1)
    return schema, table


def _ident(qualified: str) -> sql.Composed:
    schema, table = _split(qualified)
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def live_tables(connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT n.nspname || '.' || c.relname
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        """
    ).fetchall()
    return {row[0] for row in rows}


def check_ready(connection) -> set[str]:
    """Raises ResetError unless every live table is classified and there is one tenant."""
    live = live_tables(connection)
    classified = set(PURGE_TABLES) | set(EDITED_TABLES) | set(KEPT_TABLES)
    unclassified = sorted(live - classified)
    if unclassified:
        raise ResetError(
            "these tables are not classified in scripts/reset_operational_data.py "
            "(add each to PURGE_TABLES, EDITED_TABLES or KEPT_TABLES): " + ", ".join(unclassified)
        )
    tenants = [row[0] for row in connection.execute("SELECT DISTINCT tenant_id FROM core.users").fetchall()]
    if len(tenants) > 1:
        raise ResetError(f"more than one tenant in core.users ({', '.join(sorted(tenants))}); this reset is whole-database")
    return live


def _count(connection, qualified: str, where: sql.Composable | None = None, params: tuple = ()) -> int:
    query = sql.SQL("SELECT count(*) FROM {}").format(_ident(qualified))
    if where is not None:
        query = sql.SQL("{} WHERE {}").format(query, where)
    return connection.execute(query, params).fetchone()[0]


def purge(connection, tenant_id: str, *, keep_customers: bool = False) -> dict[str, int]:
    """Runs the wipe on `connection` without committing; returns rows removed/zeroed per table."""
    live = check_ready(connection)
    report: dict[str, int] = {}

    tables = [t for t in PURGE_TABLES if t in live]
    for table in tables:
        report[table] = _count(connection, table)
    connection.execute(sql.SQL("TRUNCATE {}").format(sql.SQL(", ").join(_ident(t) for t in tables)))

    if not keep_customers:
        customers = sql.SQL("kind = 'customer' AND tenant_id = %s")
        report["core.partners (customers)"] = _count(connection, "core.partners", customers, (tenant_id,))
        connection.execute(
            "DELETE FROM core.partner_tag_links WHERE partner_id IN "
            "(SELECT id FROM core.partners WHERE kind = 'customer' AND tenant_id = %s)",
            (tenant_id,),
        )
        connection.execute("DELETE FROM core.partners WHERE kind = 'customer' AND tenant_id = %s", (tenant_id,))

    cursor = connection.execute(
        """
        UPDATE warehouse.stock_items
        SET quantity_on_hand = 0, quantity_reserved = 0, quantity_in_production = 0
        WHERE tenant_id = %s
          AND (quantity_on_hand <> 0 OR quantity_reserved <> 0 OR quantity_in_production <> 0)
        """,
        (tenant_id,),
    )
    report["warehouse.stock_items (zeroed)"] = cursor.rowcount

    if "treasury.accounts" in live:
        # The movements are gone, so each account goes back to its opening balance.
        cursor = connection.execute(
            "UPDATE treasury.accounts SET balance = opening_balance WHERE tenant_id = %s AND balance <> opening_balance",
            (tenant_id,),
        )
        report["treasury.accounts (balance reset)"] = cursor.rowcount

    cursor = connection.execute(
        "UPDATE core.sequences SET next_value = 0 WHERE tenant_id = %s AND name = ANY(%s) AND next_value <> 0",
        (tenant_id, RESET_SEQUENCES),
    )
    report["core.sequences (reset)"] = cursor.rowcount

    if "maintenance.programs" in live:
        report["maintenance.programs (sweep restarted)"] = restart_program_sweeps(connection, tenant_id)
    return report


def restart_program_sweeps(connection, tenant_id: str) -> int:
    """Marks every preventive program as generated through yesterday. Its jobs are wiped
    with the rest of the operational data; without this the next sweep would re-raise
    every occurrence since the program was created, all of them overdue."""
    cursor = connection.execute(
        "UPDATE maintenance.programs SET last_generated_date = CURRENT_DATE - 1 WHERE tenant_id = %s",
        (tenant_id,),
    )
    return cursor.rowcount


def print_report(report: dict[str, int], verb: str) -> None:
    width = max(len(name) for name in report)
    for name, count in report.items():
        if count:
            print(f"  {name:<{width}}  {count:>8}")
    print(f"{verb} {sum(report.values())} row(s) across {sum(1 for c in report.values() if c)} table(s).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--keep-customers", action="store_true", help="Keep customer partners (suppliers are always kept).")
    parser.add_argument("--dry-run", action="store_true", help="Run the whole wipe, report it, then roll back.")
    parser.add_argument("--confirm-database", metavar="NAME", help="Name of the database to wipe for real; must match the connection.")
    args = parser.parse_args()

    if not args.dry_run and not args.confirm_database:
        parser.error("pass --dry-run to preview, or --confirm-database <name> to wipe for real")

    with get_connection() as connection:
        database = connection.execute("SELECT current_database()").fetchone()[0]
        if not args.dry_run and args.confirm_database != database:
            print(f"Refusing: connected to database '{database}' but --confirm-database is '{args.confirm_database}'.", file=sys.stderr)
            return 2
        try:
            report = purge(connection, args.tenant, keep_customers=args.keep_customers)
        except ResetError as error:
            connection.rollback()
            print(f"Refusing: {error}", file=sys.stderr)
            return 2
        if args.dry_run:
            connection.rollback()
            print(f"DRY RUN on '{database}' -- nothing was changed. A real run would remove:")
            print_report(report, "Would touch")
        else:
            connection.commit()
            print(f"Reset '{database}':")
            print_report(report, "Touched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
