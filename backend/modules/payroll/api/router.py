"""Every payroll endpoint hangs off this router; each area adds its own sub-router here."""
from __future__ import annotations

from fastapi import APIRouter

from modules.payroll.api.routes_inputs import router as inputs_router
from modules.payroll.api.routes_payouts import router as payouts_router
from modules.payroll.api.routes_rules import router as rules_router
from modules.payroll.api.routes_declarations import router as declarations_router
from modules.payroll.api.routes_runs import router as runs_router

router = APIRouter(prefix="/payroll", tags=["payroll"])
router.include_router(rules_router)
router.include_router(runs_router)
router.include_router(inputs_router)
router.include_router(payouts_router)
router.include_router(declarations_router)
