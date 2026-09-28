"""Every payroll endpoint hangs off this router; each area adds its own sub-router here."""
from __future__ import annotations

from fastapi import APIRouter

from modules.payroll.api.routes_rules import router as rules_router

router = APIRouter(prefix="/payroll", tags=["payroll"])
router.include_router(rules_router)
