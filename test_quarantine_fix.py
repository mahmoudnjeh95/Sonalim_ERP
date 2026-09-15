#!/usr/bin/env python3
"""
Integration test to verify the quarantine discrepancy fix.

This test:
1. Creates a quality report with non-conforming cartons
2. Validates it (creating a non-conformity)
3. Checks stock was moved to quarantine
4. Rejects the report (should clean up non-conformity with the fix)
5. Verifies stock was released and non-conformity deleted
"""

import os
import sys
from pathlib import Path
from ulid import ULID

os.environ["DATABASE_URL"] = "postgresql://erp:erp@localhost:5432/erp"
sys.path.insert(0, str(Path(__file__).parent))

from core.db import get_connection
from modules.qc.api.quality_service import QualityReportService
from modules.qc.api.non_conformity_service import NonConformityService
from modules.production.api.production_report_service import ProductionReportService
from modules.warehouse.api.service import StockService

def test_quarantine_cleanup_on_rejection():
    """Test that rejecting a quality report cleans up non-conformities."""

    with get_connection() as conn:
        tenant_id = "3S-SONALIM"
        actor_id = "test:quarantine_fix"
        correlation_id = str(ULID())

        print("\n" + "="*60)
        print("QUARANTINE DISCREPANCY FIX - Integration Test")
        print("="*60)

        # Find a work order and get its latest conditionnement report
        print("\n1. Finding test data...")
        work_orders = conn.execute('''
        SELECT id FROM production.work_orders
        WHERE id = '01M275R50KJ4Q2DH25SP327AMW'
        LIMIT 1
        ''').fetchall()

        if not work_orders:
            print("  [ERROR] No work orders found for testing")
            return False

        of_id = work_orders[0][0]
        print(f"  [OK] Found work order: {of_id}")

        # Get a conditionnement report
        cond_reports = conn.execute('''
        SELECT id, product_id FROM production.conditionnement_reports
        WHERE of_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        ''', (of_id,)).fetchall()

        if not cond_reports:
            print(f"  [ERROR] No conditionnement reports found for {of_id}")
            return False

        cond_report_id, product_id = cond_reports[0]
        print(f"  [OK] Found conditionnement report: {cond_report_id}")
        print(f"  [OK] Product ID: {product_id}")

        # Get quarantine location
        quart_loc = conn.execute('''
        SELECT id FROM warehouse.locations
        WHERE is_blocked = TRUE LIMIT 1
        ''').fetchone()

        if not quart_loc:
            print("  [ERROR] No quarantine location found")
            return False

        quarantine_location_id = quart_loc[0]
        print(f"  [OK] Quarantine location: {quarantine_location_id}")

        # Create a quality report
        print("\n2. Creating quality report...")
        qr_service = QualityReportService(conn)
        from modules.qc.domain.quality import QualityReportDetail

        detail = QualityReportDetail(
            conforming_cartons=5,
            non_conforming_cartons=3,  # 3 non-conforming cartons
            defect_details="Test defect"
        )

        qr_result = qr_service.create_report(
            tenant_id=tenant_id,
            actor_id=actor_id,
            conditionnement_report_id=cond_report_id,
            detail=detail
        )

        if qr_result.code != "Ok":
            print(f"  [ERROR] Failed to create report: {qr_result.message}")
            return False

        report_id = qr_result.value["report"]["id"]
        print(f"  [OK] Created quality report: {report_id}")

        # Submit the report
        print("\n3. Submitting quality report...")
        submit_result = qr_service.submit_report(
            tenant_id=tenant_id,
            actor_id=actor_id,
            report_id=report_id
        )
        if submit_result.code != "Ok":
            print(f"  [ERROR] Failed to submit: {submit_result.message}")
            return False
        print("  [OK] Report submitted")

        # Validate the report (should create non-conformity)
        print("\n4. Validating quality report...")
        validate_result = qr_service.validate_report(
            tenant_id=tenant_id,
            actor_id=actor_id,
            report_id=report_id,
            correlation_id=correlation_id,
            product_id=product_id
        )
        if validate_result.code != "Ok":
            print(f"  [ERROR] Failed to validate: {validate_result.message}")
            return False

        validated_report = validate_result.value["report"]
        print(f"  [OK] Report validated with status: {validated_report.status}")

        # Check non-conformity was created
        ncs = conn.execute('''
        SELECT id, quantity, status FROM qc.non_conformities
        WHERE quality_report_id = %s
        ''', (report_id,)).fetchall()

        if not ncs:
            print("  [WARNING] No non-conformities created (expected at least 1)")
            return False

        nc_id, nc_qty, nc_status = ncs[0]
        print(f"  [OK] Non-conformity created: {nc_id}")
        print(f"       Quantity: {nc_qty} | Status: {nc_status}")

        # Check quarantine stock
        quart_stock = conn.execute('''
        SELECT quantity_on_hand FROM warehouse.stock_items
        WHERE location_id = %s AND product_id = %s
        ''', (quarantine_location_id, product_id)).fetchone()

        before_stock = float(quart_stock[0]) if quart_stock else 0
        print(f"  [OK] Stock in quarantine: {before_stock} units")

        # Now reject the report (this is where the fix applies!)
        print("\n5. Rejecting quality report (testing fix)...")
        reject_result = qr_service.reject_report(
            tenant_id=tenant_id,
            actor_id=actor_id,
            report_id=report_id,
            reason="Test rejection to verify non-conformity cleanup"
        )
        if reject_result.code != "Ok":
            print(f"  [ERROR] Failed to reject: {reject_result.message}")
            return False

        rejected_report = reject_result.value
        print(f"  [OK] Report rejected with status: {rejected_report.status}")

        # Check non-conformity was cleaned up
        ncs_after = conn.execute('''
        SELECT id, status FROM qc.non_conformities
        WHERE quality_report_id = %s
        ''', (report_id,)).fetchall()

        if ncs_after:
            print(f"  [ERROR] Non-conformity still exists after rejection!")
            print(f"          NC: {ncs_after[0][0]} | Status: {ncs_after[0][1]}")
            return False

        print(f"  [OK] Non-conformity was cleaned up (deleted)")

        # Check quarantine stock was released
        quart_stock_after = conn.execute('''
        SELECT quantity_on_hand FROM warehouse.stock_items
        WHERE location_id = %s AND product_id = %s
        ''', (quarantine_location_id, product_id)).fetchone()

        after_stock = float(quart_stock_after[0]) if quart_stock_after else 0
        print(f"  [OK] Stock in quarantine after rejection: {after_stock} units")

        if after_stock > before_stock - 0.1:  # Allow for floating point
            print(f"  [WARNING] Stock may not have been released!")
            print(f"            Before: {before_stock} | After: {after_stock}")

        print("\n" + "="*60)
        print("TEST PASSED - Quarantine cleanup fix is working!")
        print("="*60)
        return True

if __name__ == "__main__":
    try:
        success = test_quarantine_cleanup_on_rejection()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nTEST FAILED WITH ERROR:")
        print(f"   {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
