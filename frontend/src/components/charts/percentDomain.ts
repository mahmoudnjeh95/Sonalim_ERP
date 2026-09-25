/**
 * Upper bound for a percentage axis: 100% normally, raised to the next round
 * 10% when a value goes past it (e.g. a 111% yield → a 0–120% axis), so the
 * point stays on the plot and the ticks stay even instead of topping out at
 * an odd "111%".
 */
export function percentAxisMax(dataMax: number): number {
  return Number.isFinite(dataMax) && dataMax > 100 ? Math.ceil(dataMax / 10) * 10 : 100;
}
