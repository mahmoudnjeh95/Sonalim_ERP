const FORMAT_NAME: Record<string, string> = { packet: "Sachet", carton: "Carton", sac: "Sac" };

/**
 * "Sachet 500 g": the classified packaging format and the net weight, as the paper fiche writes it.
 * Mirrors the server's rule so the type shows the moment a product is picked; the server's own
 * value replaces it on the next load.
 */
export function packingTypeLabel(netWeightGrams: number | null | undefined, packagingFormat: string | null | undefined): string {
  const name = FORMAT_NAME[packagingFormat ?? ""];
  const grams = netWeightGrams && netWeightGrams > 0 ? Number(netWeightGrams) : null;
  const weight = grams === null ? null : `${Number.isInteger(grams) ? grams : Number(grams.toPrecision(12))} g`;
  return [name, weight].filter(Boolean).join(" ");
}
