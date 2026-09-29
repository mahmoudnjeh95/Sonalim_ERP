"""What every payroll route shares.

Routes open connections through `http.get_connection()` (never a direct import), so router tests
patch this one name. `finish` commits a successful write, or rolls it back and raises its refusal
as {"code", "message", "message_fr"} with the right status.
"""
from __future__ import annotations

from typing import NoReturn, TypeVar

from fastapi import HTTPException, Response, status

from core.db import get_connection as get_connection  # noqa: PLC0414 - re-exported patch point
from core.domain.result import Err, Result, err_detail

T = TypeVar("T")

CONFLICT_CODES = frozenset({
    "RULESET_LOCKED", "RULESET_IN_USE", "RULESET_NOT_CONFIRMED",
    "RUN_LOCKED", "RUN_NOT_CALCULATED", "RUN_NOT_APPROVED", "RUN_NOT_REVERSIBLE",
    "SAME_USER_APPROVAL", "PRESENCE_NOT_CLOSED", "PAYOUT_CONFIRMED", "PAYOUT_INCOMPLETE",
})


def status_for(err: Err) -> int:
    if err.code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if err.code in CONFLICT_CODES or err.code.startswith("DUPLICATE"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_ENTITY


def fail(err: Err) -> NoReturn:
    raise HTTPException(status_for(err), err_detail(err))


def finish(connection, result: Result[T]) -> T:
    if isinstance(result, Err):
        connection.rollback()
        fail(result)
    connection.commit()
    return result.value


def found(value: T | None, what_en: str, what_fr: str) -> T:
    if value is None:
        fail(Err("NOT_FOUND", f"{what_en} not found", f"{what_fr} introuvable"))
    return value


def csv_response(file_name: str, text: str) -> Response:
    """CSV as a download; the byte-order mark makes Excel read the accents as UTF-8."""
    return Response(content="﻿" + text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{file_name}"'})
