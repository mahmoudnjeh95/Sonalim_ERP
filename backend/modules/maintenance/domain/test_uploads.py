"""An upload is read with a ceiling: a huge body is refused without ever being held whole."""
from __future__ import annotations

import io

from modules.maintenance.domain.uploads import MAX_IMAGE_BYTES, read_capped


class _CountingFile(io.BytesIO):
    """Remembers how much was actually pulled out of the request's file."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.read_bytes = 0

    def read(self, size: int = -1) -> bytes:  # type: ignore[override]
        chunk = super().read(size)
        self.read_bytes += len(chunk)
        return chunk


def test_a_normal_photo_is_read_whole():
    file = _CountingFile(b"\xff\xd8\xff" + b"0" * 2048)
    data = read_capped(file)
    assert data == file.getvalue() and len(data) == 2051


def test_a_body_over_the_limit_stops_just_past_it_instead_of_buffering_everything():
    file = _CountingFile(b"0" * (MAX_IMAGE_BYTES + 50 * 1024 * 1024))

    data = read_capped(file)

    # One byte past the limit is enough for the service to refuse it...
    assert len(data) == MAX_IMAGE_BYTES + 1
    # ...and the other 50 MB never left the request.
    assert file.read_bytes <= MAX_IMAGE_BYTES + 1


def test_an_empty_part_reads_empty():
    assert read_capped(_CountingFile(b"")) == b""
