from modules.warehouse.domain.putaway import rank_candidates


def test_a_rule_ranks_above_everything_else():
    result = rank_candidates(
        rule_location_id="bin-rule",
        same_product_location_ids=["bin-same"],
        empty_bin_ids=["bin-empty"],
        exclude_location_id=None,
    )
    assert result == ["bin-rule", "bin-same", "bin-empty"]


def test_same_product_ranks_above_empty_bins_with_no_rule():
    result = rank_candidates(
        rule_location_id=None,
        same_product_location_ids=["bin-same"],
        empty_bin_ids=["bin-empty"],
        exclude_location_id=None,
    )
    assert result == ["bin-same", "bin-empty"]


def test_duplicates_across_signals_are_kept_once_at_their_highest_rank():
    result = rank_candidates(
        rule_location_id="bin-a",
        same_product_location_ids=["bin-a", "bin-b"],
        empty_bin_ids=["bin-b"],
        exclude_location_id=None,
    )
    assert result == ["bin-a", "bin-b"]


def test_the_current_location_is_never_suggested():
    result = rank_candidates(
        rule_location_id="bin-current",
        same_product_location_ids=["bin-current", "bin-other"],
        empty_bin_ids=["bin-current"],
        exclude_location_id="bin-current",
    )
    assert result == ["bin-other"]


def test_no_signals_at_all_gives_no_suggestions():
    assert rank_candidates(rule_location_id=None, same_product_location_ids=[], empty_bin_ids=[], exclude_location_id=None) == []
