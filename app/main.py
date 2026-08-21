import os

import psycopg
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="3S ERP", version="0.1.0")
Instrumentator().instrument(app).expose(app)


@app.get("/")
def index() -> dict[str, str]:
    return {"service": "3S ERP", "status": "running"}


@app.get("/health")
def health() -> dict[str, str]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT 1")
    return {"status": "healthy"}