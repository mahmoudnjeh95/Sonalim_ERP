from modules.production.domain.packing_derivation import packing_type_label, pick_packaging_location


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
