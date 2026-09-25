from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

RECIPE_VALID_TRANSITIONS = {
    "draft": {"trial"},
    "trial": {"active", "draft"},
    "active": {"archived"},
    "archived": set(),
}


@dataclass(frozen=True)
class RecipeLine:
    component_product_id: str
    default_percentage: float
    min_percentage: float
    max_percentage: float
    is_hard_limit: bool


@dataclass(frozen=True)
class Recipe:
    id: str
    target_product_id: str
    version: int
    status: str
    target_moisture_percentage: float | None
    origin: str
    ai_confidence: float | None
    previous_recipe_id: str | None
    lines: tuple[RecipeLine, ...]


def validate_composition(lines: tuple[RecipeLine, ...]) -> Result[tuple[str, ...]]:
    """Ok holds soft-limit warnings (non-blocking); hard-limit violations always Err."""
    if not lines:
        return Err("EMPTY_RECIPE", "a recipe must have at least one component", "une recette doit avoir au moins un composant")

    warnings: list[str] = []
    total = 0.0
    for line in lines:
        if line.min_percentage < 0 or line.max_percentage > 100 or line.min_percentage > line.max_percentage:
            return Err(
                "INVALID_RANGE",
                f"invalid percentage range for {line.component_product_id}",
                f"plage de pourcentage invalide pour {line.component_product_id}",
            )
        if line.default_percentage < line.min_percentage or line.default_percentage > line.max_percentage:
            if line.is_hard_limit:
                return Err(
                    "HARD_LIMIT_VIOLATION",
                    f"{line.component_product_id} is outside its hard limit range",
                    f"{line.component_product_id} est hors de sa plage limite stricte",
                )
            warnings.append(f"{line.component_product_id} is outside its soft limit range")
        total += line.default_percentage

    if abs(total - 100.0) > 0.01:
        return Err(
            "INVALID_TOTAL",
            f"component percentages must sum to 100%, got {total}",
            f"la somme des pourcentages des composants doit être 100 %, reçu {total}",
        )

    return Ok(tuple(warnings))


def transition_recipe(recipe: Recipe, new_status: str) -> Result[Recipe]:
    if new_status not in RECIPE_VALID_TRANSITIONS.get(recipe.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move recipe from {recipe.status} to {new_status}",
            f"impossible de faire passer la recette de {recipe.status} à {new_status}",
        )
    return Ok(
        Recipe(
            id=recipe.id,
            target_product_id=recipe.target_product_id,
            version=recipe.version,
            status=new_status,
            target_moisture_percentage=recipe.target_moisture_percentage,
            origin=recipe.origin,
            ai_confidence=recipe.ai_confidence,
            previous_recipe_id=recipe.previous_recipe_id,
            lines=recipe.lines,
        )
    )
