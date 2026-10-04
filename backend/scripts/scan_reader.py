"""The scan reading queue on its own, for local dev without Docker or RabbitMQ.

The server runs this loop inside `worker/main.py`, which also needs a broker for the
event consumers. Locally there is usually no RabbitMQ, so this script runs the same
`read_next_page` step against the same OCR container and nothing else. Stop it with
Ctrl+C; a page interrupted mid-read is put back in the queue on the next start.
"""
from __future__ import annotations

import os
import pathlib
import time

from dotenv import load_dotenv

# The repo-root .env explicitly: `load_dotenv()` searches upward from the *current*
# directory, and a `backend/.env` -- which exists on some dev boxes -- would shadow it
# and hide OCR_URL. Both files are loaded, root last so it wins on shared keys.
_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env", override=True)

from core.db import get_connection
from modules.scan.api.ocr_client import OcrClient
from modules.scan.api.reader import read_next_page, requeue_stale_reads

IDLE_SECONDS = 2
RETRY_SECONDS = 15


def main() -> None:
    ocr_url = os.environ.get("OCR_URL")
    if not ocr_url:
        raise SystemExit("OCR_URL is not set: start the OCR service and set OCR_URL in .env")
    client = OcrClient(ocr_url)
    print(f"Scan reader started against {ocr_url}", flush=True)
    try:
        with get_connection() as db_connection:
            requeued = requeue_stale_reads(db_connection)
        if requeued:
            print(f"Put {requeued} interrupted page(s) back in the queue", flush=True)
    except Exception as error:  # a startup DB hiccup must not stop the loop
        print(f"Requeue of stale reads failed at startup: {error}", flush=True)
    while True:
        try:
            with get_connection() as db_connection:
                step = read_next_page(db_connection, client.read)
        except Exception as error:  # retried next tick, never kills the loop
            print(f"Scan reader failed: {error}", flush=True)
            step = ("", "retry")
        if step is None:
            time.sleep(IDLE_SECONDS)
            continue
        page_id, outcome = step
        print(f"page {page_id}: {outcome}", flush=True)
        if outcome in ("retry", "failed"):
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    main()
