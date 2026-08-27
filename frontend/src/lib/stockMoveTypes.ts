import type { BadgeProps } from "../components/ui/badge";
import type { StockMoveType } from "../features/warehouse/api";
import { useI18n } from "./i18n";

export const MOVE_TYPE_VARIANT: Record<StockMoveType, BadgeProps["variant"]> = {
  receipt: "success",
  issue: "warning",
  adjustment: "accent",
  reservation: "default",
  reservation_released: "outline",
  production: "primary",
  send_to_production: "primary",
  production_consumption: "primary",
  transfer_out: "warning",
  transfer_in: "success",
  admin_correction: "destructive",
};

export function useMoveTypeLabels(): Record<StockMoveType, string> {
  const { t } = useI18n();
  return {
    receipt: t("warehouse.stockHistory.type.receipt"),
    issue: t("warehouse.stockHistory.type.issue"),
    adjustment: t("warehouse.stockHistory.type.adjustment"),
    reservation: t("warehouse.stockHistory.type.reservation"),
    reservation_released: t("warehouse.stockHistory.type.reservationReleased"),
    production: t("warehouse.stockHistory.type.production"),
    send_to_production: t("warehouse.stockHistory.type.sendToProduction"),
    production_consumption: t("warehouse.stockHistory.type.productionConsumption"),
    transfer_out: t("warehouse.stockHistory.type.transferOut"),
    transfer_in: t("warehouse.stockHistory.type.transferIn"),
    admin_correction: t("warehouse.stockHistory.type.adminCorrection"),
  };
}
