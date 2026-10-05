from modules.scan.domain.vocabulary import Term, Vocabulary, resolve

VOCAB = Vocabulary({
    "waste_production": (Term("press", ("Presse",)), Term("kneading", ("Pétrin",)), Term("raw_material", ("Matière",))),
    "finished_product": (
        Term("P-VERM", ("Vermicelle 500g PC", "PF-VERM"), {"net_weight_grams": 500}),
        Term("P-VERM-PL", ("Vermicelle 500g PL", "PF-VERM-PL")),
    ),
    "line_state": (Term("running", ("En marche", "Marche")), Term("stopped", ("En arrêt", "Arrêt"))),
    "check_state": (Term("good", ("Bon", "Conforme")), Term("not_good", ("Non bon", "Non conforme"))),
})


def test_a_learned_alias_wins():
    found = resolve(VOCAB, {("raw_material", "bsk1"): "MP-1"}, "raw_material", " BSK1 ")
    assert (found.value, found.how, found.sure) == ("MP-1", "alias", True)


def test_exact_name_or_code():
    assert resolve(VOCAB, {}, "line_state", "En Marche").how == "exact"
    assert resolve(VOCAB, {}, "finished_product", "pf-verm").value == "P-VERM"


def test_contained_name_is_a_partial_match():
    found = resolve(VOCAB, {}, "waste_production", "Déchet Presse")
    assert (found.value, found.how, found.sure) == ("press", "contained", False)


def test_exact_beats_contained():
    assert resolve(VOCAB, {}, "check_state", "Non conforme").value == "not_good"


def test_several_matches_are_narrowed_by_the_preferred_value():
    found = resolve(VOCAB, {}, "finished_product", "Vermicelles", prefer="P-VERM")
    assert (found.value, found.how, found.sure) == ("P-VERM", "narrowed", True)


def test_several_matches_without_preference_are_ambiguous():
    found = resolve(VOCAB, {}, "finished_product", "Vermicelles")
    assert found.value is None and found.how == "ambiguous" and set(found.candidates) == {"P-VERM", "P-VERM-PL"}


def test_unknown_and_empty():
    assert resolve(VOCAB, {}, "waste_production", "Broyage").how == "none"
    assert resolve(VOCAB, {}, "waste_production", "  ").how == "empty"


def test_attr_and_label():
    assert VOCAB.attr("finished_product", "P-VERM", "net_weight_grams") == 500
    assert VOCAB.label("finished_product", "P-VERM") == "Vermicelle 500g PC"
