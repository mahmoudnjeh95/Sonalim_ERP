import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { Button } from "../../../../components/ui/button";
import { Checkbox } from "../../../../components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../../components/ui/dialog";
import { Input } from "../../../../components/ui/input";
import { Label } from "../../../../components/ui/label";
import { Select } from "../../../../components/ui/select";
import { Skeleton } from "../../../../components/ui/skeleton";
import { useI18n, type TranslationKey } from "../../../../lib/i18n";
import {
  BANK_TEMPLATE_FIELDS,
  useBankTemplates,
  useCreateTemplate,
  useDeleteTemplate,
  useUpdateTemplate,
  type BankFileTemplate,
  type BankTemplateColumn,
} from "../../api";

/** The separators the server accepts (domain/payouts.py DELIMITERS). */
const DELIMITERS: { value: string; labelKey: TranslationKey }[] = [
  { value: ";", labelKey: "payroll.payouts.templates.delimiter.semicolon" },
  { value: ",", labelKey: "payroll.payouts.templates.delimiter.comma" },
  { value: "\t", labelKey: "payroll.payouts.templates.delimiter.tab" },
  { value: "|", labelKey: "payroll.payouts.templates.delimiter.pipe" },
];

/** A starting point for a new template: the column titles are what the bank's file expects, edited per bank. */
const DEFAULT_COLUMNS: BankTemplateColumn[] = [
  { header: "Compte", field: "account_no" },
  { header: "Nom", field: "full_name" },
  { header: "Montant", field: "amount" },
];

interface Draft {
  /** null for a new template. */
  id: string | null;
  bankName: string;
  delimiter: string;
  includeHeader: boolean;
  columns: BankTemplateColumn[];
}

function newDraft(bankName = ""): Draft {
  return { id: null, bankName, delimiter: ";", includeHeader: true, columns: DEFAULT_COLUMNS.map((column) => ({ ...column })) };
}

function errorText(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}

/**
 * The bank file templates a bank payout batch is written with (one per bank). Opened with
 * `bankName` when a batch's bank has none, so the form starts on that bank.
 */
export function BankTemplatesDialog({
  open,
  onOpenChange,
  bankName,
  canEdit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  bankName?: string | null;
  canEdit: boolean;
}) {
  const { t } = useI18n();
  const { data: templates = [], isLoading } = useBankTemplates();
  const create = useCreateTemplate();
  const update = useUpdateTemplate();
  const remove = useDeleteTemplate();
  const [draft, setDraft] = useState<Draft | null>(null);
  const save = draft?.id ? update : create;

  // Each opening starts clean: on the missing bank's new template, or on the list.
  useEffect(() => {
    if (!open) return;
    create.reset();
    update.reset();
    setDraft(bankName && canEdit ? newDraft(bankName) : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, bankName, canEdit]);

  const delimiterLabel = (value: string) => {
    const entry = DELIMITERS.find((delimiter) => delimiter.value === value);
    return entry ? t(entry.labelKey) : value;
  };

  const edit = (template: BankFileTemplate) => {
    create.reset();
    update.reset();
    setDraft({
      id: template.id,
      bankName: template.bank_name,
      delimiter: template.delimiter,
      includeHeader: template.include_header,
      columns: template.columns.map((column) => ({ ...column })),
    });
  };

  const startNew = () => {
    create.reset();
    update.reset();
    setDraft(newDraft());
  };

  const setColumn = (index: number, changes: Partial<BankTemplateColumn>) =>
    setDraft((current) =>
      current ? { ...current, columns: current.columns.map((column, i) => (i === index ? { ...column, ...changes } : column)) } : current,
    );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    const values = {
      bank_name: draft.bankName.trim(),
      delimiter: draft.delimiter,
      include_header: draft.includeHeader,
      columns: draft.columns.map((column) => ({ header: column.header.trim(), field: column.field })),
    };
    const done = {
      onSuccess: () => {
        toast.success(t("payroll.payouts.templates.saved"));
        setDraft(null);
      },
    };
    if (draft.id) update.mutate({ id: draft.id, changes: values }, done);
    else create.mutate(values, done);
  };

  const deleteTemplate = (template: BankFileTemplate) =>
    remove.mutate(template.id, {
      onSuccess: () => {
        toast.success(t("payroll.payouts.templates.deleted"));
        if (draft?.id === template.id) setDraft(null);
      },
      onError: (error) => toast.error(t("payroll.payouts.templates.deleteRefused"), { description: errorText(error) }),
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("payroll.payouts.templates.title")}</DialogTitle>
          <DialogDescription>{t("payroll.payouts.templates.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          {isLoading ? (
            <>
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </>
          ) : templates.length === 0 ? (
            <p className="rounded-md border border-dashed border-border px-3 py-3 text-sm text-muted-foreground">{t("payroll.payouts.templates.none")}</p>
          ) : (
            templates.map((template) => (
              <div
                key={template.id}
                className={`flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm ${
                  draft?.id === template.id ? "border-primary/40 bg-primary/5" : "border-border"
                }`}
              >
                <div className="min-w-0">
                  <p className="font-medium">{template.bank_name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {template.columns.map((column) => column.header).join(" · ")} — {delimiterLabel(template.delimiter)},{" "}
                    {template.include_header ? t("payroll.payouts.templates.withHeader") : t("payroll.payouts.templates.noHeader")}
                  </p>
                </div>
                {canEdit && (
                  <div className="flex shrink-0 gap-1">
                    <Button size="sm" variant="ghost" aria-label={t("common.edit")} title={t("common.edit")} onClick={() => edit(template)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive"
                      aria-label={t("common.delete")}
                      title={t("common.delete")}
                      disabled={remove.isPending}
                      onClick={() => deleteTemplate(template)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {canEdit && !draft && (
          <div className="mt-3">
            <Button size="sm" variant="outline" onClick={startNew}>
              <Plus className="h-4 w-4" />
              {t("payroll.payouts.templates.new")}
            </Button>
          </div>
        )}

        {canEdit && draft && (
          <form className="mt-4 space-y-4 rounded-lg border border-border bg-muted/30 p-4" onSubmit={submit}>
            <p className="text-sm font-semibold">{draft.id ? t("payroll.payouts.templates.editTitle") : t("payroll.payouts.templates.new")}</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="template-bank">{t("payroll.payouts.templates.bankName")}</Label>
                <Input
                  id="template-bank"
                  required
                  value={draft.bankName}
                  onChange={(event) => setDraft({ ...draft, bankName: event.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="template-delimiter">{t("payroll.payouts.templates.delimiter")}</Label>
                <Select id="template-delimiter" value={draft.delimiter} onChange={(event) => setDraft({ ...draft, delimiter: event.target.value })}>
                  {DELIMITERS.map((delimiter) => (
                    <option key={delimiter.value} value={delimiter.value}>
                      {t(delimiter.labelKey)}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={draft.includeHeader} onCheckedChange={(checked) => setDraft({ ...draft, includeHeader: checked === true })} />
              {t("payroll.payouts.templates.includeHeader")}
            </label>
            <div className="space-y-2">
              <p className="text-sm font-medium">{t("payroll.payouts.templates.columns")}</p>
              {draft.columns.map((column, index) => (
                <div key={index} className="flex items-center gap-2">
                  <Input
                    aria-label={t("payroll.payouts.templates.columnHeader")}
                    placeholder={t("payroll.payouts.templates.columnHeader")}
                    required
                    value={column.header}
                    onChange={(event) => setColumn(index, { header: event.target.value })}
                  />
                  <div className="w-56 shrink-0">
                    <Select
                      aria-label={t("payroll.payouts.templates.columnField")}
                      value={column.field}
                      onChange={(event) => setColumn(index, { field: event.target.value })}
                    >
                      {BANK_TEMPLATE_FIELDS.map((field) => (
                        <option key={field} value={field}>
                          {t(`payroll.payouts.templates.field.${field}` as TranslationKey)}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    aria-label={t("payroll.payouts.templates.removeColumn")}
                    title={t("payroll.payouts.templates.removeColumn")}
                    disabled={draft.columns.length <= 1}
                    onClick={() => setDraft({ ...draft, columns: draft.columns.filter((_, i) => i !== index) })}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setDraft({ ...draft, columns: [...draft.columns, { header: "", field: "employee_no" }] })}
              >
                <Plus className="h-4 w-4" />
                {t("payroll.payouts.templates.addColumn")}
              </Button>
            </div>
            {save.isError && (
              <p className="rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">{errorText(save.error)}</p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setDraft(null)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={!draft.bankName.trim() || save.isPending}>
                {save.isPending ? t("common.saving") : t("common.save")}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
