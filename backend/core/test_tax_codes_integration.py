"""Tax-code catalogue: defaults, one default per side, and the modules' default VAT rate following it."""
from __future__ import annotations

from decimal import Decimal

from core.domain.result import Err, Ok
from core.tax_codes import TaxCodeService
from modules.procurement.api.invoice_service import PurchaseInvoiceService
from modules.sales.api.pricing_service import PricingService

D = Decimal
ACTOR = "actor-tax"


def test_catalogue_starts_with_defaults(db):
    service = TaxCodeService(db)
    codes = service.list_codes(tenant_id="tax-t1")
    assert [c["code"] for c in codes] == ["TVA18", "EXO"]
    assert service.default_rate(tenant_id="tax-t1", side="sales") == D("18.00")
    assert service.default_rate(tenant_id="tax-t1", side="purchase") == D("18.00")
    assert next(c for c in codes if c["code"] == "EXO")["exempt"] is True


def test_create_validates_and_refuses_duplicates(db):
    service = TaxCodeService(db)
    ok = service.create_code(tenant_id="tax-t2", actor_id=ACTOR, code="tva10", name_fr="TVA 10 %", rate=10, applies_to="sales")
    assert isinstance(ok, Ok) and ok.value["code"] == "TVA10"
    assert service.create_code(tenant_id="tax-t2", actor_id=ACTOR, code="TVA10", name_fr="x", rate=10).code == "TAX_CODE_EXISTS"
    assert service.create_code(tenant_id="tax-t2", actor_id=ACTOR, code="BAD", name_fr="x", rate=120).code == "INVALID_TAX_RATE"
    assert [c["code"] for c in service.list_codes(tenant_id="tax-t2", side="purchase")] == ["TVA18", "EXO"]


def test_one_default_per_side_and_guards(db):
    service = TaxCodeService(db)
    new = service.create_code(tenant_id="tax-t3", actor_id=ACTOR, code="TVA5", name_fr="TVA 5 %", rate=5, applies_to="sales").value
    assert service.set_default(tenant_id="tax-t3", actor_id=ACTOR, code_id=new["id"], side="purchase").code == "INVALID_TAX_CODE"
    assert isinstance(service.set_default(tenant_id="tax-t3", actor_id=ACTOR, code_id=new["id"], side="sales"), Ok)
    assert service.default_rate(tenant_id="tax-t3", side="sales") == D("5.00")
    assert service.default_rate(tenant_id="tax-t3", side="purchase") == D("18.00")
    assert sum(c["is_default_sales"] for c in service.list_codes(tenant_id="tax-t3")) == 1
    # the default cannot be deactivated or moved off its side
    assert service.update_code(tenant_id="tax-t3", actor_id=ACTOR, code_id=new["id"], active=False).code == "TAX_CODE_IS_DEFAULT"
    assert service.update_code(tenant_id="tax-t3", actor_id=ACTOR, code_id=new["id"], applies_to="purchase").code == "TAX_CODE_IS_DEFAULT"
    other = next(c for c in service.list_codes(tenant_id="tax-t3") if c["code"] == "EXO")
    assert isinstance(service.update_code(tenant_id="tax-t3", actor_id=ACTOR, code_id=other["id"], active=False), Ok)
    assert [c["code"] for c in service.list_codes(tenant_id="tax-t3")] == ["TVA18", "TVA5"]


def test_catalogues_are_per_tenant(db):
    service = TaxCodeService(db)
    service.create_code(tenant_id="tax-t4a", actor_id=ACTOR, code="ONLY", name_fr="x", rate=1)
    assert "ONLY" not in [c["code"] for c in service.list_codes(tenant_id="tax-t4b")]


def test_sales_default_vat_follows_the_catalogue(db):
    pricing = PricingService(db)
    assert pricing.get_settings(tenant_id="tax-t5")["default_vat_rate"] == D("18.00")
    assert isinstance(pricing.update_settings(tenant_id="tax-t5", actor_id=ACTOR, default_vat_rate=D("10")), Ok)
    assert pricing.get_settings(tenant_id="tax-t5")["default_vat_rate"] == D("10.00")
    assert TaxCodeService(db).default_rate(tenant_id="tax-t5", side="sales") == D("10.00")
    assert TaxCodeService(db).default_rate(tenant_id="tax-t5", side="purchase") == D("18.00")


def test_purchase_default_vat_follows_the_catalogue(db):
    service = PurchaseInvoiceService(db)
    assert service.default_vat_rate(tenant_id="tax-t6") == D("18.00")
    assert isinstance(service.set_default_vat_rate(tenant_id="tax-t6", actor_id=ACTOR, rate=D("0")), Ok)
    assert service.default_vat_rate(tenant_id="tax-t6") == D("0.00")
    assert TaxCodeService(db).default_rate(tenant_id="tax-t6", side="sales") == D("18.00")


def test_a_rate_stored_before_codes_existed_is_kept(db):
    db.execute("INSERT INTO sales.settings (tenant_id, default_vat_rate) VALUES ('tax-t7', 7.5)")
    assert PricingService(db).get_settings(tenant_id="tax-t7")["default_vat_rate"] == D("7.50")
    codes = {c["code"]: c for c in TaxCodeService(db).list_codes(tenant_id="tax-t7")}
    assert codes["TVA7.5"]["is_default_sales"] and codes["TVA18"]["is_default_purchase"]
