import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Local-dev convenience only: a .env at the repo root is loaded into the process
# environment before anything below reads it, so DATABASE_URL/GROQ_API_KEY/etc.
# work the same whether uvicorn is started from a VS Code terminal, its debugger,
# or a plain shell -- no launch config or manual `$env:` needed. A no-op wherever
# no .env exists (Docker, Vercel), which already inject these variables directly.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from core.audit import router as core_audit_router
from core.auth import router as auth_router
from core.db import close_pool, get_connection
from core.exchange_rates import currencies_router as core_currencies_router
from core.exchange_rates import router as core_exchange_rates_router
from core.migrations.runner import migrate_on_startup
from core.notifications import router as core_notifications_router
from core.tax_codes import router as core_tax_codes_router
from core.observability import ErrorReportingMiddleware, init_error_reporting, setup_logging
from core.partners import router as core_partners_router
from core.report_options import router as core_report_options_router
from core.roles import router as core_roles_router
from core.products import attributes_router as core_product_attributes_router
from core.products import router as core_products_router
from core.products import tags_router as core_product_tags_router
from core.products import uoms_router as core_uoms_router
from core.table_preferences import router as core_table_preferences_router
from core.user_avatars import router as core_user_avatars_router
from core.users import router as core_users_router
from modules.crm.api.router import router as crm_router
from modules.finance.api.ledger_router import router as finance_ledger_router
from modules.finance.api.receivables_router import router as finance_receivables_router
from modules.finance.api.router import router as finance_router
from modules.maintenance.api.router import router as maintenance_router
from modules.production.api.router import router as production_router
from modules.scan.api.router import router as scan_router
from modules.sales.api.router import router as sales_router
from modules.warehouse.api.router import router as warehouse_router
from modules.hr.api.router import router as hr_router
from modules.hr.api.presence_router import router as hr_presence_router
from modules.payroll.api.router import router as payroll_router
from modules.procurement.api.router import router as procurement_router
from modules.qc.api.router import router as qc_router
from modules.treasury.api.router import router as treasury_router


setup_logging()
init_error_reporting("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate_on_startup()
    yield
    close_pool()


app = FastAPI(title="Sonalim ERP", version="0.1.0", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)

# Added before CORS so it sits inside it: the 500 it answers with gets the CORS headers and the
# browser can read the {"detail": {...}} error instead of reporting a CORS failure.
app.add_middleware(ErrorReportingMiddleware)

# Dev-only: the Vite dev server and the API run on different origins (ports),
# so the browser blocks every request without this. Restrict to configured
# frontend origins rather than "*" since requests carry a Bearer session token.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(core_users_router)
app.include_router(core_user_avatars_router)
app.include_router(core_roles_router)
app.include_router(core_partners_router)
app.include_router(core_exchange_rates_router)
app.include_router(core_currencies_router)
app.include_router(core_products_router)
app.include_router(core_product_attributes_router)
app.include_router(core_product_tags_router)
app.include_router(core_uoms_router)
app.include_router(core_report_options_router)
app.include_router(core_table_preferences_router)
app.include_router(core_audit_router)
app.include_router(core_notifications_router)
app.include_router(core_tax_codes_router)
app.include_router(warehouse_router)
app.include_router(production_router)
app.include_router(crm_router)
app.include_router(sales_router)
app.include_router(finance_router)
app.include_router(finance_ledger_router)
app.include_router(finance_receivables_router)
app.include_router(hr_router)
app.include_router(hr_presence_router)
app.include_router(payroll_router)
app.include_router(procurement_router)
app.include_router(qc_router)
app.include_router(maintenance_router)
app.include_router(treasury_router)
app.include_router(scan_router)


@app.get("/")
def index() -> dict[str, str]:
    return {"service": "Sonalim ERP", "status": "running"}


@app.get("/health")
def health() -> dict[str, str]:
    with get_connection() as connection:
        connection.execute("SELECT 1")
    return {"status": "healthy"}
