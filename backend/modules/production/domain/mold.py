from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_MOLD_TYPES = {"PC", "PL"}


@dataclass(frozen=True)
class Mold:
    id: str
    code: str
    name: str
    type: str


def validate_mold(*, code: str, type: str) -> Result[None]:
    if not code.strip():
        return Err("INVALID_CODE", "mold code is required", "le code du moule est obligatoire")
    if type not in VALID_MOLD_TYPES:
        return Err("INVALID_TYPE", "mold type must be PC or PL", "le type de moule doit être PC ou PL")
    return Ok(None)
