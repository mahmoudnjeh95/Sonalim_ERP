#!/usr/bin/env python3
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "postgresql://erp:erp@localhost:5432/erp"
sys.path.insert(0, str(Path(__file__).parent))

from core.db import get_connection

with get_connection() as conn:
    # Check all tenants
    tenants = conn.execute('SELECT id, name FROM tenants').fetchall()
    print('Tenants in database:')
    for tenant_id, name in tenants:
        print(f'  {tenant_id}: {name}')

    # Check any quality reports
    all_qr = conn.execute('SELECT COUNT(*) FROM qc.quality_reports').fetchone()
    print(f'\nTotal quality reports: {all_qr[0]}')

    # Check any non-conformities
    all_nc = conn.execute('SELECT COUNT(*) FROM qc.non_conformities').fetchone()
    print(f'Total non-conformities: {all_nc[0]}')

    # Check orders
    all_of = conn.execute('SELECT COUNT(*) FROM production.work_orders').fetchone()
    print(f'Total work orders: {all_of[0]}')

    if all_of[0] > 0:
        # Show recent orders
        recent = conn.execute('''
        SELECT id, status FROM production.work_orders
        ORDER BY created_at DESC LIMIT 5
        ''').fetchall()
        print('\nRecent work orders:')
        for of_id, status in recent:
            print(f'  {of_id}: {status}')
