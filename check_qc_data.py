#!/usr/bin/env python3
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "postgresql://erp:erp@localhost:5432/erp"
sys.path.insert(0, str(Path(__file__).parent))

from core.db import get_connection

with get_connection() as conn:
    print('Checking QC data:')

    # Quality reports
    qr_count = conn.execute('SELECT COUNT(*) FROM qc.quality_reports').fetchone()[0]
    print(f'\nQuality Reports: {qr_count}')
    if qr_count > 0:
        reports = conn.execute('''
        SELECT id, of_id, revision, status, report_date
        FROM qc.quality_reports
        ORDER BY report_date DESC
        LIMIT 5
        ''').fetchall()
        for row in reports:
            print(f'  {row[0][:8]}... OF:{row[1]} Rev:{row[2]} Status:{row[3]} Date:{row[4]}')

    # Non-conformities
    nc_count = conn.execute('SELECT COUNT(*) FROM qc.non_conformities').fetchone()[0]
    print(f'\nNon-Conformities: {nc_count}')
    if nc_count > 0:
        ncs = conn.execute('''
        SELECT id, reference, of_id, quantity, status
        FROM qc.non_conformities
        ORDER BY raised_at DESC
        LIMIT 5
        ''').fetchall()
        for row in ncs:
            print(f'  {row[1]} OF:{row[2]} Qty:{row[3]} Status:{row[4]}')

    # Work orders
    wo_count = conn.execute('SELECT COUNT(*) FROM production.work_orders').fetchone()[0]
    print(f'\nWork Orders: {wo_count}')
    if wo_count > 0:
        wos = conn.execute('''
        SELECT id, status FROM production.work_orders
        ORDER BY created_at DESC LIMIT 5
        ''').fetchall()
        for row in wos:
            print(f'  {row[0]} {row[1]}')
