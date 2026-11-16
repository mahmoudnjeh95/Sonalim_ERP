import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { formatAmount } from "../finance/ledgerFormat";
import { getCreditPreview } from "../finance/receivablesApi";
import type { SalesOrder } from "./api";

/** Before an order is confirmed: the customer's exposure against its credit limit, what is late, and what
 *  credit control will say. The server decides; this only shows it, and offers the override to whoever holds it. */
export function ConfirmOrderCreditDialog({ order, customerName, pending, onConfirm, onClose }: {
  order: SalesOrder;
  customerName: string;
  pending: boolean;
  onConfirm: (override: boolean) => void;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const [override, setOverride] = useState(false);
  const { data: preview, isLoading } = useQuery({
    queryKey: ["finance", "receivables", "credit-check", order.partner_id, order.total_amount],
    queryFn: () => getCreditPreview(session!.token, order.partner_id, order.total_amount),
  });
  const message = (reason: { message: string; message_fr: string }) => (language === "fr" ? reason.message_fr : reason.message);
  const blocked = (preview?.blocking.length ?? 0) > 0;
  const amount = (value: string | number | null | undefined) => formatAmount(Number(value ?? 0));

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("sales.credit.title")} — {customerName}</DialogTitle>
          <DialogDescription>{t("sales.credit.description")}</DialogDescription>
        </DialogHeader>
        {isLoading || !preview ? (
          <p className="text-sm text-muted-foreground">{t("sales.credit.loading")}</p>
        ) : (
          <div className="space-y-3 text-sm">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
              <dt className="text-muted-foreground">{t("sales.credit.order")}</dt><dd className="text-right tabular-nums">{amount(preview.order_amount)}</dd>
              <dt className="text-muted-foreground">{t("finance.receivables.exposure")}</dt><dd className="text-right tabular-nums">{amount(preview.exposure)}</dd>
              <dt className="text-muted-foreground">{t("finance.receivables.creditLimit")}</dt>
              <dd className="text-right tabular-nums">{preview.credit_limit === null ? t("finance.receivables.noLimit") : amount(preview.credit_limit)}</dd>
              <dt className="text-muted-foreground">{t("finance.receivables.column.overdue")}</dt>
              <dd className="text-right tabular-nums">{amount(preview.overdue)}{preview.max_days_overdue ? ` (${preview.max_days_overdue} ${t("sales.credit.days")})` : ""}</dd>
            </dl>
            {preview.warnings.map((reason) => (
              <p key={reason.code} className="flex gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-warning">
                <AlertTriangle className="h-4 w-4 shrink-0" />{message(reason)}
              </p>
            ))}
            {preview.blocking.map((reason) => (
              <p key={reason.code} className="flex gap-2 rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-destructive">
                <ShieldAlert className="h-4 w-4 shrink-0" />{message(reason)}
              </p>
            ))}
            {blocked && (preview.can_override ? (
              <label className="flex items-center gap-2">
                <Checkbox checked={override} onCheckedChange={(checked) => setOverride(checked === true)} />
                {t("sales.credit.override")}
              </label>
            ) : (
              <p className="text-muted-foreground">{t("sales.credit.blockedNoOverride")}</p>
            ))}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
          <Button disabled={pending || isLoading || (blocked && !override)} onClick={() => onConfirm(override)}>
            {pending ? t("sales.confirming") : t("sales.confirm")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
