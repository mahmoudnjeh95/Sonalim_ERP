import pytest

from modules.production.domain.shift_report import (
    SECTION_KEYS,
    can_declare_nothing,
    can_submit,
    derive_shift_status,
    permission_for_section,
    status_after_save,
)


def test_section_keys_follow_the_paper_order():
    assert SECTION_KEYS == (
        "runs", "waste_production", "stops", "silo", "staffing",
        "packing", "packet_checks", "waste_packing", "energy",
    )


def test_each_section_has_its_own_edit_permission():
    assert permission_for_section("packing") == "production.shift.edit.packing"
    assert len({permission_for_section(k) for k in SECTION_KEYS}) == len(SECTION_KEYS)


def test_an_unknown_section_has_no_permission():
    with pytest.raises(ValueError):
        permission_for_section("reels_not_yet")


@pytest.mark.parametrize(
    "before, after, is_edit_after_submit",
    [
        ("empty", "draft", False),
        ("draft", "draft", False),
        ("returned", "draft", False),
        ("nothing_to_report", "draft", False),
        ("submitted", "submitted", True),
    ],
)
def test_saving_a_section(before, after, is_edit_after_submit):
    assert status_after_save(before) == (after, is_edit_after_submit)


@pytest.mark.parametrize(
    "status, expected",
    [("empty", False), ("draft", True), ("returned", True), ("submitted", False), ("nothing_to_report", False)],
)
def test_only_a_draft_or_returned_section_can_be_submitted(status, expected):
    assert can_submit(status) is expected


@pytest.mark.parametrize("status", ["empty", "draft", "returned", "submitted", "nothing_to_report"])
def test_nothing_to_report_can_be_declared_from_any_state(status):
    assert can_declare_nothing(status) is True


def test_a_shift_is_submitted_when_every_section_is_in():
    assert derive_shift_status("open", ["submitted", "nothing_to_report", "submitted"]) == "submitted"


def test_a_shift_stays_open_while_a_section_is_missing_or_drafted():
    assert derive_shift_status("open", ["submitted", "draft"]) == "open"
    assert derive_shift_status("open", ["submitted", "empty"]) == "open"


def test_a_returned_section_returns_the_shift():
    assert derive_shift_status("submitted", ["submitted", "returned"]) == "returned"


def test_a_returned_shift_goes_back_once_the_section_is_resubmitted():
    assert derive_shift_status("returned", ["submitted", "submitted"]) == "submitted"


def test_editing_after_submission_leaves_the_shift_submitted():
    # Edit-after-submit keeps the section submitted, so the shift does not reopen.
    assert derive_shift_status("submitted", ["submitted", "submitted"]) == "submitted"


def test_a_validated_shift_never_changes():
    assert derive_shift_status("validated", ["draft", "empty"]) == "validated"


# ---- energy split ----------------------------------------------------------

from modules.production.domain.shift_report import split_proportionally  # noqa: E402


def test_the_split_follows_the_weights():
    assert split_proportionally(1000, [260, 160]) == [619.047619, 380.952381]


def test_the_last_share_takes_the_remainder_so_the_sum_is_exact():
    shares = split_proportionally(100, [1, 1, 1])
    assert sum(shares) == pytest.approx(100, abs=1e-9)
    assert shares[:2] == [33.333333, 33.333333]
    assert shares[2] == pytest.approx(33.333334, abs=1e-9)


def test_a_single_run_gets_everything():
    assert split_proportionally(600, [420]) == [600]


def test_with_no_weights_at_all_the_first_takes_everything():
    assert split_proportionally(600, [0, 0]) == [600, 0]


def test_nothing_to_split_between_is_empty():
    assert split_proportionally(600, []) == []


def test_a_zero_total_splits_into_zeros():
    assert split_proportionally(0, [10, 20]) == [0, 0]
