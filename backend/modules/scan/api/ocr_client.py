"""The call to the OCR container (compose service `ocr`): one photo in, the cells it read out."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class OcrUnavailable(Exception):
    """The container did not answer with a reading: down, restarting, too slow, or broken."""


class OcrReadError(Exception):
    """The container answered but refused this photo: an HTTP error that isn't an outage."""


class OcrClient:
    def __init__(self, base_url: str, timeout: float = 180) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def read(self, image: bytes, form_hint: str | None) -> dict:
        query = f"?{urllib.parse.urlencode({'form_hint': form_hint})}" if form_hint else ""
        request = urllib.request.Request(
            f"{self._base_url}/read{query}", data=image, method="POST", headers={"Content-Type": "application/octet-stream"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code in (502, 503, 504):
                raise OcrUnavailable(f"{error.code} {error.reason}") from error
            excerpt = ""
            try:
                excerpt = error.read(500).decode("utf-8", errors="replace")
            except Exception:
                pass
            raise OcrReadError(f"{error.code} {error.reason}: {excerpt}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as error:
            raise OcrUnavailable(str(getattr(error, "reason", error))) from error
