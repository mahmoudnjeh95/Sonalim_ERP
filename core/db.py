from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        yield connection
