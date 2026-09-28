"""Every payroll endpoint hangs off this router; each area adds its own sub-router here."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/payroll", tags=["payroll"])
