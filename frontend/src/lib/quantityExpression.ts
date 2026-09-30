/**
 * What a person typed into a quantity box, as a number: either a plain number or a
 * sum such as `15.67+15.27+15.9-2.8` -- the weights of the film rolls used, less what
 * is left on the last one. That is how the plant's Excel took the figure (a formula
 * typed into the cell), and typing it here spares the operator a calculator and a
 * transcription error.
 *
 * Only `+` and `-` between decimal numbers are understood; nothing else is
 * evaluated, so the box can never run anything. A comma is read as the decimal
 * point, as a French keyboard types it. Returns null for anything else, including an
 * empty box or a sum left half-typed (`15.67+`), so the caller can refuse it instead
 * of saving a figure the person did not mean.
 */
export function evaluateQuantity(text: string): number | null {
  // A typographic minus is what most keyboards and word processors put in.
  const compact = text.replace(/[−–]/g, "-").replace(/\s+/g, "");
  if (!compact || !/^[+-]?(\d+([.,]\d+)?|[.,]\d+)([+-](\d+([.,]\d+)?|[.,]\d+))*$/.test(compact)) return null;

  let total = 0;
  for (const [, sign, digits] of compact.matchAll(/([+-]?)(\d+(?:[.,]\d+)?|[.,]\d+)/g)) {
    const amount = Number(digits.replace(",", "."));
    total += sign === "-" ? -amount : amount;
  }
  // 15.67 + 15.27 - 2.8 is 28.139999999999997 in floating point; a quantity is
  // never read to more than a gram, so six decimals is far past anything typed.
  return Math.round(total * 1e6) / 1e6;
}

/** True when the text is a calculation rather than a single number -- what the box shows a result for. */
export function isSum(text: string): boolean {
  return /\d\s*[+\-−–]\s*[\d.,]/.test(text);
}

/**
 * Whether a quantity box should be rewritten to show `value`, when the box currently
 * says `text`.
 *
 * The box follows the form -- a draft loading in, a reset -- but must not rewrite what
 * somebody is in the middle of typing. `100,5` and `100.5` are the same figure, so
 * replacing the first with the second only moves the caret and eats the comma a French
 * keyboard just typed; that is what made `100,5 kg` of film impossible to enter. A text
 * that is not yet a figure (`100,`) is mid-typing too, and an emptied box is a 0 the
 * person means, not a 0 to write back.
 */
export function shouldSyncText(text: string, value: number): boolean {
  if (!Number.isFinite(value)) return false;
  const typed = text.trim();
  // An emptied box already reads as 0 to the form; writing "0" back into it is noise.
  if (typed === "") return value !== 0;
  const current = evaluateQuantity(typed);
  // Still being typed: leave it be until it is a figure again.
  if (current === null) return false;
  return current !== value;
}
