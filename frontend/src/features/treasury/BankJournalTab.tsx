import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Link2, Unlink, Upload } from "lucide-react";
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
import { listAccounts } from "./api";
import {
  fileToBase64,
  getStatementSummary,
  getSuggestions,
  importStatement,
  listStatementLines,
  matchLine,
  setLinePartner,
  type ImportResult,
} from "./statementsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
const fmt = (value: string | null) => (value === null ? "" : new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 2 }).format(Number(value)));

export function BankJournalTab() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canImport = hasPermission("treasury.import_statements");
  const [accountId, setAccountId] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);

  const { data: accounts = [] } = useQuery({ queryKey: ["treasury", "accounts"], queryFn: () => listAccounts(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const bankAccounts = accounts.filter((a) => a.kind === "bank");
  const activeId = accountId || bankAccounts[0]?.id || "";

  const linesKey = ["treasury", "statement-lines", activeId] as const;
  const { data: lines = [] } = useQuery({ queryKey: linesKey, queryFn: () => listStatementLines(token, activeId), enabled: activeId !== "" });
  const { data: suggestions } = useQuery({
    queryKey: ["treasury", "statement-suggestions", activeId, lines.length],
    queryFn: () => getSuggestions(token, activeId),
    enabled: activeId !== "",
  });
  const { data: summary } = useQuery({
    queryKey: ["treasury", "statement-summary", activeId, lines.length],
    queryFn: () => getStatementSummary(token, activeId),
    enabled: activeId !== "",
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["treasury", "statement-lines"] });
    queryClient.invalidateQueries({ queryKey: ["treasury", "statement-suggestions"] });
    queryClient.invalidateQueries({ queryKey: ["treasury", "statement-summary"] });
  };
  const fail = (key: Key) => (error: unknown) =>
    toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const importMutation = useMutation({
    mutationFn: async (commit: boolean) =>
      importStatement(token, { account_id: activeId, filename: file!.name, content_base64: await fileToBase64(file!), commit }),
    onSuccess: (result, commit) => {
      setPreview(result);
      if (commit) {
        refresh();
        setImportOpen(false);
        setFile(null);
        setPreview(null);
        toast.success(t("treasury.statement.imported"));
      }
    },
    onError: fail("treasury.statement.importError"),
  });
  const partnerMutation = useMutation({
    mutationFn: ({ lineId, partnerId }: { lineId: string; partnerId: string | null }) => setLinePartner(token, lineId, partnerId),
    onSuccess: refresh,
    onError: fail("treasury.statement.saveError"),
  });
  const matchMutation = useMutation({
    mutationFn: ({ lineId, paymentId }: { lineId: string; paymentId: string | null }) => matchLine(token, lineId, paymentId),
    onSuccess: refresh,
    onError: fail("treasury.statement.saveError"),
  });

  const partnersFor = (debit: string) =>
    partners.filter((p) => p.status === "active" && (Number(debit) > 0 ? ["customer", "both"] : ["supplier", "both"]).includes(p.kind));

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("treasury.statement.title")}</CardTitle>
            <Select className="w-56" value={activeId} onChange={(e) => setAccountId(e.target.value)}>
              {bankAccounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </Select>
          </div>
          {canImport && activeId && (
            <Button onClick={() => setImportOpen(true)}>
              <Upload className="h-4 w-4" />
              {t("treasury.statement.import")}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-4 p-0">
          {summary && (
            <div className="grid gap-3 px-6 pt-2 sm:grid-cols-4">
              <Stat label={t("treasury.statement.accountBalance")} value={fmt(summary.account_balance)} />
              <Stat label={t("treasury.statement.statementBalance")} value={fmt(summary.statement_balance) || "—"} />
              <Stat label={t("treasury.statement.difference")} value={fmt(summary.difference) || "—"} warn={!!summary.difference && Number(summary.difference) !== 0} />
              <Stat label={t("treasury.statement.reconciled")} value={`${summary.matched} / ${summary.lines}`} />
            </div>
          )}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.date")}</TableHead>
                <TableHead>{t("treasury.journal.label")}</TableHead>
                <TableHead className="text-right">{t("treasury.statement.debit")}</TableHead>
                <TableHead className="text-right">{t("treasury.statement.credit")}</TableHead>
                <TableHead>{t("treasury.column.partner")}</TableHead>
                <TableHead className="text-right">{t("treasury.statement.reconcile")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="p-0">
                    <EmptyState icon={<FileSpreadsheet className="h-5 w-5" />} title={t("treasury.statement.empty.title")} description={t("treasury.statement.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {lines.map((line) => {
                const suggested = suggestions?.suggestions[line.id];
                const payment = suggestions?.payments.find((p) => p.id === suggested);
                // The suggestion only looks 5 days around the line; any payment of the same direction and
                // amount can still be chosen by hand, nearest date first.
                const direction = Number(line.debit) > 0 ? "in" : "out";
                const amount = Number(direction === "in" ? line.debit : line.credit);
                const lineTime = new Date(line.line_date).getTime();
                const others = (suggestions?.payments ?? [])
                  .filter((p) => p.id !== suggested && p.direction === direction && Number(p.amount) === amount)
                  .sort((a, b) => Math.abs(new Date(a.date).getTime() - lineTime) - Math.abs(new Date(b.date).getTime() - lineTime));
                return (
                  <TableRow key={line.id}>
                    <TableCell>{line.line_date}</TableCell>
                    <TableCell>{line.label}</TableCell>
                    <TableCell className="text-right tabular-nums">{Number(line.debit) ? fmt(line.debit) : ""}</TableCell>
                    <TableCell className="text-right tabular-nums">{Number(line.credit) ? fmt(line.credit) : ""}</TableCell>
                    <TableCell>
                      <Select
                        disabled={!canImport}
                        value={line.partner_id ?? ""}
                        onChange={(e) => partnerMutation.mutate({ lineId: line.id, partnerId: e.target.value || null })}
                      >
                        <option value="">—</option>
                        {partnersFor(line.debit).map((p) => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </Select>
                    </TableCell>
                    <TableCell className="text-right">
                      {line.matched_payment_id ? (
                        canImport && (
                          <Button size="sm" variant="outline" onClick={() => matchMutation.mutate({ lineId: line.id, paymentId: null })}>
                            <Unlink className="h-3.5 w-3.5" />
                            {t("treasury.statement.unmatch")}
                          </Button>
                        )
                      ) : (
                        canImport && (
                          <div className="flex flex-wrap items-center justify-end gap-2">
                            {payment && (
                              <Button size="sm" variant="outline" disabled={matchMutation.isPending} onClick={() => matchMutation.mutate({ lineId: line.id, paymentId: payment.id })}>
                                <Link2 className="h-3.5 w-3.5" />
                                {payment.document_number}
                              </Button>
                            )}
                            {others.length > 0 && (
                              <Select
                                aria-label={t("treasury.statement.chooseMatch")}
                                className="h-8 w-auto"
                                value=""
                                disabled={matchMutation.isPending}
                                onChange={(e) => e.target.value && matchMutation.mutate({ lineId: line.id, paymentId: e.target.value })}
                              >
                                <option value="">{t(payment ? "treasury.statement.chooseOther" : "treasury.statement.chooseMatch")}</option>
                                {others.map((p) => (
                                  <option key={p.id} value={p.id}>{p.document_number} · {p.date}</option>
                                ))}
                              </Select>
                            )}
                          </div>
                        )
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={importOpen} onOpenChange={(open) => { setImportOpen(open); if (!open) { setPreview(null); setFile(null); } }}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("treasury.statement.import")}</DialogTitle>
            <DialogDescription>{t("treasury.statement.importDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="stmt_file">{t("treasury.statement.file")}</Label>
              <Input id="stmt_file" type="file" accept=".xlsx,.csv,.txt" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); }} />
            </div>
            <Button disabled={!file || importMutation.isPending} variant="outline" onClick={() => importMutation.mutate(false)}>
              {t("treasury.statement.preview")}
            </Button>
            {preview && (
              <div className="space-y-2 text-sm">
                <p>
                  {preview.new_lines.length} {t("treasury.statement.newLines")} · {preview.duplicate_lines.length} {t("treasury.statement.duplicates")}
                </p>
                {preview.errors.map((e) => (
                  <p key={`e${e.row}`} className="text-destructive">
                    {t("treasury.statement.row")} {e.row}: {language === "fr" ? e.message_fr : e.message}
                  </p>
                ))}
                {preview.warnings.map((w) => (
                  <p key={`w${w.row}`} className="text-warning">
                    {t("treasury.statement.row")} {w.row}: {language === "fr" ? w.message_fr : w.message}
                  </p>
                ))}
                <Button className="w-full" disabled={preview.errors.length > 0 || preview.new_lines.length === 0 || importMutation.isPending} onClick={() => importMutation.mutate(true)}>
                  {t("treasury.statement.commit")}
                </Button>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-md border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${warn ? "text-destructive" : ""}`}>{value}</p>
    </div>
  );
}
