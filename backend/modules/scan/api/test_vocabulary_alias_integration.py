import pytest

from core.domain.result import Err
from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.scan_world import make_world, ok
from modules.scan.api.vocabulary_service import build_vocabulary, vocabulary_options

TENANT = "scan-vocabulary-test"


@pytest.fixture
def world(db):
    return make_world(db, TENANT)


def test_vocabulary_is_built_from_the_plants_data(db, world):
    vocabulary = build_vocabulary(db, tenant_id=TENANT, work_center_id=world["work_center"])
    assert [t.value for t in vocabulary.of("raw_material")] == [world["semoule"]]
    assert vocabulary.attr("finished_product", world["pasta"], "net_weight_grams") == 500
    assert [t.value for t in vocabulary.of("film_item")] == [world["film"]]
    assert "press" in {t.value for t in vocabulary.of("waste_production")}
    assert "finished_product_conditioning" not in {t.value for t in vocabulary.of("waste_production")}
    assert {t.value for t in vocabulary.of("line_state")} == {"running", "stopped"}
    options = vocabulary_options(vocabulary)
    assert {"value": world["semoule"], "label": "Semoule SSSE"} in options["raw_material"]


def test_learning_an_alias_and_using_it(db, world):
    aliases = ScanAliasService(db)
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="raw_material", read_text=" BSK1 ", target_value=world["semoule"])
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="raw_material", read_text="bsk1", target_value=world["semoule"])
    assert aliases.alias_map(tenant_id=TENANT) == {("raw_material", "bsk1"): world["semoule"]}
    [row] = aliases.list_aliases(tenant_id=TENANT)
    assert (row["kind"], row["raw_text_example"], row["use_count"]) == ("raw_material", "bsk1", 2)
    audits = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'scan_alias.learned'", (TENANT,)
    ).fetchone()[0]
    assert audits == 2


def test_a_learned_alias_ignores_unknown_kinds_and_blank_text(db, world):
    aliases = ScanAliasService(db)
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="nonsense", read_text="x", target_value="y")
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="raw_material", read_text=" - ", target_value="y")
    assert aliases.list_aliases(tenant_id=TENANT) == []


def test_editing_and_deleting_an_alias(db, world):
    aliases = ScanAliasService(db)
    aliases.learn(tenant_id=TENANT, actor_id=world["actor"], kind="equipment", read_text="C2", target_value="E1")
    [row] = aliases.list_aliases(tenant_id=TENANT, kind="equipment")
    updated = ok(aliases.update_alias(tenant_id=TENANT, actor_id=world["actor"], alias_id=row["id"], target_value="E2"))
    assert updated["target_value"] == "E2"
    assert isinstance(aliases.update_alias(tenant_id=TENANT, actor_id=world["actor"], alias_id=row["id"], target_value=" "), Err)
    ok(aliases.delete_alias(tenant_id=TENANT, actor_id=world["actor"], alias_id=row["id"]))
    assert aliases.list_aliases(tenant_id=TENANT) == []
    assert aliases.delete_alias(tenant_id=TENANT, actor_id=world["actor"], alias_id=row["id"]).code == "NOT_FOUND"
