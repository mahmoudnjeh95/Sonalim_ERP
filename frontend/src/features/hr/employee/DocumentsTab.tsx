import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileStack, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import {
  createDocument,
  DOCUMENT_KINDS,
  hrKeys,
  listDocuments,
  updateDocument,
  type DocumentInput,
  type DocumentKind,
  type DocumentState,
  type EmployeeDocument,
  type EmployeeRecord,
} from "../api";
import { DOCUMENT_KIND_LABEL, DOCUMENT_STATE_LABEL, DOCUMENT_STATE_VARIANT } from "../employeeLabels";
import { emptyToNull, formatDate } from "../employeeFormat";
import { FormField } from "../FormField";
import { HrListTable } from "../HrListTable";

type StateFilter = "all" | DocumentState | "none";

export function DocumentsTab({ employee }: { employee: EmployeeRecord }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [state, setState] = useState<StateFilter>("all");
  const [dialog, setDialog] = useState<{ open: boolean; document: EmployeeDocument | null }>({ open: false, document: null });
  const { data: documents = [], isLoading } = useQuery({
    queryKey: hrKeys.documents(employee.id),
    queryFn: () => listDocuments(session!.token, employee.id),
  });
  const filters = useColumnFilters<EmployeeDocument>([
    { key: "title", kind: "text", getValue: (row) => row.title },
    { key: "file", kind: "text", getValue: (row) => row.file_ref },
  ]);
  const byState = state === "all" ? documents : documents.filter((row) => (state === "none" ? row.state === null : row.state === state));
  const rows = filters.apply(byState);
  const stateOptions: { value: StateFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    { value: "expired", label: t(DOCUMENT_STATE_LABEL.expired) },
    { value: "expiring", label: t(DOCUMENT_STATE_LABEL.expiring) },
    { value: "valid", label: t(DOCUMENT_STATE_LABEL.valid) },
    { value: "none", label: t("hr.documents.noExpiry") },
  ];

  const columns: ColumnDef<EmployeeDocument>[] = [
    { key: "kind", header: t("hr.documents.column.kind"), defaultWidth: 180, cell: (row) => t(DOCUMENT_KIND_LABEL[row.kind]), sortValue: (row) => row.kind },
    {
      key: "title",
      header: t("hr.documents.column.title"),
      defaultWidth: 180,
      cell: (row) => row.title ?? "—",
      filterCell: { type: "text", value: filters.text.title ?? "", onChange: (value) => filters.setTextValue("title", value), placeholder: t("hr.documents.column.title") },
    },
    { key: "issued", header: t("hr.documents.column.issued"), defaultWidth: 120, cell: (row) => formatDate(row.issued_on), sortValue: (row) => row.issued_on },
    { key: "expires", header: t("hr.documents.column.expires"), defaultWidth: 120, cell: (row) => formatDate(row.expires_on), sortValue: (row) => row.expires_on },
    {
      key: "state",
      header: t("hr.documents.column.state"),
      defaultWidth: 130,
      cell: (row) => (row.state ? <Badge variant={DOCUMENT_STATE_VARIANT[row.state]}>{t(DOCUMENT_STATE_LABEL[row.state])}</Badge> : t("hr.documents.noExpiry")),
    },
    {
      key: "file",
      header: t("hr.documents.column.file"),
      defaultWidth: 220,
      cell: (row) =>
        !row.file_ref ? (
          "—"
        ) : /^https?:\/\//.test(row.file_ref) ? (
          <a href={row.file_ref} target="_blank" rel="noreferrer" className="text-primary hover:underline">
            {row.file_ref}
          </a>
        ) : (
          <span className="font-mono text-xs">{row.file_ref}</span>
        ),
      filterCell: { type: "text", value: filters.text.file ?? "", onChange: (value) => filters.setTextValue("file", value), placeholder: t("hr.documents.column.file") },
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        hasPermission("hr.admin_employees") ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, document: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.file.tab.documents")}</CardTitle>
        {hasPermission("hr.manage_employees") && (
          <Button onClick={() => setDialog({ open: true, document: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.documents.add")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrListTable
          tableKey="hr.employee.documents"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          loading={isLoading}
          bordered={false}
          emptyIcon={<FileStack className="h-5 w-5" />}
          emptyTitle={t("hr.documents.empty.title")}
          emptyDescription={t("hr.documents.empty.description")}
          toolbar={<FilterTabs value={state} onChange={setState} options={stateOptions} />}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <DocumentDialog
        employeeId={employee.id}
        open={dialog.open}
        document={dialog.document}
        onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
      />
    </Card>
  );
}

interface DocumentForm {
  kind: DocumentKind;
  title: string;
  file_ref: string;
  issued_on: string;
  expires_on: string;
}

function toForm(document: EmployeeDocument | null): DocumentForm {
  return {
    kind: document?.kind ?? "id_card",
    title: document?.title ?? "",
    file_ref: document?.file_ref ?? "",
    issued_on: document?.issued_on ?? "",
    expires_on: document?.expires_on ?? "",
  };
}

function DocumentDialog({
  employeeId,
  open,
  document,
  onOpenChange,
}: {
  employeeId: string;
  open: boolean;
  document: EmployeeDocument | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<DocumentForm>(toForm(null));

  useEffect(() => {
    if (open) setForm(toForm(document));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, document?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: DocumentInput = {
        kind: form.kind,
        title: emptyToNull(form.title),
        file_ref: emptyToNull(form.file_ref),
        issued_on: emptyToNull(form.issued_on),
        expires_on: emptyToNull(form.expires_on),
      };
      return document ? updateDocument(session!.token, document.id, input) : createDocument(session!.token, employeeId, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.documents(employeeId) });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t("hr.documents.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.documents.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(document ? "hr.documents.dialog.editTitle" : "hr.documents.dialog.createTitle")}</DialogTitle>
          <DialogDescription>{t("hr.documents.dialog.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <FormField id="document-kind" label={t("hr.documents.column.kind")}>
              <Select id="document-kind" value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value as DocumentKind })}>
                {DOCUMENT_KINDS.map((value) => (
                  <option key={value} value={value}>
                    {t(DOCUMENT_KIND_LABEL[value])}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField id="document-title" label={t("hr.documents.column.title")}>
              <Input id="document-title" required={form.kind === "other"} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
            </FormField>
            <FormField id="document-issued" label={t("hr.documents.column.issued")}>
              <Input id="document-issued" type="date" value={form.issued_on} onChange={(event) => setForm({ ...form, issued_on: event.target.value })} />
            </FormField>
            <FormField id="document-expires" label={t("hr.documents.column.expires")}>
              <Input id="document-expires" type="date" value={form.expires_on} onChange={(event) => setForm({ ...form, expires_on: event.target.value })} />
            </FormField>
          </div>
          <FormField id="document-file" label={t("hr.documents.field.fileRef")}>
            <Input id="document-file" placeholder="\\srv-rh\dossiers\HRP-001\passeport.pdf" value={form.file_ref} onChange={(event) => setForm({ ...form, file_ref: event.target.value })} />
          </FormField>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
