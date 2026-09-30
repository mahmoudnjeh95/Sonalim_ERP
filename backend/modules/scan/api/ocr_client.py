"""The call to the OCR container (compose service `ocr`): one photo in, the cells it read out."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class OcrUnavailable(Exception):
    """The container did not answer with a reading: down, restarting, too slow, or broken."""


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
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as error:
            raise OcrUnavailable(str(getattr(error, "reason", error))) from error
