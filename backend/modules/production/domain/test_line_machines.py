from modules.production.domain.line_machines import pick_stage_machine, silo_machine_changes

MACHINES = [
    ("p1", "versement", "operational"),
    ("p2", "extrusion", "operational"),
    ("p3", "conditionnement", "down"),
    ("p4", None, "operational"),
]


def test_a_stage_with_exactly_one_machine_names_it():
    assert pick_stage_machine(MACHINES, "extrusion") == "p2"


def test_a_stage_with_none_or_several_machines_names_nothing():
    assert pick_stage_machine(MACHINES, "missing") is None
    assert pick_stage_machine([*MACHINES, ("p5", "extrusion", "operational")], "extrusion") is None


def test_a_stopped_production_side_takes_versement_and_extrusion_down():
    assert silo_machine_changes(side="production", line_state="stopped", machines=MACHINES) == [
        ("p1", "down"),
        ("p2", "down"),
    ]


def test_a_running_packing_side_brings_conditionnement_back():
    assert silo_machine_changes(side="packing", line_state="running", machines=MACHINES) == [("p3", "operational")]


def test_maintenance_and_machines_already_there_are_left_alone():
    machines = [("a", "extrusion", "maintenance"), ("b", "versement", "down")]
    assert silo_machine_changes(side="production", line_state="stopped", machines=machines) == []


def test_an_unknown_or_missing_state_changes_nothing():
    assert silo_machine_changes(side="production", line_state=None, machines=MACHINES) == []
    assert silo_machine_changes(side="production", line_state="En marche", machines=MACHINES) == []
