#!/usr/bin/env python3
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "postgresql://erp:erp@localhost:5432/erp"
sys.path.insert(0, str(Path(__file__).parent))

from core.db import get_connection

with get_connection() as conn:
    # Check conditionnement_reports columns
    cols = conn.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'production' AND table_name = 'conditionnement_reports'
    ORDER BY ordinal_position
    """).fetchall()

    print('conditionnement_reports columns:')
    for col, dtype in cols:
        print(f'  {col}: {dtype}')

    # Get a sample row
    rows = conn.execute('''
    SELECT * FROM production.conditionnement_reports LIMIT 1
    ''').fetchall()
    if rows:
        print('\nSample row columns:')
        desc = conn.execute('''
        SELECT * FROM production.conditionnement_reports LIMIT 1
        ''').description
        for desc_item in desc:
            print(f'  {desc_item[0]}')
