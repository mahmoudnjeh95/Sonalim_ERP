import os
import time

import psycopg


def run() -> None:
    database_url = os.environ["DATABASE_URL"]
    print("Outbox worker started", flush=True)
    while True:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                SELECT event_id, event_type, payload
                FROM events.outbox
                WHERE sent_at IS NULL
                ORDER BY created_at
                LIMIT 100
                """
            ).fetchall()
        time.sleep(5)


if __name__ == "__main__":
    run()