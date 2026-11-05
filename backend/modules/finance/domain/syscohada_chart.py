"""The SYSCOHADA revised chart (plan comptable OHADA 2017) as seed data.

The nine classes, the headings above the accounts, and the accounts this plant posts to.
Numbers and names are seed data from public references, to be checked by the client's
accountant (spec: "no invented numbers"); accounts can be added and renamed from the screen.
Default posting rules are all `to_confirm`.
"""
from __future__ import annotations

from modules.finance.domain.ledger import Account
from modules.finance.domain.posting import PostingRule

HEADING = False
POSTABLE = True


def _account(code: str, name: str, account_type: str, is_postable: bool, parent: str | None = None) -> Account:
    return Account(
        code=code, name=name, class_no=int(code[0]), account_type=account_type,
        is_postable=is_postable, parent_code=parent,
    )


CHART: tuple[Account, ...] = (
    _account("1", "Comptes de ressources durables", "equity", HEADING),
    _account("2", "Comptes d'actif immobilisé", "asset", HEADING),
    _account("3", "Comptes de stocks", "asset", HEADING),
    _account("4", "Comptes de tiers", "liability", HEADING),
    _account("5", "Comptes de trésorerie", "asset", HEADING),
    _account("6", "Comptes de charges des activités ordinaires", "expense", HEADING),
    _account("7", "Comptes de produits des activités ordinaires", "income", HEADING),
    _account("8", "Comptes des autres charges et des autres produits", "expense", HEADING),
    _account("9", "Comptes des engagements hors bilan et de la comptabilité analytique", "expense", HEADING),
    # Class 1
    _account("10", "Capital", "equity", HEADING, "1"),
    _account("101", "Capital social", "equity", POSTABLE, "10"),
    _account("11", "Réserves", "equity", HEADING, "1"),
    _account("111", "Réserve légale", "equity", POSTABLE, "11"),
    _account("12", "Report à nouveau", "equity", HEADING, "1"),
    _account("121", "Report à nouveau créditeur", "equity", POSTABLE, "12"),
    _account("129", "Report à nouveau débiteur", "equity", POSTABLE, "12"),
    _account("13", "Résultat net de l'exercice", "equity", HEADING, "1"),
    _account("131", "Résultat net : bénéfice", "equity", POSTABLE, "13"),
    _account("139", "Résultat net : perte", "equity", POSTABLE, "13"),
    _account("16", "Emprunts et dettes assimilées", "liability", HEADING, "1"),
    _account("162", "Emprunts et dettes auprès des établissements de crédit", "liability", POSTABLE, "16"),
    # Class 2
    _account("24", "Matériel, mobilier et actifs biologiques", "asset", HEADING, "2"),
    _account("241", "Matériel et outillage industriel et commercial", "asset", POSTABLE, "24"),
    _account("245", "Matériel de transport", "asset", POSTABLE, "24"),
    _account("28", "Amortissements", "asset", HEADING, "2"),
    _account("284", "Amortissements du matériel", "asset", POSTABLE, "28"),
    # Class 3
    _account("31", "Marchandises", "asset", HEADING, "3"),
    _account("311", "Marchandises A", "asset", POSTABLE, "31"),
    _account("32", "Matières premières et fournitures liées", "asset", HEADING, "3"),
    _account("321", "Matières premières", "asset", POSTABLE, "32"),
    _account("33", "Autres approvisionnements", "asset", HEADING, "3"),
    _account("335", "Emballages", "asset", POSTABLE, "33"),
    _account("36", "Produits finis", "asset", HEADING, "3"),
    _account("361", "Produits finis A", "asset", POSTABLE, "36"),
    # Class 4
    _account("40", "Fournisseurs et comptes rattachés", "liability", HEADING, "4"),
    _account("401", "Fournisseurs, dettes en compte", "liability", POSTABLE, "40"),
    _account("41", "Clients et comptes rattachés", "asset", HEADING, "4"),
    _account("411", "Clients", "asset", POSTABLE, "41"),
    _account("42", "Personnel", "liability", HEADING, "4"),
    _account("421", "Personnel, avances et acomptes", "asset", POSTABLE, "42"),
    _account("422", "Personnel, rémunérations dues", "liability", POSTABLE, "42"),
    _account("43", "Organismes sociaux", "liability", HEADING, "4"),
    _account("431", "Sécurité sociale", "liability", POSTABLE, "43"),
    _account("433", "Autres organismes sociaux", "liability", POSTABLE, "43"),
    _account("44", "État et collectivités publiques", "liability", HEADING, "4"),
    _account("441", "État, impôt sur les bénéfices", "liability", POSTABLE, "44"),
    _account("442", "État, autres impôts et taxes", "liability", POSTABLE, "44"),
    _account("443", "État, TVA facturée", "liability", POSTABLE, "44"),
    _account("444", "État, TVA due ou crédit de TVA", "liability", POSTABLE, "44"),
    _account("445", "État, TVA récupérable", "asset", POSTABLE, "44"),
    _account("446", "État, autres taxes sur le chiffre d'affaires", "liability", POSTABLE, "44"),
    _account("447", "État, impôts retenus à la source", "liability", POSTABLE, "44"),
    _account("47", "Débiteurs et créditeurs divers", "liability", HEADING, "4"),
    _account("471", "Débiteurs et créditeurs divers, comptes d'attente", "liability", POSTABLE, "47"),
    # Class 5
    _account("52", "Banques", "asset", HEADING, "5"),
    _account("521", "Banques locales", "asset", POSTABLE, "52"),
    _account("55", "Instruments de monnaie électronique", "asset", HEADING, "5"),
    _account("552", "Monnaie électronique, téléphone portable", "asset", POSTABLE, "55"),
    _account("57", "Caisse", "asset", HEADING, "5"),
    _account("571", "Caisse siège social", "asset", POSTABLE, "57"),
    _account("58", "Régies d'avances, accréditifs et virements internes", "asset", HEADING, "5"),
    _account("585", "Virements de fonds", "asset", POSTABLE, "58"),
    # Class 6
    _account("60", "Achats et variations de stocks", "expense", HEADING, "6"),
    _account("601", "Achats de marchandises", "expense", POSTABLE, "60"),
    _account("602", "Achats de matières premières et fournitures liées", "expense", POSTABLE, "60"),
    _account("608", "Achats d'emballages", "expense", POSTABLE, "60"),
    _account("64", "Impôts et taxes", "expense", HEADING, "6"),
    _account("641", "Impôts et taxes directs", "expense", POSTABLE, "64"),
    _account("66", "Charges de personnel", "expense", HEADING, "6"),
    _account("661", "Rémunérations directes versées au personnel national", "expense", POSTABLE, "66"),
    _account("663", "Indemnités forfaitaires versées au personnel", "expense", POSTABLE, "66"),
    _account("664", "Charges sociales", "expense", POSTABLE, "66"),
    # Class 7
    _account("70", "Ventes", "income", HEADING, "7"),
    _account("701", "Ventes de marchandises", "income", POSTABLE, "70"),
    _account("702", "Ventes de produits finis", "income", POSTABLE, "70"),
    _account("706", "Services vendus", "income", POSTABLE, "70"),
)

JOURNALS: tuple[tuple[str, str, str], ...] = (
    ("PAIE", "Journal de paie", "payroll"),
    ("VTE", "Journal des ventes", "sales"),
    ("ACH", "Journal des achats", "purchases"),
    ("BNQ", "Journal de banque", "bank"),
    ("CAI", "Journal de caisse", "cash"),
    ("OD", "Opérations diverses", "general"),
)


def _rule(source: str, kind: str, code: str, debit: str | None, credit: str | None, journal: str | None = None) -> PostingRule:
    return PostingRule(
        source=source, source_kind=kind, code=code,
        debit_account_code=debit, credit_account_code=credit, journal_code=journal,
    )


# Spec default mapping, to be confirmed by the accountant. Filled where the spec is silent:
# employer charges credit 442; mobile money pays out of 552. AMO contributions (Mali's payroll
# "AMO" code, both employee and employer) go to 433 "Autres organismes sociaux" rather than the
# generic 431 wildcard.
DEFAULT_POSTING_RULES: tuple[PostingRule, ...] = (
    _rule("payroll", "earning", "*", "661", None),
    _rule("payroll", "deduction", "*", None, "421"),
    _rule("payroll", "employee_contribution", "*", None, "431"),
    _rule("payroll", "employee_contribution", "AMO", None, "433"),
    _rule("payroll", "employer_contribution", "*", "664", "431"),
    _rule("payroll", "employer_contribution", "AMO", "664", "433"),
    _rule("payroll", "employer_charge", "*", "641", "442"),
    _rule("payroll", "tax", "*", None, "447"),
    _rule("payroll", "net", "*", None, "422"),
    _rule("payroll", "payment", "bank", "422", "521", "BNQ"),
    _rule("payroll", "payment", "mobile_money", "422", "552", "BNQ"),
    _rule("payroll", "payment", "cash", "422", "571", "CAI"),
    _rule("invoice", "issued", "*", "411", "702", "VTE"),
    _rule("invoice", "paid", "*", "521", "411", "BNQ"),
    _rule("purchase_invoice", "validated", "*", "601", "401", "ACH"),
)
