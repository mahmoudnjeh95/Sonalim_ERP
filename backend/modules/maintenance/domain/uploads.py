"""How an uploaded photo is read off a request.

The size limit is enforced by the services (map_service, job_service), but a router
that reads the whole part first would already be holding it: a 500 MB body is 500 MB
of memory before anything refuses it. `read_capped` stops one byte past the limit --
enough for the service to refuse it, never more.
"""
from __future__ import annotations

from typing import Protocol

ALLOWED_IMAGE_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_IMAGE_BYTES = 10 * 1024 * 1024

_CHUNK = 64 * 1024


class _Readable(Protocol):
    def read(self, size: int = -1) -> bytes: ...


def read_capped(file: _Readable, limit: int = MAX_IMAGE_BYTES) -> bytes:
    """The upload's bytes, up to `limit` + 1. The extra byte is what tells the service
    "over the limit" apart from "exactly at it", so the refusal stays the service's."""
    chunks: list[bytes] = []
    size = 0
    while size <= limit:
        chunk = file.read(min(_CHUNK, limit + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)
