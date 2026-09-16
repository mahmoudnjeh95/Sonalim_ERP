from core.domain.result import Err, Ok
from modules.production.domain.recipe import Recipe, RecipeLine, transition_recipe, validate_composition


def _line(pct: float, is_hard_limit: bool = False, min_pct: float | None = None, max_pct: float | None = None) -> RecipeLine:
    return RecipeLine(
        component_product_id="flour",
        default_percentage=pct,
        min_percentage=min_pct if min_pct is not None else pct - 5,
        max_percentage=max_pct if max_pct is not None else pct + 5,
        is_hard_limit=is_hard_limit,
    )


def _recipe(status: str = "draft") -> Recipe:
    return Recipe(
        id="1",
        target_product_id="fusilli-500g",
        version=1,
        status=status,
        target_moisture_percentage=None,
        origin="manual",
        ai_confidence=None,
        previous_recipe_id=None,
        lines=(_line(100),),
    )


def test_composition_summing_to_100_is_valid():
    result = validate_composition((_line(60), _line(40)))
    assert isinstance(result, Ok)


def test_composition_not_summing_to_100_is_invalid():
    result = validate_composition((_line(60), _line(30)))
    assert isinstance(result, Err)
    assert result.code == "INVALID_TOTAL"


def test_empty_composition_is_invalid():
    result = validate_composition(())
    assert isinstance(result, Err)
    assert result.code == "EMPTY_RECIPE"


def test_hard_limit_violation_is_always_rejected():
    line = RecipeLine(
        component_product_id="salt", default_percentage=5, min_percentage=1, max_percentage=2, is_hard_limit=True
    )
    result = validate_composition((line, _line(95)))
    assert isinstance(result, Err)
    assert result.code == "HARD_LIMIT_VIOLATION"


def test_soft_limit_violation_is_a_warning_not_a_block():
    line = RecipeLine(
        component_product_id="salt", default_percentage=5, min_percentage=1, max_percentage=2, is_hard_limit=False
    )
    result = validate_composition((line, _line(95)))
    assert isinstance(result, Ok)
    assert len(result.value) == 1


def test_invalid_range_is_rejected():
    line = RecipeLine(component_product_id="x", default_percentage=50, min_percentage=60, max_percentage=40, is_hard_limit=False)
    result = validate_composition((line,))
    assert isinstance(result, Err)
    assert result.code == "INVALID_RANGE"


def test_draft_can_promote_to_trial():
    result = transition_recipe(_recipe(), "trial")
    assert isinstance(result, Ok)
    assert result.value.status == "trial"


def test_trial_can_be_rejected_to_draft():
    result = transition_recipe(_recipe("trial"), "draft")
    assert isinstance(result, Ok)
    assert result.value.status == "draft"


def test_trial_can_be_activated():
    result = transition_recipe(_recipe("trial"), "active")
    assert isinstance(result, Ok)
    assert result.value.status == "active"


def test_draft_cannot_activate_directly():
    result = transition_recipe(_recipe(), "active")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_archived_has_no_further_transitions():
    result = transition_recipe(_recipe("archived"), "draft")
    assert isinstance(result, Err)
