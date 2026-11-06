import { useQuery } from "@tanstack/react-query";
import { ReceiptText } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { formatXofWithCode } from "../../lib/currency";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { listCreditNotes } from "./api";
import { LedgerStatusBadge, useLedgerStatuses } from "./ledgerStatus";

/** Sales credit notes (factures avoir): one per return against an invoiced delivery. */
export function CreditNotesCard({ partnerName, onOpenInvoice }: { partnerName: (id: string) => string; onOpenInvoice: (id: string) => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const { data: notes = [] } = useQuery({ queryKey: ["finance", "credit-notes"], queryFn: () => listCreditNotes(session!.token) });
  // Credit notes post under ("finance", credit_note_id), like the invoices they correct.
  const ledgerStatuses = useLedgerStatuses("finance", notes.map((note) => note.id));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("finance.creditNotes.title")}</CardTitle>
        <p className="mt-0.5 text-sm text-muted-foreground">{t("finance.creditNotes.subtitle")}</p>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("finance.creditNotes.number")}</TableHead>
              <TableHead>{t("finance.detail.date")}</TableHead>
              <TableHead>{t("finance.column.partner")}</TableHead>
              <TableHead>{t("finance.creditNotes.invoice")}</TableHead>
              <TableHead>{t("finance.creditNotes.return")}</TableHead>
              <TableHead className="text-right">{t("finance.column.amount")}</TableHead>
              <TableHead>{t("finance.ledgerStatus.column")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {notes.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="p-0">
                  <EmptyState icon={<ReceiptText className="h-5 w-5" />} title={t("finance.creditNotes.none")} description={t("finance.creditNotes.emptyDescription")} />
                </TableCell>
              </TableRow>
            )}
            {notes.map((note) => (
              <TableRow key={note.id}>
                <TableCell className="font-medium">{note.number}</TableCell>
                <TableCell>{note.credit_date}</TableCell>
                <TableCell>{partnerName(note.partner_id)}</TableCell>
                <TableCell>
                  <button type="button" className="text-primary underline-offset-2 hover:underline" onClick={() => onOpenInvoice(note.invoice_id)}>
                    {note.invoice_number ?? "—"}
                  </button>
                </TableCell>
                <TableCell>{note.return_number ?? "—"}</TableCell>
                <TableCell className="text-right tabular-nums">{formatXofWithCode(note.amount)}</TableCell>
                <TableCell>
                  <LedgerStatusBadge status={ledgerStatuses[note.id]} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
