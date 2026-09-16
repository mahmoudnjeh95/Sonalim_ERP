from core.domain.result import Err, Ok
from modules.qc.domain.non_conformity import (
    DispositionLine,
    NonConformity,
    transition_non_conformity,
    validate_disposition_lines,
    validate_non_conformity,
)


def _nc(status: str) -> NonConformity:
    return NonConformity(
        id="nc1",
        reference="NC-000001",
        of_id="of1",
        product_id="p1",
        quantity=10,
        source_location_id="loc1",
        defect_type="bad film seal",
        severity="major",
        status=status,
    )


def test_the_ticket_walks_raised_to_closed():
    assert isinstance(transition_non_conformity(_nc("raised"), "quarantined"), Ok)
    assert isinstance(transition_non_conformity(_nc("quarantined"), "dispositioned"), Ok)
    assert isinstance(transition_non_conformity(_nc("dispositioned"), "closed"), Ok)


def test_product_cannot_be_dispositioned_before_it_is_quarantined():
    """Quarantine is the step that stops rejected product being sold — not a formality."""
    result = transition_non_conformity(_nc("raised"), "dispositioned")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_a_closed_ticket_is_terminal():
    for target in ("raised", "quarantined", "dispositioned"):
        assert isinstance(transition_non_conformity(_nc("closed"), target), Err)


def test_a_valid_ticket_passes():
    result = validate_non_conformity(
        product_id="p1", quantity=10, source_location_id="loc1", defect_type="bad seal", severity="major"
    )
    assert isinstance(result, Ok)


def test_a_ticket_needs_a_positive_quantity_and_a_defect():
    assert validate_non_conformity(
        product_id="p1", quantity=0, source_location_id="loc1", defect_type="bad seal", severity="major"
    ).code == "INVALID_QUANTITY"
    assert validate_non_conformity(
        product_id="p1", quantity=10, source_location_id="loc1", defect_type="  ", severity="major"
    ).code == "MISSING_DEFECT_TYPE"
    assert validate_non_conformity(
        product_id="p1", quantity=10, source_location_id="", defect_type="bad seal", severity="major"
    ).code == "MISSING_LOCATION"
    assert validate_non_conformity(
        product_id="p1", quantity=10, source_location_id="loc1", defect_type="bad seal", severity="catastrophic"
    ).code == "INVALID_SEVERITY"


def test_the_worked_example_from_the_specification():
    """Ten packets fail: pasta to rebroyat, film and carton and tape to déchet."""
    lines = (
        DispositionLine(component="product", disposition="regrind", quantity=8),
        DispositionLine(component="film", disposition="dechet", quantity=0.4),
        DispositionLine(component="carton", disposition="dechet", quantity=1),
        DispositionLine(component="tape", disposition="dechet", quantity=0.1),
    )
    assert isinstance(validate_disposition_lines(lines), Ok)


def test_a_disposition_must_say_where_things_went():
    result = validate_disposition_lines(())
    assert isinstance(result, Err)
    assert result.code == "NO_DISPOSITION_LINES"


def test_packaging_cannot_be_reground():
    """Only the pasta goes back to rebroyat — film and carton are déchet."""
    for component in ("film", "carton", "tape"):
        result = validate_disposition_lines(
            (DispositionLine(component=component, disposition="regrind", quantity=1),)
        )
        assert isinstance(result, Err)
        assert result.code == "NOT_REGRINDABLE"


def test_the_same_component_cannot_be_sent_twice_to_the_same_place():
    result = validate_disposition_lines(
        (
            DispositionLine(component="film", disposition="dechet", quantity=1),
            DispositionLine(component="film", disposition="dechet", quantity=2),
        )
    )
    assert isinstance(result, Err)
    assert result.code == "DUPLICATE_LINE"


def test_a_component_may_be_split_across_destinations():
    # Half the pasta reground, half reworked, is legitimate.
    result = validate_disposition_lines(
        (
            DispositionLine(component="product", disposition="regrind", quantity=4),
            DispositionLine(component="product", disposition="rework", quantity=4),
        )
    )
    assert isinstance(result, Ok)


def test_every_line_needs_a_positive_quantity():
    result = validate_disposition_lines((DispositionLine(component="product", disposition="regrind", quantity=0),))
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_unknown_components_and_dispositions_are_rejected():
    assert validate_disposition_lines(
        (DispositionLine(component="pallet", disposition="dechet", quantity=1),)
    ).code == "INVALID_COMPONENT"
    assert validate_disposition_lines(
        (DispositionLine(component="product", disposition="incinerate", quantity=1),)
    ).code == "INVALID_DISPOSITION"
