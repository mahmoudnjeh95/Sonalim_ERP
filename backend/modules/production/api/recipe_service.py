from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.recipe import Recipe, RecipeLine, transition_recipe, validate_composition


class RecipeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_recipe(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        target_product_id: str,
        lines: tuple[RecipeLine, ...],
        target_moisture_percentage: float | None = None,
        origin: str = "manual",
        ai_confidence: float | None = None,
        previous_recipe_id: str | None = None,
    ) -> Result[Recipe]:
        validation = validate_composition(lines)
        if isinstance(validation, Err):
            return validation

        # Both target_product_id and each component_product_id reach here as
        # caller-supplied strings (the recipe dialog used to allow free text on
        # both) with no format guarantee. Without this check a typo or made-up
        # SKU trips recipes_target_product_id_fkey / recipe_lines_component_product_id_fkey
        # as a raw psycopg IntegrityError -- an unhandled 500 that also drops the
        # response's CORS headers, which the browser then misreports as a CORS
        # failure instead of the real "no such product" problem.
        wanted_product_ids = {target_product_id, *(line.component_product_id for line in lines)}
        found_product_ids = {
            row[0]
            for row in self._connection.execute(
                "SELECT id FROM core.products WHERE tenant_id = %s AND id = ANY(%s)",
                (tenant_id, list(wanted_product_ids)),
            ).fetchall()
        }
        missing_product_ids = wanted_product_ids - found_product_ids
        if missing_product_ids:
            return Err("PRODUCT_NOT_FOUND", f"product(s) not found: {', '.join(sorted(missing_product_ids))}")

        # Same FOR-UPDATE-without-aggregate pattern as PackagingBomService.create_bom:
        # lock every existing row for this target product, compute the next version in
        # Python, so a concurrent create_recipe() for the same product serializes here.
        existing_versions = self._connection.execute(
            """
            SELECT version FROM production.recipes
            WHERE tenant_id = %s AND target_product_id = %s
            FOR UPDATE
            """,
            (tenant_id, target_product_id),
        ).fetchall()
        version = max((row[0] for row in existing_versions), default=0) + 1

        recipe_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.recipes
                (id, tenant_id, target_product_id, version, status, target_moisture_percentage, origin, ai_confidence, previous_recipe_id)
            VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s, %s)
            """,
            (
                recipe_id,
                tenant_id,
                target_product_id,
                version,
                target_moisture_percentage,
                origin,
                ai_confidence,
                previous_recipe_id,
            ),
        )
        for line in lines:
            self._connection.execute(
                """
                INSERT INTO production.recipe_lines
                    (id, recipe_id, tenant_id, component_product_id, default_percentage, min_percentage, max_percentage, is_hard_limit)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()),
                    recipe_id,
                    tenant_id,
                    line.component_product_id,
                    line.default_percentage,
                    line.min_percentage,
                    line.max_percentage,
                    line.is_hard_limit,
                ),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="recipe.created",
            entity_type="recipe",
            entity_id=recipe_id,
            payload={"target_product_id": target_product_id, "version": version},
        )
        return Ok(
            Recipe(
                id=recipe_id,
                target_product_id=target_product_id,
                version=version,
                status="draft",
                target_moisture_percentage=target_moisture_percentage,
                origin=origin,
                ai_confidence=ai_confidence,
                previous_recipe_id=previous_recipe_id,
                lines=lines,
            )
        )

    def create_new_version(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        previous_recipe_id: str,
        lines: tuple[RecipeLine, ...],
        target_moisture_percentage: float | None = None,
        origin: str = "manual",
        ai_confidence: float | None = None,
    ) -> Result[Recipe]:
        previous = self._get_recipe(tenant_id, previous_recipe_id)
        if previous is None:
            return Err("NOT_FOUND", f"recipe {previous_recipe_id} not found")
        return self.create_recipe(
            tenant_id=tenant_id,
            actor_id=actor_id,
            target_product_id=previous.target_product_id,
            lines=lines,
            target_moisture_percentage=target_moisture_percentage,
            origin=origin,
            ai_confidence=ai_confidence,
            previous_recipe_id=previous_recipe_id,
        )

    def promote_to_trial(self, *, tenant_id: str, actor_id: str, recipe_id: str) -> Result[Recipe]:
        return self._apply_transition(tenant_id, actor_id, recipe_id, "trial")

    def reject_to_draft(self, *, tenant_id: str, actor_id: str, recipe_id: str) -> Result[Recipe]:
        return self._apply_transition(tenant_id, actor_id, recipe_id, "draft")

    def archive_recipe(self, *, tenant_id: str, actor_id: str, recipe_id: str) -> Result[Recipe]:
        return self._apply_transition(tenant_id, actor_id, recipe_id, "archived")

    def activate_recipe(self, *, tenant_id: str, actor_id: str, recipe_id: str) -> Result[Recipe]:
        target_row = self._connection.execute(
            "SELECT target_product_id FROM production.recipes WHERE id = %s AND tenant_id = %s",
            (recipe_id, tenant_id),
        ).fetchone()
        if target_row is None:
            return Err("NOT_FOUND", f"recipe {recipe_id} not found")
        target_product_id = target_row[0]

        # Family-scoped lock, same reasoning as PackagingBomService.activate_bom: the
        # "only one active recipe per target product" invariant spans every recipe for
        # this product, not just the one being activated.
        family_rows = self._connection.execute(
            """
            SELECT id, status FROM production.recipes
            WHERE tenant_id = %s AND target_product_id = %s
            FOR UPDATE
            """,
            (tenant_id, target_product_id),
        ).fetchall()
        status_by_id = dict(family_rows)
        if recipe_id not in status_by_id:
            return Err("NOT_FOUND", f"recipe {recipe_id} not found")

        recipe = self._get_recipe(tenant_id, recipe_id)
        assert recipe is not None
        result = transition_recipe(recipe, "active")
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            UPDATE production.recipes SET status = 'archived'
            WHERE tenant_id = %s AND target_product_id = %s AND status = 'active' AND id != %s
            """,
            (tenant_id, target_product_id, recipe_id),
        )
        self._connection.execute("UPDATE production.recipes SET status = 'active' WHERE id = %s", (recipe_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="recipe.activated",
            entity_type="recipe",
            entity_id=recipe_id,
            payload={"target_product_id": target_product_id},
        )
        return Ok(self._get_recipe(tenant_id, recipe_id))

    def _apply_transition(self, tenant_id: str, actor_id: str, recipe_id: str, new_status: str) -> Result[Recipe]:
        recipe = self._get_recipe(tenant_id, recipe_id, for_update=True)
        if recipe is None:
            return Err("NOT_FOUND", f"recipe {recipe_id} not found")
        result = transition_recipe(recipe, new_status)
        if isinstance(result, Err):
            return result
        self._connection.execute("UPDATE production.recipes SET status = %s WHERE id = %s", (new_status, recipe_id))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="recipe.status_changed",
            entity_type="recipe",
            entity_id=recipe_id,
            payload={"from_status": recipe.status, "to_status": new_status},
        )
        return Ok(self._get_recipe(tenant_id, recipe_id))

    def get_recipe(self, tenant_id: str, recipe_id: str) -> Recipe | None:
        return self._get_recipe(tenant_id, recipe_id)

    def list_recipes(
        self, tenant_id: str, target_product_id: str | None = None, status: str | None = None
    ) -> list[Recipe]:
        query = "SELECT id FROM production.recipes WHERE tenant_id = %s"
        params: list[object] = [tenant_id]
        if target_product_id is not None:
            query += " AND target_product_id = %s"
            params.append(target_product_id)
        if status is not None:
            query += " AND status = %s"
            params.append(status)

        rows = self._connection.execute(query, params).fetchall()
        recipes = [self._get_recipe(tenant_id, recipe_id) for (recipe_id,) in rows]
        return [recipe for recipe in recipes if recipe is not None]

    def _get_recipe(self, tenant_id: str, recipe_id: str, *, for_update: bool = False) -> Recipe | None:
        if for_update:
            row = self._connection.execute(
                """
                SELECT id, target_product_id, version, status, target_moisture_percentage, origin, ai_confidence, previous_recipe_id
                FROM production.recipes WHERE id = %s AND tenant_id = %s
                FOR UPDATE
                """,
                (recipe_id, tenant_id),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT id, target_product_id, version, status, target_moisture_percentage, origin, ai_confidence, previous_recipe_id
                FROM production.recipes WHERE id = %s AND tenant_id = %s
                """,
                (recipe_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        rid, target_product_id, version, status, moisture, origin, ai_confidence, previous_recipe_id = row

        line_rows = self._connection.execute(
            """
            SELECT component_product_id, default_percentage, min_percentage, max_percentage, is_hard_limit
            FROM production.recipe_lines WHERE recipe_id = %s AND tenant_id = %s
            """,
            (recipe_id, tenant_id),
        ).fetchall()
        lines = tuple(
            RecipeLine(
                component_product_id=component_product_id,
                default_percentage=float(default_percentage),
                min_percentage=float(min_percentage),
                max_percentage=float(max_percentage),
                is_hard_limit=is_hard_limit,
            )
            for component_product_id, default_percentage, min_percentage, max_percentage, is_hard_limit in line_rows
        )
        return Recipe(
            id=rid,
            target_product_id=target_product_id,
            version=version,
            status=status,
            target_moisture_percentage=float(moisture) if moisture is not None else None,
            origin=origin,
            ai_confidence=float(ai_confidence) if ai_confidence is not None else None,
            previous_recipe_id=previous_recipe_id,
            lines=lines,
        )
