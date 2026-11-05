import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Paperclip, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { addAttachment, deleteAttachment, downloadAttachment, getDocument, listAttachments, type Direction } from "./paymentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
const fmt = (value: string) => new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(Number(value));
const MAX_BYTES = 10 * 1024 * 1024;

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/** One receipt or disbursement in full: its payments, the invoices it settled, its note and its files. */
export function DocumentDetailDialog({ direction, documentId, onClose }: { direction: Direction; documentId: string | null; onClose: () => void }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission(direction === "in" ? "treasury.manage_receipts" : "treasury.manage_disbursements");
  const fileInput = useRef<HTMLInputElement>(null);
  const attachmentsKey = ["treasury", "attachments", direction, documentId];

  const { data: document } = useQuery({
    queryKey: ["treasury", "document", direction, documentId],
    queryFn: () => getDocument(token, direction, documentId!),
    enabled: documentId !== null,
  });
  const { data: attachments = [] } = useQuery({
    queryKey: attachmentsKey,
    queryFn: () => listAttachments(token, direction, documentId!),
    enabled: documentId !== null,
  });

  const fail = (error: unknown) => toast.error(t("treasury.attachment.error"), { description: error instanceof ApiError ? error.message : undefined });
  const addMutation = useMutation({
    mutationFn: async (file: File) =>
      addAttachment(token, direction, documentId!, { filename: file.name, content_type: file.type || undefined, content_base64: await readBase64(file) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: attachmentsKey }),
    onError: fail,
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAttachment(token, direction, documentId!, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: attachmentsKey }),
    onError: fail,
  });

  async function open(id: string, filename: string) {
    try {
      const blob = await downloadAttachment(token, direction, documentId!, id);
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = filename;
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      fail(error);
    }
  }

  return (
    <Dialog open={documentId !== null} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{document?.number}</DialogTitle>
          <DialogDescription>{document?.doc_date}</DialogDescription>
        </DialogHeader>
        {document && (
          <div className="space-y-4 text-sm">
            <dl className="grid grid-cols-3 gap-3">
              <div><dt className="text-muted-foreground">{t("treasury.document.settlement")}</dt><dd className="tabular-nums">{fmt(document.total)}</dd></div>
              <div><dt className="text-muted-foreground">{t("treasury.document.withheld")}</dt><dd className="tabular-nums">{fmt(document.withheld_amount)}</dd></div>
              <div><dt className="text-muted-foreground">{t("treasury.document.unallocated")}</dt><dd className="tabular-nums">{fmt(document.unallocated)}</dd></div>
            </dl>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("treasury.document.payments")}</TableHead>
                  <TableHead className="text-right">{t("treasury.column.amount")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {document.payments.map((payment) => (
                  <TableRow key={payment.id}>
                    <TableCell>
                      {t(`treasury.method.${payment.method}` as Key)}
                      {payment.reference && ` · ${payment.reference}`}
                      {payment.denominations && (
                        <span className="block text-xs text-muted-foreground">
                          {Object.entries(payment.denominations).filter(([, count]) => count > 0).map(([value, count]) => `${count} x ${value}`).join(" · ")}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(payment.amount)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {document.instruments.length > 0 && (
              <ul className="space-y-1">
                {document.instruments.map((instrument) => (
                  <li key={instrument.id} className="rounded-md border border-border p-2">
                    <span className="font-medium">{t(`treasury.method.${instrument.method}` as Key)} {instrument.number}</span> · {t(`treasury.instruments.status.${instrument.status}` as Key)}
                    <span className="block text-xs text-muted-foreground">
                      {[instrument.bank_name, instrument.branch_name, instrument.issue_date && `${t("treasury.instrument.issueDate")} ${instrument.issue_date}`,
                        `${t("treasury.instruments.column.due")} ${instrument.due_date}`, instrument.deposit_date && `${t("treasury.instrument.depositDate")} ${instrument.deposit_date}`,
                        instrument.slip_reference].filter(Boolean).join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {document.note && <p className="whitespace-pre-wrap rounded-md bg-muted/40 p-2">{document.note}</p>}

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="font-medium">{t("treasury.attachment.title")}</p>
                {canManage && (
                  <>
                    <input
                      ref={fileInput}
                      type="file"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (!file) return;
                        if (file.size > MAX_BYTES) {
                          toast.error(t("treasury.attachment.tooLarge"));
                          return;
                        }
                        addMutation.mutate(file);
                      }}
                    />
                    <Button size="sm" variant="outline" disabled={addMutation.isPending} onClick={() => fileInput.current?.click()}>
                      <Paperclip className="h-3.5 w-3.5" />
                      {t("treasury.attachment.add")}
                    </Button>
                  </>
                )}
              </div>
              {attachments.length === 0 && <p className="text-muted-foreground">{t("treasury.attachment.none")}</p>}
              <ul className="space-y-1">
                {attachments.map((attachment) => (
                  <li key={attachment.id} className="flex items-center justify-between gap-2">
                    <span className="truncate">{attachment.filename}</span>
                    <span className="flex gap-1">
                      <Button size="sm" variant="ghost" aria-label={t("treasury.attachment.open")} title={t("treasury.attachment.open")} onClick={() => open(attachment.id, attachment.filename)}>
                        <Download className="h-3.5 w-3.5" />
                      </Button>
                      {canManage && (
                        <Button size="sm" variant="ghost" aria-label={t("treasury.attachment.delete")} title={t("treasury.attachment.delete")} disabled={deleteMutation.isPending} onClick={() => {
                          if (window.confirm(t("attachment.deleteConfirm").replace("{name}", attachment.filename))) deleteMutation.mutate(attachment.id);
                        }}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
