import type { RuleRowKind } from "../api";
import type { TranslationKey } from "../../../lib/i18n";

/**
 * How a rule-row column is typed in: `money` is whole F CFA, `percent` is 0–100, `json` is an
 * object typed as JSON text (tax relief parameters).
 */
export type RuleRowFieldKind = "text" | "number" | "money" | "percent" | "boolean" | "select" | "json";

export interface RuleRowField {
  /** The column name, exactly as rule_set_service.CHILD_KINDS lists it. */
  name: string;
  labelKey: TranslationKey;
  kind: RuleRowFieldKind;
  /** Closed values (rule_validation.py); each is labelled by `payroll.ruleRow.option.<value>`. */
  options?: readonly string[];
  /** The server refuses the row without it (rule_validation.py). */
  required?: boolean;
  hintKey?: TranslationKey;
}

// Closed lists mirrored from backend/modules/payroll/domain/rule_validation.py and rules.py.
const COMPONENT_KINDS = ["earning", "deduction", "employer_charge"] as const;
const FORMULA_TYPES = ["fixed", "rate_x_base", "qty_x_rate", "per_day"] as const;
const BASE_REFS = ["base_salary", "earned_base", "gross", "contributable"] as const;
const PAYSLIP_SECTIONS = ["earnings", "deductions", "employer"] as const;
const CONTRIBUTION_BASES = ["gross", "contributable"] as const;
const RELIEF_KINDS = ["family", "professional_expenses"] as const;
const OVERTIME_BANDS = ["day", "night", "rest_holiday"] as const;

// One entry per column of each rule table, in rule_set_service.CHILD_KINDS order.
export const RULE_ROW_FIELDS: Record<RuleRowKind, RuleRowField[]> = {
  components: [
    { name: "code", labelKey: "payroll.ruleRow.code", kind: "text", required: true },
    { name: "name_en", labelKey: "payroll.ruleRow.nameEn", kind: "text", required: true },
    { name: "name_fr", labelKey: "payroll.ruleRow.nameFr", kind: "text", required: true },
    { name: "kind", labelKey: "payroll.ruleRow.kind", kind: "select", options: COMPONENT_KINDS, required: true },
    { name: "taxable", labelKey: "payroll.ruleRow.taxable", kind: "boolean" },
    { name: "contributable", labelKey: "payroll.ruleRow.contributable", kind: "boolean" },
    { name: "formula_type", labelKey: "payroll.ruleRow.formulaType", kind: "select", options: FORMULA_TYPES, required: true },
    { name: "base_ref", labelKey: "payroll.ruleRow.baseRef", kind: "select", options: BASE_REFS, hintKey: "payroll.ruleRow.hint.baseRef" },
    { name: "default_amount", labelKey: "payroll.ruleRow.defaultAmount", kind: "money" },
    { name: "default_rate", labelKey: "payroll.ruleRow.defaultRate", kind: "percent" },
    { name: "display_order", labelKey: "payroll.ruleRow.displayOrder", kind: "number" },
    { name: "payslip_section", labelKey: "payroll.ruleRow.payslipSection", kind: "select", options: PAYSLIP_SECTIONS },
    { name: "declaration_code", labelKey: "payroll.ruleRow.declarationCode", kind: "text" },
  ],
  contributions: [
    { name: "code", labelKey: "payroll.ruleRow.code", kind: "text", required: true },
    { name: "name_en", labelKey: "payroll.ruleRow.nameEn", kind: "text", required: true },
    { name: "name_fr", labelKey: "payroll.ruleRow.nameFr", kind: "text", required: true },
    { name: "base", labelKey: "payroll.ruleRow.base", kind: "select", options: CONTRIBUTION_BASES, required: true },
    { name: "employee_rate", labelKey: "payroll.ruleRow.employeeRate", kind: "percent" },
    { name: "employer_rate", labelKey: "payroll.ruleRow.employerRate", kind: "percent" },
    { name: "ceiling_monthly", labelKey: "payroll.ruleRow.ceilingMonthly", kind: "money" },
    { name: "deductible_from_taxable", labelKey: "payroll.ruleRow.deductibleFromTaxable", kind: "boolean" },
    { name: "declaration_code", labelKey: "payroll.ruleRow.declarationCode", kind: "text", required: true },
    { name: "liability_account_code", labelKey: "payroll.ruleRow.liabilityAccountCode", kind: "text" },
    { name: "display_order", labelKey: "payroll.ruleRow.displayOrder", kind: "number" },
  ],
  tax_brackets: [
    { name: "tax_code", labelKey: "payroll.ruleRow.taxCode", kind: "text", required: true },
    { name: "lower_bound", labelKey: "payroll.ruleRow.lowerBound", kind: "money", required: true },
    { name: "upper_bound", labelKey: "payroll.ruleRow.upperBound", kind: "money", hintKey: "payroll.ruleRow.hint.upperBound" },
    { name: "rate", labelKey: "payroll.ruleRow.rate", kind: "percent", required: true },
    { name: "annualised", labelKey: "payroll.ruleRow.annualised", kind: "boolean" },
  ],
  tax_reliefs: [
    { name: "tax_code", labelKey: "payroll.ruleRow.taxCode", kind: "text", required: true },
    { name: "kind", labelKey: "payroll.ruleRow.kind", kind: "select", options: RELIEF_KINDS, required: true },
    { name: "parameters", labelKey: "payroll.ruleRow.parameters", kind: "json", required: true, hintKey: "payroll.ruleRow.hint.parameters" },
  ],
  seniority_scale: [
    { name: "years_from", labelKey: "payroll.ruleRow.yearsFrom", kind: "number", required: true },
    { name: "percent", labelKey: "payroll.ruleRow.percent", kind: "percent", required: true },
  ],
  overtime_rates: [
    { name: "band_code", labelKey: "payroll.ruleRow.bandCode", kind: "select", options: OVERTIME_BANDS, required: true },
    { name: "multiplier", labelKey: "payroll.ruleRow.multiplier", kind: "number", required: true },
  ],
  severance_scale: [
    { name: "years_from", labelKey: "payroll.ruleRow.yearsFrom", kind: "number", required: true },
    { name: "percent_per_year", labelKey: "payroll.ruleRow.percentPerYear", kind: "percent", required: true },
  ],
};

/** The i18n key naming one closed value of a select field. */
export function optionLabelKey(value: string): TranslationKey {
  return `payroll.ruleRow.option.${value}` as TranslationKey;
}

/** The i18n key naming a rule table (tab label, dialog title). */
export function kindLabelKey(kind: RuleRowKind): TranslationKey {
  return `payroll.rules.rows.${kind}` as TranslationKey;
}
