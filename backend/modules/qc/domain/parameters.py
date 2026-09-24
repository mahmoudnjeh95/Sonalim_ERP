from __future__ import annotations

from core.domain.result import Err, Ok, Result

# The nine groups of the "Contrôle des paramètres" paper sheet, each a
# repeatable rows list: entry_label is the row's own key (a free time for
# most groups, a machine/press number for presse and compresseurs, PL/PC for
# additif) and fields holds that group's own readings. Field lists come
# from the photographed sheet (2026-09-24 spec, section 1.4) -- confirm
# wording/units with the client if a reading looks misread.
PARAMETER_GROUPS: dict[str, tuple[str, ...]] = {
    "presse": ("pression", "debit_bar", "niveau_moulange_percent"),
    "pompe_vide": ("niveau_huile", "temperature_c", "niveau_vide_bar"),
    "sechage": ("temperature_c", "delta"),
    "chaudiere": (
        "t_aller_c", "p_aller_bar", "t_retour_c", "p_retour_bar", "t_digit_c",
        "signal_a_elec", "niveau_bac_exp", "niveau_bac_alim", "compteur_cuve1", "compteur_cuve2",
    ),
    "compresseurs": ("pression_bar", "temperature_c"),
    "traitement_eau": (
        "niveau_cuve1", "niveau_cuve2", "niveau_sel", "niveau_bicore", "niveau_bache", "niveau_chateau",
    ),
    "chiller": (
        "t_entree_c", "t_sortie_c", "p_entree_bar", "p_sortie_bar",
        "t_digit_entree_c", "t_digit_sortie_c", "proprete_radiateur", "observation",
    ),
    "additif": ("tableau", "niveau_tremie", "observation"),
    "proprete_locaux": (
        "lave_m", "chaud", "tri_eau", "compr", "b_eau", "presse", "pres_en_h", "sech_en_h", "silo",
    ),
}

# Fields that are always a percentage, wherever their group declares them.
_PERCENTAGE_FIELDS = {"niveau_moulange_percent"}


def validate_parameter_entry(group_key: str, fields: dict) -> Result[None]:
    """Refuse a group nobody declared, a field that group doesn't have, or an
    impossible reading -- same "refuse impossible, not disappointing" stance
    as the rest of qc's validation. An empty `fields` dict is always valid:
    a row may be saved with only its entry_label typed so far.
    """
    declared = PARAMETER_GROUPS.get(group_key)
    if declared is None:
        return Err("INVALID_GROUP", f"group must be one of {sorted(PARAMETER_GROUPS)}")

    for key, value in fields.items():
        if key not in declared:
            return Err("INVALID_FIELD", f"{key} is not a field of group {group_key}")
        if key in _PERCENTAGE_FIELDS and value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return Err("INVALID_NUMBER", f"{key} must be a number")
            if not 0 <= value <= 100:
                return Err("INVALID_PERCENTAGE", f"{key} must be between 0 and 100")
    return Ok(None)
