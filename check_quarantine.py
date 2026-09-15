#!/usr/bin/env python3
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "postgresql://erp:erp@localhost:5432/erp"
sys.path.insert(0, str(Path(__file__).parent))

from core.db import get_connection

with get_connection() as conn:
    # Check all quality reports
    rows = conn.execute('''
    SELECT qr.id, qr.of_id, qr.revision, qr.status, qr.created_at
    FROM qc.quality_reports qr
    WHERE qr.tenant_id = '3S-SONALIM'
    ORDER BY qr.created_at DESC
    LIMIT 15
    ''').fetchall()

    print('All recent quality reports:')
    if not rows:
        print('  (none found)')
    else:
        for row in rows:
            report_id, of_id, rev, status, created_at = row
            print(f'  OF: {of_id} | Rev: {rev} | Status: {status} | {created_at.date()}')

    # Check non-conformities
    nc_rows = conn.execute('''
    SELECT nc.reference, nc.of_id, nc.quantity, nc.status, nc.raised_at, nc.quality_report_id
    FROM qc.non_conformities nc
    WHERE nc.tenant_id = '3S-SONALIM'
    ORDER BY nc.raised_at DESC
    LIMIT 15
    ''').fetchall()

    print('\nRecent non-conformities:')
    if not nc_rows:
        print('  (none found)')
    else:
        for row in nc_rows:
            ref, of_id, qty, status, raised_at, qr_id = row
            date_str = raised_at.date() if raised_at else "N/A"
            linked = "linked" if qr_id else "orphaned"
            print(f'  {ref} | OF: {of_id} | Qty: {qty} | Status: {status} | {date_str} | {linked}')

    # Check stock in quarantine
    stock_rows = conn.execute('''
    SELECT si.product_id, si.quantity_on_hand, l.name, si.location_id
    FROM warehouse.stock_items si
    JOIN warehouse.locations l ON l.id = si.location_id AND l.is_blocked = TRUE
    WHERE si.tenant_id = '3S-SONALIM'
    AND si.quantity_on_hand > 0
    ''').fetchall()

    print('\nStock in blocked/quarantine locations:')
    if not stock_rows:
        print('  (none)')
    else:
        for row in stock_rows:
            product_id, qty, location, loc_id = row
            print(f'  {product_id}: {qty} units in {location} ({loc_id})')
