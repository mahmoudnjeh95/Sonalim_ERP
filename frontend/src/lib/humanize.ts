/**
 * Turns a `snake_case` token into a readable phrase: "role_granted" -> "Role granted".
 * Only the first letter is capitalized -- these compose into longer phrases
 * (see `humanizeAuditAction`) where mid-sentence title-casing would look wrong.
 */
export function humanizeSnakeCase(value: string): string {
  const spaced = value.replace(/_/g, " ").trim();
  if (!spaced) return spaced;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * The audit log's `action` field is written everywhere in the codebase as
 * `{entity_type}.{verb_phrase}` (e.g. "production_report.corrected_after_validation",
 * "purchase_order_receipt.confirmed") -- see `record_audit(...)` call sites across
 * every module. That naming convention is consistent enough that splitting on the
 * first "." and turning both halves into words reads as a natural sentence for
 * virtually every action in the system, without hand-maintaining a translation per
 * action (there are ~100 and counting across modules).
 */
export function humanizeAuditAction(action: string): string {
  const separatorIndex = action.indexOf(".");
  if (separatorIndex === -1) return humanizeSnakeCase(action);
  const entity = action.slice(0, separatorIndex).replace(/_/g, " ");
  const verb = action.slice(separatorIndex + 1).replace(/_/g, " ");
  const phrase = `${entity} ${verb}`.trim();
  return phrase.charAt(0).toUpperCase() + phrase.slice(1);
}
