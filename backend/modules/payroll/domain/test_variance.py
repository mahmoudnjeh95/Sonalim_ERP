from decimal import Decimal

from modules.payroll.domain.variance import compare

D = Decimal


def row(employee_id, gross, net):
    return {"employee_id": employee_id, "employee_no": employee_id, "full_name": f"Name {employee_id}", "gross": D(gross), "net": D(net)}


CURRENT = [row("A", 100, 80), row("B", 200, 150), row("C", 50, 40)]
PREVIOUS = [row("B", 200, 150), row("C", 60, 45), row("D", 70, 60)]


def test_each_employee_is_new_left_changed_or_same():
    rows = {item.employee_id: item for item in compare(CURRENT, PREVIOUS)}
    assert {key: item.change for key, item in rows.items()} == {"A": "new", "B": "same", "C": "changed", "D": "left"}
    assert (rows["C"].delta_gross, rows["C"].delta_net) == (D(-10), D(-5))
    assert rows["D"].delta_net == D(-60) and rows["A"].previous_net is None


def test_rows_come_by_the_size_of_the_net_change():
    assert [item.employee_id for item in compare(CURRENT, PREVIOUS)] == ["A", "D", "C", "B"]
