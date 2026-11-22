from decimal import Decimal

from core.domain.result import Err, Ok
from core.domain.tax import (
    BreakdownPart,
    ResolvedTax,
    TaxCode,
    allocate_breakdown,
    check_tax_code,
    parse_breakdown,
    resolve_line_tax,
    split_whole,
    vat_breakdown,
)

D = Decimal
CODES = [
    TaxCode("t18", "TVA18", D("18")),
    TaxCode("exo", "EXO", D("0"), exempt=True),
    TaxCode("t5", "TVA5", D("5"), scope="sales"),
    TaxCode("old", "OLD10", D("10"), active=False),
]


def test_explicit_code_gives_its_rate():
    assert resolve_line_tax(side="sales", codes=CODES, explicit_code="tva5") == Ok(ResolvedTax("TVA5", D("5")))


def test_explicit_code_with_a_different_rate_is_refused():
    result = resolve_line_tax(side="sales", codes=CODES, explicit_code="TVA18", explicit_rate=5)
    assert isinstance(result, Err) and result.code == "TAX_RATE_MISMATCH"


def test_explicit_code_unknown_inactive_or_wrong_side_is_refused():
    assert resolve_line_tax(side="sales", codes=CODES, explicit_code="NOPE").code == "TAX_CODE_NOT_FOUND"
    assert resolve_line_tax(side="sales", codes=CODES, explicit_code="OLD10").code == "TAX_CODE_INACTIVE"
    assert resolve_line_tax(side="purchases", codes=CODES, explicit_code="TVA5").code == "TAX_CODE_WRONG_SCOPE"


def test_explicit_rate_keeps_the_rate_and_finds_its_code():
    result = resolve_line_tax(side="sales", codes=CODES, explicit_rate=D("18"))
    assert (result.value.tax_code, result.value.rate) == ("TVA18", D("18"))
    # no active code at 10 %: the rate stays, without a code
    result = resolve_line_tax(side="sales", codes=CODES, explicit_rate=10)
    assert (result.value.tax_code, result.value.rate) == (None, D("10"))
    # a 0 % rate is not an exemption unless the partner or product says so
    assert resolve_line_tax(side="sales", codes=CODES, explicit_rate=0).value.tax_code is None
    assert resolve_line_tax(side="sales", codes=CODES, explicit_rate=0, partner_code_id="exo").value.tax_code == "EXO"


def test_partner_code_beats_product_code_and_default():
    result = resolve_line_tax(side="sales", codes=CODES, partner_code_id="exo", product_code_id="t5", default_rate=D("18"))
    assert (result.value.tax_code, result.value.rate) == ("EXO", D("0"))
    result = resolve_line_tax(side="sales", codes=CODES, product_code_id="t5", default_rate=D("18"))
    assert (result.value.tax_code, result.value.rate) == ("TVA5", D("5"))


def test_product_code_for_the_other_side_is_ignored():
    result = resolve_line_tax(side="purchases", codes=CODES, product_code_id="t5", default_rate=D("18"))
    assert (result.value.tax_code, result.value.rate) == ("TVA18", D("18"))


def test_no_codes_at_all_is_the_old_behaviour():
    result = resolve_line_tax(side="sales", codes=[], default_rate=D("18"))
    assert (result.value.tax_code, result.value.rate) == (None, D("18"))
    result = resolve_line_tax(side="sales", codes=[], explicit_rate=D("7.5"))
    assert (result.value.tax_code, result.value.rate) == (None, D("7.5"))


def test_check_tax_code():
    assert check_tax_code(code="TVA18", name_fr="TVA", rate="18", scope="both", exempt=False) == Ok(D("18"))
    assert check_tax_code(code="EXO", name_fr="Exo", rate="5", scope="both", exempt=True).code == "INVALID_TAX_CODE"
    assert check_tax_code(code="A B", name_fr="x", rate="5", scope="both", exempt=False).code == "INVALID_TAX_CODE"
    assert check_tax_code(code="X", name_fr="x", rate="101", scope="both", exempt=False).code == "INVALID_VAT_RATE"
    assert check_tax_code(code="X", name_fr="x", rate="5", scope="all", exempt=False).code == "INVALID_TAX_CODE"


def test_breakdown_groups_by_code_and_rate():
    parts = vat_breakdown([("TVA18", "18", "1000"), ("EXO", "0", "500"), ("TVA18", "18", "333.335"), (None, "18", "10")])
    assert parts == [
        BreakdownPart(None, D("18"), D("10.00"), D("1.80")),
        BreakdownPart("EXO", D("0"), D("500.00"), D("0.00")),
        BreakdownPart("TVA18", D("18"), D("1333.34"), D("240.00")),
    ]


def test_split_whole_sums_exactly_and_puts_the_gap_on_the_largest():
    assert split_whole(D("100"), [D("1"), D("1"), D("2")]) == [D("25"), D("25"), D("50")]
    assert split_whole(D("100"), [D("1"), D("1"), D("1")]) == [D("34"), D("33"), D("33")]
    parts = split_whole(D("181"), [D("90.5"), D("90.5")])
    assert sum(parts) == D("181")
    assert split_whole(D("5"), [D("0"), D("0")]) == [D("5"), D("0")]


def test_allocate_breakdown_matches_the_document_totals():
    parts = [BreakdownPart("TVA18", D("18"), D("1000.40"), D("180.07")), BreakdownPart("TVA5", D("5"), D("200.30"), D("10.02"))]
    allocated = allocate_breakdown(parts, base_total=D("1201"), vat_total=D("190"))
    assert sum(p.base for p in allocated) == D("1201")
    assert sum(p.vat for p in allocated) == D("190")
    assert [p.tax_code for p in allocated] == ["TVA18", "TVA5"]


def test_parse_breakdown_ignores_garbage():
    assert parse_breakdown(None) == []
    assert parse_breakdown([{"rate": "x"}]) == []
    assert parse_breakdown([{"tax_code": "EXO", "rate": "0", "base": "10", "vat": "0"}]) == [BreakdownPart("EXO", D("0"), D("10"), D("0"))]
