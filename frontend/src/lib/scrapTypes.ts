import { useI18n } from "./i18n";
import type { ScrapType } from "../features/production/api";

/**
 * Only "cutting" and "filling_dosing" are ever picked by a person, in the
 * "Enregistrer un rebut" dialog. "daily_report" (a validated daily report's
 * own rebroyat figure) and "non_conformity" (a QC disposition sending a
 * rejected packet back to regrind) are written by the backend itself -- a
 * scrap row of either kind used to fall through to the "filling / dosing"
 * label just because it wasn't "cutting", which misrepresented where the
 * figure actually came from.
 */
export function useScrapTypeLabels(): Record<ScrapType, string> {
  const { t } = useI18n();
  return {
    cutting: t("production.regrind.scrapType.cutting"),
    filling_dosing: t("production.regrind.scrapType.fillingDosing"),
    daily_report: t("production.regrind.scrapType.dailyReport"),
    non_conformity: t("production.regrind.scrapType.nonConformity"),
  };
}
