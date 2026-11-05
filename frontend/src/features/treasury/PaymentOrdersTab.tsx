import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Eye, FileText, Printer } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { listPartners } from "../partners/api";
import { InvoicePaymentOrdersCard } from "./InvoicePaymentOrdersCard";
import { getPaymentOrder, listNotifiableUsers, listPaymentOrders, notifyPaymentOrder } from "./paymentOrdersApi";

const money = (value: string, currency: string) => {
  try {
    return new Intl.NumberFormat(currentLocale(), { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
  } catch {
    return `${value} ${currency}`;
  }
};

export function PaymentOrdersTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("treasury.manage_disbursements");
  const [selected, setSelected] = useState<string | null>(null);
  const [userId, setUserId] = useState("");

  const { data: orders = [] } = useQuery({ queryKey: ["treasury", "payment-orders"], queryFn: () => listPaymentOrders(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: order } = useQuery({ queryKey: ["treasury", "payment-order", selected], queryFn: () => getPaymentOrder(token, selected!), enabled: selected !== null });
  const { data: users = [] } = useQuery({ queryKey: ["treasury", "notifiable-users"], queryFn: () => listNotifiableUsers(token), enabled: selected !== null && canManage });
  const partnerName = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  const notifyMutation = useMutation({
    mutationFn: () => notifyPaymentOrder(token, selected!, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["treasury", "notifications"] });
      toast.success(t("treasury.order.notified"));
    },
    onError: (error) => toast.error(t("treasury.order.notifyError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <div className="space-y-6">
      <InvoicePaymentOrdersCard />
      <Card>
        <CardHeader>
          <CardTitle>{t("treasury.order.title")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.number")}</TableHead>
                <TableHead>{t("treasury.order.disbursement")}</TableHead>
                <TableHead>{t("treasury.column.partner")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.amount")}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="p-0">
                    <EmptyState icon={<FileText className="h-5 w-5" />} title={t("treasury.order.empty.title")} description={t("treasury.order.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {orders.map((o) => (
                <TableRow key={o.id}>
                  <TableCell className="font-mono text-xs">{o.number}</TableCell>
                  <TableCell className="font-mono text-xs">{o.disbursement_number}</TableCell>
                  <TableCell>{partnerName(o.partner_id)}</TableCell>
                  <TableCell className="text-right tabular-nums">{money(o.total, o.currency)}</TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="outline" onClick={() => setSelected(o.id)}>
                      <Eye className="h-3.5 w-3.5" />
                      {t("treasury.order.view")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{order?.number}</DialogTitle>
            <DialogDescription>
              {order && `${partnerName(order.partner_id)} · ${order.doc_date}`}
            </DialogDescription>
          </DialogHeader>
          {order && (
            <div className="space-y-4 print:text-black">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("treasury.order.fromAccount")}</TableHead>
                    <TableHead>{t("treasury.field.accountNumber")}</TableHead>
                    <TableHead className="text-right">{t("treasury.column.amount")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {order.transfers.map((tr) => (
                    <TableRow key={tr.payment_id}>
                      <TableCell>{tr.account_name}</TableCell>
                      <TableCell className="font-mono text-xs">{tr.iban ?? tr.account_number}</TableCell>
                      <TableCell className="text-right tabular-nums">{money(tr.amount, order.currency)}</TableCell>
                    </TableRow>
                  ))}
                  <TableRow>
                    <TableCell colSpan={2} className="font-medium">{t("treasury.document.total")}</TableCell>
                    <TableCell className="text-right font-medium tabular-nums">{money(order.total, order.currency)}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
              <div className="flex flex-wrap items-end gap-2 print:hidden">
                <Button variant="outline" onClick={() => window.print()}>
                  <Printer className="h-4 w-4" />
                  {t("treasury.order.print")}
                </Button>
                {canManage && (
                  <>
                    <div className="min-w-48 flex-1 space-y-1.5">
                      <Label htmlFor="notify_user">{t("treasury.order.notifyUser")}</Label>
                      <Select id="notify_user" value={userId} onChange={(e) => setUserId(e.target.value)}>
                        <option value="">—</option>
                        {users.map((u) => (
                          <option key={u.id} value={u.id}>{u.email}</option>
                        ))}
                      </Select>
                    </div>
                    <Button disabled={!userId || notifyMutation.isPending} onClick={() => notifyMutation.mutate()}>
                      <Bell className="h-4 w-4" />
                      {t("treasury.order.notify")}
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
