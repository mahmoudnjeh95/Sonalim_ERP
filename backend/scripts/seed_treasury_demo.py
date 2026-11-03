"""Seeds demo treasury data for the `demo` tenant: a bank, three accounts, a customer invoice paid in two
instalments, a supplier invoice, and a cheque waiting to be collected. Dev-only and idempotent: it does
nothing if the demo bank already exists.

    python -m scripts.seed_treasury_demo
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import psycopg
from ulid import ULID

from core.db import get_connection
from modules.finance.api.service import InvoiceService
from modules.finance.events import treasury_consumers as finance_consumers
from modules.procurement.api.invoice_service import PurchaseInvoiceService
from modules.procurement.events import treasury_consumers as procurement_consumers
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.service import AccountService, BankService

TENANT = "demo"
BANK_NAME = "Banque de démonstration"
SYSTEM = "system:seed"


def _deliver(connection: psycopg.Connection, consumers, document_id: str, event_type: str) -> None:
    """The worker is not running in dev; hand the document's event to the consumer directly."""
    row = connection.execute(
        "SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = %s "
        "AND (payload->'payload'->>'receipt_id' = %s OR payload->'payload'->>'disbursement_id' = %s) LIMIT 1",
        (TENANT, event_type, document_id, document_id),
    ).fetchone()
    handler = consumers._handle_posted
    handler(connection, row[0])


def _partner(connection: psycopg.Connection, name: str, kind: str) -> str:
    row = connection.execute("SELECT id FROM core.partners WHERE tenant_id = %s AND name = %s", (TENANT, name)).fetchone()
    if row:
        return row[0]
    partner_id = str(ULID())
    connection.execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, %s, %s, 'active')",
        (partner_id, TENANT, name, kind),
    )
    return partner_id


def seed(connection: psycopg.Connection) -> str:
    if connection.execute("SELECT 1 FROM treasury.banks WHERE tenant_id = %s AND name = %s", (TENANT, BANK_NAME)).fetchone():
        return "already seeded"
    actor = connection.execute("SELECT id FROM core.users WHERE tenant_id = %s ORDER BY created_at LIMIT 1", (TENANT,)).fetchone()
    if actor is None:
        return "no demo user: run scripts.seed_dev first"
    actor_id = actor[0]
    today = datetime.date.today()

    bank = BankService(connection).create_bank(tenant_id=TENANT, actor_id=actor_id, name=BANK_NAME, country="ML").value
    branch = BankService(connection).add_branch(tenant_id=TENANT, actor_id=actor_id, bank_id=bank["id"], name="Agence centrale", city="Bamako").value
    accounts = AccountService(connection)
    bank_account = accounts.create_account(
        tenant_id=TENANT, actor_id=actor_id, kind="bank",
        fields={"name": "Compte courant XOF", "currency": "XOF", "branch_id": branch["id"], "account_number": "DEMO-0001",
                "opening_balance": 5_000_000, "ledger_account_code": "521"}).value
    cash = accounts.create_account(
        tenant_id=TENANT, actor_id=actor_id, kind="cash",
        fields={"name": "Caisse principale", "currency": "XOF", "opening_balance": 250_000, "ledger_account_code": "571"}).value
    accounts.create_account(
        tenant_id=TENANT, actor_id=actor_id, kind="mobile_money",
        fields={"name": "Orange Money", "currency": "XOF", "operator": "orange_money", "phone": "70000000",
                "ledger_account_code": "552"})

    customer = _partner(connection, "Client démo", "customer")
    supplier = _partner(connection, "Fournisseur démo", "supplier")
    documents = DocumentService(connection)

    invoice = InvoiceService(connection).create_draft_invoice(tenant_id=TENANT, partner_id=customer, amount=1_200_000.0, currency="XOF")
    InvoiceService(connection).issue_invoice(tenant_id=TENANT, actor_id=actor_id, invoice_id=invoice.id, correlation_id="seed")
    for amount, payment in ((500_000, {"method": "transfer", "account_id": bank_account["id"]}),
                            (300_000, {"method": "cash", "account_id": cash["id"]})):
        receipt = documents.create_and_post(
            tenant_id=TENANT, actor_id=actor_id, direction="in", partner_id=customer, doc_date=today, currency="XOF",
            payments=[{**payment, "amount": amount}], allocations=[{"invoice_id": invoice.id, "amount": amount}],
            reason="advance", correlation_id="seed")
        _deliver(connection, finance_consumers, receipt.value["id"], "treasury.receipt.posted")

    purchase = PurchaseInvoiceService(connection)
    supplier_invoice = purchase.create_draft(
        tenant_id=TENANT, actor_id=actor_id, partner_id=supplier, supplier_invoice_number=f"DEMO-{today:%Y%m%d}",
        invoice_date=today, due_date=today + datetime.timedelta(days=30), amount=Decimal("640000"))
    purchase.validate(tenant_id=TENANT, actor_id=actor_id, invoice_id=supplier_invoice.value["id"], correlation_id="seed")

    documents.create_and_post(
        tenant_id=TENANT, actor_id=actor_id, direction="in", partner_id=customer, doc_date=today, currency="XOF",
        payments=[{"method": "cheque", "amount": 150_000, "number": "CHQ-DEMO-1", "bank_name": "Banque de démonstration",
                   "due_date": today + datetime.timedelta(days=7)}],
        with_details=False, correlation_id="seed")
    return "seeded"


def main() -> None:
    with get_connection() as connection:
        outcome = seed(connection)
        connection.commit()
    print(f"treasury demo data: {outcome}")


if __name__ == "__main__":
    main()
