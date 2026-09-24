from modules.production.domain.packing_derivation import (
    packing_type_label,
    pick_packaging_location,
    resolve_packing_order,
)


def test_type_label_reads_the_format_and_the_weight():
    assert packing_type_label(packaging_format="packet", net_weight_grams=500) == "Sachet 500 g"
    assert packing_type_label(packaging_format="carton", net_weight_grams=4540.0) == "Carton 4540 g"
    assert packing_type_label(packaging_format="sac", net_weight_grams=0) == "Sac"
    assert packing_type_label(packaging_format=None, net_weight_grams=250.5) == "250.5 g"
    assert packing_type_label(packaging_format=None, net_weight_grams=None) is None


def test_one_shared_store_is_picked():
    assert pick_packaging_location(["store-a", "store-a", None]) == ("store-a", False)


def test_no_default_store_is_not_a_conflict():
    assert pick_packaging_location([None, None]) == (None, False)
    assert pick_packaging_location([]) == (None, False)


def test_different_stores_are_a_conflict():
    assert pick_packaging_location(["store-a", "store-b"]) == (None, True)


def test_a_named_run_decides_the_order():
    assert resolve_packing_order(given_of_id="of-x", run_of_id="of-run", shift_orders={"of-1": None}, product_id=None) == ("of-run", None)


def test_an_order_the_row_already_holds_is_kept():
    assert resolve_packing_order(given_of_id="of-x", run_of_id=None, shift_orders={"of-1": None, "of-2": None}, product_id=None) == ("of-x", None)


def test_the_only_order_of_the_shift_is_the_one():
    assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders={"of-1": None}, product_id="p") == ("of-1", None)


def test_several_orders_are_told_apart_by_the_rows_product():
    orders = {"of-1": "p1", "of-2": "p2"}
    assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders=orders, product_id="p2") == ("of-2", None)


def test_several_orders_with_no_product_match_are_ambiguous():
    orders = {"of-1": "p1", "of-2": "p2"}
    for product in (None, "p3"):
        assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders=orders, product_id=product) == (None, "OF_AMBIGUOUS")


def test_several_orders_of_the_same_product_are_ambiguous():
    orders = {"of-1": "p1", "of-2": "p1"}
    assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders=orders, product_id="p1") == (None, "OF_AMBIGUOUS")


def test_a_shift_with_no_production_cannot_place_the_row():
    assert resolve_packing_order(given_of_id=None, run_of_id=None, shift_orders={}, product_id="p") == (None, "PRODUCTION_FIRST")
