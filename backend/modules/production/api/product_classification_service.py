from __future__ import annotations

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.product_classification import ProductClassification, validate_classification


class ProductClassificationService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def set_classification(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        product_id: str,
        category: str,
        is_regrind: bool = False,
        packaging_format: str | None = None,
        is_water: bool = False,
    ) -> Result[ProductClassification]:
        validation = validate_classification(category, is_regrind, packaging_format, is_water)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            INSERT INTO production.product_classifications (tenant_id, product_id, category, is_regrind, packaging_format, is_water)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, product_id)
            DO UPDATE SET category = EXCLUDED.category, is_regrind = EXCLUDED.is_regrind,
                packaging_format = EXCLUDED.packaging_format, is_water = EXCLUDED.is_water
            """,
            (tenant_id, product_id, category, is_regrind, packaging_format, is_water),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="product_classification.set",
            entity_type="product_classification",
            entity_id=product_id,
            payload={"category": category, "is_regrind": is_regrind, "packaging_format": packaging_format, "is_water": is_water},
        )
        return Ok(
            ProductClassification(
                product_id=product_id, category=category, is_regrind=is_regrind, packaging_format=packaging_format, is_water=is_water
            )
        )

    def get_classification(self, tenant_id: str, product_id: str) -> ProductClassification | None:
        row = self._connection.execute(
            """
            SELECT category, is_regrind, packaging_format, is_water
            FROM production.product_classifications
            WHERE tenant_id = %s AND product_id = %s
            """,
            (tenant_id, product_id),
        ).fetchone()
        if row is None:
            return None
        category, is_regrind, packaging_format, is_water = row
        return ProductClassification(
            product_id=product_id, category=category, is_regrind=is_regrind, packaging_format=packaging_format, is_water=is_water
        )

    def list_classifications(self, tenant_id: str, category: str | None = None) -> list[ProductClassification]:
        if category is not None:
            rows = self._connection.execute(
                """
                SELECT product_id, category, is_regrind, packaging_format, is_water
                FROM production.product_classifications
                WHERE tenant_id = %s AND category = %s
                ORDER BY created_at DESC
                """,
                (tenant_id, category),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT product_id, category, is_regrind, packaging_format, is_water
                FROM production.product_classifications
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [
            ProductClassification(
                product_id=product_id, category=row_category, is_regrind=is_regrind, packaging_format=packaging_format, is_water=is_water
            )
            for product_id, row_category, is_regrind, packaging_format, is_water in rows
        ]
