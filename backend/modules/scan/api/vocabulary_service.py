"""The names a fiche's codes are matched against, read from the modules that own them."""
from __future__ import annotations

import psycopg

from core.api.service import CoreService
from core.report_options import ReportOptionsService
from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.api.mold_service import MoldService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.waste_type_service import WasteTypeService
from modules.production.domain.production_report import DOWNTIME_MOTIFS_BY_REPORT_TYPE
from modules.scan.domain.text import team_letter
from modules.scan.domain.vocabulary import Term, Vocabulary

# The built-in waste kinds' French names, as the shift form shows them when the plant has
# not renamed one (frontend i18n production.waste.category.*).
_BUILTIN_WASTE_NAMES = {
    "raw_material": "Matière", "press": "Presse", "pouring": "Versement", "cross": "Cross",
    "kneading": "Pétrin", "product": "Produit", "packaging": "Emballage",
}
_FIXED = {
    "line_state": (Term("running", ("En marche", "Marche")), Term("stopped", ("En arrêt", "Arrêt", "Arrêté"))),
    "check_state": (
        Term("good", ("Bon", "B", "OK", "Conforme", "Oui")),
        Term("not_good", ("Non bon", "NB", "Non conforme", "NC", "Mauvais", "Non")),
    ),
}


def build_vocabulary(connection: psycopg.Connection, *, tenant_id: str, work_center_id: str | None) -> Vocabulary:
    products = CoreService(connection).list_products(tenant_id)
    classes = {c.product_id: c for c in ProductClassificationService(connection).list_classifications(tenant_id)}

    def products_where(test) -> tuple[Term, ...]:
        return tuple(
            Term(p.id, (p.name, p.sku), {"net_weight_grams": p.net_weight_grams})
            for p in products
            if (c := classes.get(p.id)) is not None and test(c)
        )

    waste = WasteTypeService(connection)
    builtins = waste.list_builtin_settings(tenant_id=tenant_id)
    customs = waste.list_types(tenant_id=tenant_id, include_inactive=False)

    def waste_terms(report_type: str) -> tuple[Term, ...]:
        # finished_product_conditioning is refused on the production side ("one place per loss").
        terms = [
            Term(b["category"], tuple(n for n in (b["name"], _BUILTIN_WASTE_NAMES.get(b["category"])) if n))
            for b in builtins
            if b["report_type"] == report_type and b["is_active"] and b["category"] != "finished_product_conditioning"
        ]
        terms += [Term(t["id"], (t["name"],)) for t in customs if t["report_type"] == report_type]
        return tuple(terms)

    equipment = EquipmentService(connection).list_equipment(tenant_id=tenant_id, work_center_id=work_center_id)
    molds = MoldService(connection).list_molds(tenant_id=tenant_id)
    teams = ReportOptionsService(connection).list_options(tenant_id=tenant_id, kind="team")
    return Vocabulary({
        "raw_material": products_where(lambda c: c.category == "raw_material" and not c.is_water and not c.is_energy),
        "regrind_item": products_where(lambda c: c.is_regrind),
        "finished_product": products_where(lambda c: c.category == "finished_good"),
        "film_item": products_where(lambda c: c.packaging_kind == "film"),
        "waste_production": waste_terms("daily"),
        "waste_packing": waste_terms("conditionnement"),
        "equipment": tuple(Term(e.id, (e.code, e.name)) for e in equipment),
        "mold": tuple(Term(m.id, (m.code, m.name)) for m in molds),
        "downtime_motif": tuple(Term(code, (code,)) for code in sorted(DOWNTIME_MOTIFS_BY_REPORT_TYPE["daily"])),
        "team": tuple(Term(o["label"], (o["label"],), {"letter": team_letter(o["label"])}) for o in teams),
        **_FIXED,
    })


def vocabulary_options(vocabulary: Vocabulary) -> dict[str, list[dict]]:
    """Every kind's values with a readable label, for the dictionary screen."""
    return {
        kind: [{"value": t.value, "label": next((n for n in t.names if n), t.value)} for t in terms]
        for kind, terms in vocabulary.terms.items()
    }
