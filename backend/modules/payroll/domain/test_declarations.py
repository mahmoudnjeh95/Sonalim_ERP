from datetime import date
from decimal import Decimal

from modules.payroll.domain.declarations import annual_recap, available_codes, build_declaration, to_csv

D = Decimal


def line(section, code, amount, base=None, declaration=None):
    return {"section": section, "code": code, "amount": D(amount), "base": None if base is None else D(base), "declaration_code": declaration}


def payslip(employee_id, *, lines, gross=0, period=date(2026, 9, 1), identifiers=None, net=0, its=0, employee_contrib=0, employer_contrib=0):
    return {"employee_id": employee_id, "employee_no": f"M-{employee_id}", "full_name": f"Name {employee_id}",
            "identifiers": identifiers or {}, "period": period, "gross": D(gross), "net": D(net), "its": D(its),
            "employee_contrib": D(employee_contrib), "employer_contrib": D(employer_contrib), "lines": lines}


A = payslip("1", gross=300000, identifiers={"inps_no": "INPS-1"}, lines=[
    line("employee_contribution", "PENSION", 10800, 300000, "INPS"),
    line("employer_contribution", "PENSION", 16200, 300000, "INPS"),
    line("employer_contribution", "FAMILY", 24000, 300000, "INPS"),
    line("employee_contribution", "AMO", 9180, 300000, "AMO"),
    line("tax", "ITS", 12000, 250000),
    line("employer_charge", "TL", 3000, 300000, "TL"),
])
B_REGULAR = payslip("2", gross=200000, lines=[
    line("employee_contribution", "PENSION", 7200, 200000, "INPS"),
    line("employer_contribution", "PENSION", 10800, 200000, "INPS"),
    line("tax", "ITS", 5000, 150000),
])
B_OFF_CYCLE = payslip("2", gross=50000, lines=[
    line("employee_contribution", "PENSION", 1800, 50000, "INPS"),
    line("employer_contribution", "PENSION", 2700, 50000, "INPS"),
])


def test_codes_come_from_the_lines():
    assert available_codes([A, B_REGULAR]) == ["AMO", "EMPLOYER_TAXES", "INPS", "ITS"]


def test_a_contribution_declaration_adds_up_each_employee_across_payslips():
    declaration = build_declaration("INPS", [A, B_REGULAR, B_OFF_CYCLE])
    assert declaration.columns == ("employee_no", "full_name", "identifier", "base", "FAMILY_employee", "PENSION_employee",
                                   "FAMILY_employer", "PENSION_employer", "total")
    first, second = declaration.rows
    assert (first["identifier"], first["base"], first["PENSION_employee"], first["FAMILY_employer"], first["total"]) == (
        "INPS-1", D(300000), D(10800), D(24000), D(51000))
    assert (second["base"], second["PENSION_employee"], second["total"]) == (D(250000), D(9000), D(22500))
    assert declaration.totals["total"] == D(73500)


def test_the_tax_declaration_lists_taxable_and_tax():
    declaration = build_declaration("ITS", [A, B_REGULAR])
    assert [(row["employee_no"], row["taxable"], row["amount"]) for row in declaration.rows] == [
        ("M-1", D(250000), D(12000)), ("M-2", D(150000), D(5000))]


def test_employer_taxes_group_every_employer_charge():
    declaration = build_declaration("EMPLOYER_TAXES", [A, B_REGULAR])
    assert declaration.columns == ("employee_no", "full_name", "gross", "TL", "total")
    assert [(row["employee_no"], row["TL"]) for row in declaration.rows] == [("M-1", D(3000))]


def test_an_unknown_code_gives_nothing():
    assert build_declaration("CNSS", [A]) is None


def test_the_csv_ends_with_a_total_row():
    assert to_csv(build_declaration("ITS", [A, B_REGULAR])).splitlines() == [
        "employee_no;full_name;taxable;amount", "M-1;Name 1;250000;12000", "M-2;Name 2;150000;5000", "TOTAL;;400000;17000"]


def test_the_annual_recap_counts_months_and_adds_amounts():
    january = payslip("1", gross=300000, period=date(2026, 1, 1), lines=[], net=250000, its=12000)
    february = payslip("1", gross=310000, period=date(2026, 2, 1), lines=[], net=255000, its=13000)
    recap = annual_recap([january, february])
    assert (recap.rows[0]["months"], recap.rows[0]["gross"], recap.rows[0]["its"], recap.rows[0]["net"]) == (
        2, D(610000), D(25000), D(505000))
