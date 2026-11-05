import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Paperclip, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { addAttachment, deleteAttachment, downloadAttachment, listAttachments, type AttachmentEntity } from "./stockDocumentsApi";

function readBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function DocumentAttachments({ entityType, entityId, canManage }: { entityType: AttachmentEntity; entityId: string; canManage: boolean }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const queryKey = ["warehouse", "attachments", entityType, entityId];
  const { data: files = [] } = useQuery({ queryKey, queryFn: () => listAttachments(token, entityType, entityId) });
  const fail = (error: unknown) => toast.error(t("attachment.error"), { description: error instanceof ApiError ? error.message : undefined });

  const addMutation = useMutation({
    mutationFn: async (file: File) =>
      addAttachment(token, entityType, entityId, { filename: file.name, content_type: file.type || "application/octet-stream", content_base64: await readBase64(file) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
    onError: fail,
  });
  const deleteMutation = useMutation({
    mutationFn: (attachmentId: string) => deleteAttachment(token, entityType, entityId, attachmentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
    onError: fail,
  });
  const download = async (attachmentId: string, filename: string) => {
    try {
      const url = URL.createObjectURL(await downloadAttachment(token, entityType, entityId, attachmentId));
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      fail(error);
    }
  };

  return (
    <div className="space-y-1.5 rounded-md border p-3 print:hidden">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <Paperclip className="h-3.5 w-3.5" />
          {t("attachment.title")}
        </p>
        {canManage && (
          <label className="cursor-pointer text-sm text-primary hover:underline">
            {t("attachment.add")}
            <input
              type="file"
              className="hidden"
              disabled={addMutation.isPending}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) addMutation.mutate(file);
                event.target.value = "";
              }}
            />
          </label>
        )}
      </div>
      {files.length === 0 && <p className="text-sm text-muted-foreground">{t("attachment.empty")}</p>}
      {files.map((file) => (
        <div key={file.id} className="flex items-center justify-between gap-2 text-sm">
          <span className="truncate">{file.filename}</span>
          <div className="flex shrink-0 gap-1">
            <Button size="sm" variant="ghost" aria-label={t("attachment.download")} onClick={() => download(file.id, file.filename)}>
              <Download className="h-3.5 w-3.5" />
            </Button>
            {canManage && (
              <Button size="sm" variant="ghost" aria-label={t("attachment.delete")} disabled={deleteMutation.isPending} onClick={() => {
                if (window.confirm(t("attachment.deleteConfirm").replace("{name}", file.filename))) deleteMutation.mutate(file.id);
              }}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
