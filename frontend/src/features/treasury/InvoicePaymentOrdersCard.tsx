import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, ClipboardCheck, Eye, Plus, Printer } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { listPartners } from "../partners/api";
import { createInvoicePaymentOrder, listInvoicePaymentOrders, listNotifiableUsers, notifyInvoicePaymentOrder, type InvoicePaymentOrder } from "./paymentOrdersApi";
import { listOpenInvoices, type PaymentMethod } from "./paymentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
const METHODS: PaymentMethod[] = ["cheque", "draft", "transfer", "cash", "mobile_money"];
const today = () => new Date().toISOString().slice(0, 10);
const fmt = (value: string | null) => (value === null ? "—" : new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(Number(value)));

/** Ordres de paiement: asking someone to pay a purchase invoice, before any disbursement exists. */
export function InvoicePaymentOrdersCard() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("treasury.manage_disbursements");
  const [formOpen, setFormOpen] = useState(false);
  const [selected, setSelected] = useState<InvoicePaymentOrder | null>(null);
  const [notifyUser, setNotifyUser] = useState("");
  const [partnerId, setPartnerId] = useState("");
  const [invoiceId, setInvoiceId] = useState("");
  const [orderDate, setOrderDate] = useState(today());
  const [dueDate, setDueDate] = useState(today());
  const [method, setMethod] = useState<PaymentMethod>("cheque");
  const [employee, setEmployee] = useState("");
  const [department, setDepartment] = useState("");

  const { data: orders = [] } = useQuery({ queryKey: ["treasury", "invoice-payment-orders"], queryFn: () => listInvoicePaymentOrders(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token), enabled: formOpen });
  const { data: users = [] } = useQuery({ queryKey: ["treasury", "notifiable-users"], queryFn: () => listNotifiableUsers(token), enabled: canManage && (formOpen || selected !== null) });
  const { data: invoices = [] } = useQuery({
    queryKey: ["treasury", "open-invoices", "out", partnerId],
    queryFn: () => listOpenInvoices(token, "out", partnerId),
    enabled: formOpen && partnerId !== "",
  });
  const invoice = invoices.find((i) => i.id === invoiceId);

  const fail = (key: Key) => (error: unknown) =>
    toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const createMutation = useMutation({
    mutationFn: () =>
      createInvoicePaymentOrder(token, {
        order_date: orderDate,
        due_date: dueDate,
        method,
        invoice_id: invoiceId,
        employee_user_id: employee,
        department: department || undefined,
      }),
    onSuccess: (order) => {
      queryClient.invalidateQueries({ queryKey: ["treasury", "invoice-payment-orders"] });
      setFormOpen(false);
      setPartnerId("");
      setInvoiceId("");
      setDepartment("");
      setSelected(order);
      toast.success(`${t("treasury.paymentOrder.created")} ${order.number}`);
    },
    onError: fail("treasury.paymentOrder.createError"),
  });
  const notifyMutation = useMutation({
    mutationFn: () => notifyInvoicePaymentOrder(token, selected!.id, notifyUser),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["treasury", "notifications"] });
      toast.success(t("treasury.order.notified"));
    },
    onError: fail("treasury.order.notifyError"),
  });

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("treasury.paymentOrder.title")}</CardTitle>
          {canManage && (
            <Button onClick={() => setFormOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("treasury.paymentOrder.new")}
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.number")}</TableHead>
                <TableHead>{t("treasury.column.date")}</TableHead>
                <TableHead>{t("treasury.paymentOrder.dueDate")}</TableHead>
                <TableHead>{t("treasury.column.partner")}</TableHead>
                <TableHead>{t("treasury.paymentOrder.invoice")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.amount")}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="p-0">
                    <EmptyState icon={<ClipboardCheck className="h-5 w-5" />} title={t("treasury.paymentOrder.empty.title")} description={t("treasury.paymentOrder.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {orders.map((order) => (
                <TableRow key={order.id}>
                  <TableCell className="font-mono text-xs">{order.number}</TableCell>
                  <TableCell>{order.order_date}</TableCell>
                  <TableCell>{order.due_date}</TableCell>
                  <TableCell>{order.partner_name}</TableCell>
                  <TableCell className="font-mono text-xs">{order.invoice_number ?? order.supplier_invoice_number ?? "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(order.amount)}</TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="outline" onClick={() => setSelected(order)}>
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

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("treasury.paymentOrder.new")}</DialogTitle>
            <DialogDescription>{t("treasury.paymentOrder.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); createMutation.mutate(); }}>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="po_date">{t("treasury.column.date")}</Label>
                <Input id="po_date" type="date" required value={orderDate} onChange={(e) => setOrderDate(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="po_due">{t("treasury.paymentOrder.dueDate")}</Label>
                <Input id="po_due" type="date" required value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="po_method">{t("treasury.paymentOrder.method")}</Label>
                <Select id="po_method" value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
                  {METHODS.map((m) => <option key={m} value={m}>{t(`treasury.method.${m}` as Key)}</option>)}
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="po_partner">{t("treasury.paymentOrder.supplier")}</Label>
                <Select id="po_partner" required value={partnerId} onChange={(e) => { setPartnerId(e.target.value); setInvoiceId(""); }}>
                  <option value="">—</option>
                  {partners.filter((p) => p.status === "active" && p.kind !== "customer").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="po_invoice">{t("treasury.paymentOrder.invoice")}</Label>
                <Select id="po_invoice" required value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)}>
                  <option value="">—</option>
                  {invoices.map((i) => <option key={i.id} value={i.id}>{i.number ?? i.supplier_invoice_number ?? i.id.slice(-6)}</option>)}
                </Select>
              </div>
            </div>
            {invoice && (
              <p className="text-sm text-muted-foreground">
                {t("treasury.paymentOrder.total")} : <span className="tabular-nums">{fmt(invoice.amount)}</span> · {t("treasury.reports.remaining")} : <span className="tabular-nums">{fmt(invoice.remaining)}</span>
              </p>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="po_employee">{t("treasury.paymentOrder.employee")}</Label>
                <Select id="po_employee" required value={employee} onChange={(e) => setEmployee(e.target.value)}>
                  <option value="">—</option>
                  {users.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="po_department">{t("treasury.paymentOrder.department")}</Label>
                <Input id="po_department" value={department} onChange={(e) => setDepartment(e.target.value)} />
              </div>
            </div>
            <Button type="submit" className="w-full" disabled={createMutation.isPending}>{t("common.save")}</Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{selected?.number}</DialogTitle>
            <DialogDescription>{selected?.partner_name}</DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-4">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <div><dt className="text-muted-foreground">{t("treasury.column.date")}</dt><dd>{selected.order_date}</dd></div>
                <div><dt className="text-muted-foreground">{t("treasury.paymentOrder.dueDate")}</dt><dd>{selected.due_date}</dd></div>
                <div><dt className="text-muted-foreground">{t("treasury.paymentOrder.method")}</dt><dd>{t(`treasury.method.${selected.method}` as Key)}</dd></div>
                <div><dt className="text-muted-foreground">{t("treasury.paymentOrder.invoice")}</dt><dd>{selected.invoice_number ?? selected.supplier_invoice_number ?? "—"}</dd></div>
                <div><dt className="text-muted-foreground">{t("treasury.paymentOrder.invoiceDate")}</dt><dd>{selected.invoice_date ?? "—"}</dd></div>
                <div><dt className="text-muted-foreground">{t("treasury.paymentOrder.total")}</dt><dd className="tabular-nums">{fmt(selected.amount)}</dd></div>
                <div><dt className="text-muted-foreground">{t("treasury.paymentOrder.employee")}</dt><dd>{selected.employee_email}</dd></div>
                <div><dt className="text-muted-foreground">{t("treasury.paymentOrder.department")}</dt><dd>{selected.department ?? "—"}</dd></div>
              </dl>
              <div className="flex flex-wrap items-end gap-2 print:hidden">
                <Button variant="outline" onClick={() => window.print()}>
                  <Printer className="h-4 w-4" />
                  {t("treasury.order.print")}
                </Button>
                {canManage && (
                  <>
                    <div className="min-w-48 flex-1 space-y-1.5">
                      <Label htmlFor="po_notify">{t("treasury.order.notifyUser")}</Label>
                      <Select id="po_notify" value={notifyUser} onChange={(e) => setNotifyUser(e.target.value)}>
                        <option value="">—</option>
                        {users.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
                      </Select>
                    </div>
                    <Button disabled={!notifyUser || notifyMutation.isPending} onClick={() => notifyMutation.mutate()}>
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
    </>
  );
}
