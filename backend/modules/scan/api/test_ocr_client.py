"""OcrClient's mapping from HTTP failures to OcrUnavailable vs OcrReadError. No DB needed."""
from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from modules.scan.api.ocr_client import OcrClient, OcrReadError, OcrUnavailable


def _http_error(status: int, body: bytes = b"boom") -> urllib.error.HTTPError:
    import io

    return urllib.error.HTTPError(
        url="http://ocr/read", code=status, msg="error", hdrs=None, fp=io.BytesIO(body),
    )


def test_a_5xx_outage_status_raises_ocr_unavailable(monkeypatch):
    def raise_502(request, timeout):
        raise _http_error(502)

    monkeypatch.setattr(urllib.request, "urlopen", raise_502)
    with pytest.raises(OcrUnavailable):
        OcrClient("http://ocr").read(b"img", None)


def test_503_and_504_also_raise_ocr_unavailable(monkeypatch):
    for status in (503, 504):
        monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout, status=status: (_ for _ in ()).throw(_http_error(status)))
        with pytest.raises(OcrUnavailable):
            OcrClient("http://ocr").read(b"img", None)


def test_any_other_http_status_raises_ocr_read_error(monkeypatch):
    def raise_500(request, timeout):
        raise _http_error(500, body=b"Internal Server Error: bad image")

    monkeypatch.setattr(urllib.request, "urlopen", raise_500)
    with pytest.raises(OcrReadError) as excinfo:
        OcrClient("http://ocr").read(b"img", None)
    assert "500" in str(excinfo.value)
