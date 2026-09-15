#!/usr/bin/env python3
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "postgresql://erp:erp@localhost:5432/erp"
sys.path.insert(0, str(Path(__file__).parent))

from core.db import get_connection

with get_connection() as conn:
    # Check tables
    tables = conn.execute("""
    SELECT schemaname, tablename FROM pg_tables
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY schemaname, tablename
    """).fetchall()

    print('Database tables:')
    current_schema = None
    for schema, table in tables:
        if schema != current_schema:
            print(f'\n{schema}:')
            current_schema = schema
        print(f'  - {table}')

    # Check if qc.quality_reports exists and has data
    print('\n\nChecking QC tables:')
    try:
        qr_count = conn.execute('SELECT COUNT(*) FROM qc.quality_reports').fetchone()[0]
        print(f'  qc.quality_reports: {qr_count} rows')
    except Exception as e:
        print(f'  qc.quality_reports: ERROR - {e}')

    try:
        nc_count = conn.execute('SELECT COUNT(*) FROM qc.non_conformities').fetchone()[0]
        print(f'  qc.non_conformities: {nc_count} rows')
    except Exception as e:
        print(f'  qc.non_conformities: ERROR - {e}')
