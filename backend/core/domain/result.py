from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T


@dataclass(frozen=True)
class Err:
    code: str
    message: str
    # The same refusal in French, for a user working in French. The English stays in `message`
    # for logs, scripts and tests; `None` until the site that builds the error is translated.
    message_fr: str | None = None


Result = Ok[T] | Err


def err_detail(err: Err) -> dict[str, str | None]:
    """The HTTP error body for a refusal: the frontend shows `message_fr` to a French user."""
    return {"code": err.code, "message": err.message, "message_fr": err.message_fr}
