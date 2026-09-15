#!/usr/bin/env python3
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "postgresql://erp:erp@localhost:5432/erp"
sys.path.insert(0, str(Path(__file__).parent))

from core.db import get_connection

with get_connection() as conn:
    # Check what quality reports point to
    qr_cols = conn.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'qc' AND table_name = 'quality_reports'
    ORDER BY ordinal_position
    """).fetchall()

    print('quality_reports columns:')
    for col, dtype in qr_cols:
        print(f'  {col}: {dtype}')

    # Get a sample quality report
    qr = conn.execute('''
    SELECT id, of_id, conditionnement_report_id FROM qc.quality_reports LIMIT 1
    ''').fetchone()

    if qr:
        print(f'\nSample quality report:')
        print(f'  ID: {qr[0]}')
        print(f'  OF ID: {qr[1]}')
        print(f'  Conditionnement Report ID: {qr[2]}')

        # Check if that cond report exists
        cond = conn.execute('''
        SELECT report_id FROM production.conditionnement_reports
        WHERE report_id = %s
        ''', (qr[2],)).fetchone()

        if cond:
            print(f'  Conditionnement report exists!')
        else:
            print(f'  Conditionnement report NOT found!')

        # Get the OF
        of = conn.execute('''
        SELECT id FROM production.work_orders WHERE id = %s
        ''', (qr[1],)).fetchone()

        if of:
            print(f'  Work order exists!')
