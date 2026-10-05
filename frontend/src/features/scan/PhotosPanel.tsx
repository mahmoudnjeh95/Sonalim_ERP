import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, ImagePlus, RotateCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Checkbox } from "../../components/ui/checkbox";
import { Select } from "../../components/ui/select";
import { useLabel } from "../production/shift/shiftText";
import { CameraDialog } from "./CameraDialog";
import { prepareImage, UPLOAD_BUDGETS } from "./imagePrep";
import { PageImage } from "./PageImage";
import { ReaderPicker } from "./ReaderPicker";
import {
  deletePage, getReaders, rereadPage, SCAN_READERS_QUERY_KEY, SCAN_SESSIONS_QUERY_KEY, scanProposalPrefix, scanSessionKey,
  setReader, uploadPages, type FormType, type Reader, type ScanPage, type SessionDetail,
} from "./scanApi";
import { FORM_LABELS, PAGE_STATUS, READER_LABELS, S, VERDICT_REASONS } from "./scanText";

const STATUS_VARIANT = { queued: "default", reading: "primary", read: "success", unrecognized: "warning", failed: "destructive" } as const;

export function PhotosPanel({
  session, disabled, included, onInclude,
}: { session: SessionDetail; disabled: boolean; included: ReadonlySet<string>; onInclude: (pageId: string, on: boolean) => void }) {
  const { session: auth } = useAuth();
  const token = auth!.token;
  const label = useLabel();
  const queryClient = useQueryClient();
  const pickRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const [preparing, setPreparing] = useState(0);
  const [cameraOpen, setCameraOpen] = useState(false);
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: scanSessionKey(session.id) });
    queryClient.invalidateQueries({ queryKey: scanProposalPrefix(session.id) });
  };
  const fail = (error: unknown, fallback = S.failed) =>
    toast.error(label(fallback), { description: error instanceof ApiError ? error.message : label(S.unsupported) });

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      // A budget a proxy refused (413) is not tried again for the rest of the batch.
      let budget = 0;
      for (const [index, file] of files.entries()) {
        setPreparing(index + 1);
        for (;;) {
          const prepared = await prepareImage(file, UPLOAD_BUDGETS[budget]);
          try {
            await uploadPages(token, session.id, [prepared]);
            break;
          } catch (error) {
            if (!(error instanceof ApiError && error.status === 413) || budget === UPLOAD_BUDGETS.length - 1) throw error;
            budget += 1;
          }
        }
        refresh();
      }
    },
    onSettled: () => setPreparing(0),
    onError: (error) => fail(error, S.uploadFailed),
  });
  const remove = useMutation({ mutationFn: (pageId: string) => deletePage(token, session.id, pageId), onSuccess: refresh, onError: (e) => fail(e) });
  const reread = useMutation({
    mutationFn: ({ pageId, hint }: { pageId: string; hint: FormType | null }) => rereadPage(token, session.id, pageId, hint),
    onSuccess: refresh,
    onError: (e) => fail(e),
  });
  const readers = useQuery({ queryKey: SCAN_READERS_QUERY_KEY, queryFn: () => getReaders(token) });
  const switchReader = useMutation({
    mutationFn: ({ reader, rereadAll }: { reader: Reader; rereadAll: boolean }) => setReader(token, session.id, reader, rereadAll),
    onSuccess: (_, { rereadAll }) => {
      refresh();
      queryClient.invalidateQueries({ queryKey: SCAN_SESSIONS_QUERY_KEY });
      if (rereadAll) toast.success(label(S.rereadAllDone));
    },
    onError: (e) => fail(e),
  });
  // Pages already read by the other engine: worth offering to read them again after a switch.
  const readByOther = session.pages.some((p) => p.read_by && p.read_by !== session.reader && p.status !== "queued");
  const pick = (files: FileList | null) => {
    if (files && files.length) upload.mutate(Array.from(files));
  };
  // Attempts no longer grow while the OCR service is down (the reader refunds them), so the
  // banner is keyed on a queued page still carrying the error from its last failed pickup.
  const serviceDown = session.pages.some((p) => p.status === "queued" && !!p.error);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>{label(S.photos)}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{label(S.photosHint)}</p>
          </div>
          {!disabled && (
            <div className="flex flex-wrap gap-2">
              <input ref={pickRef} type="file" accept="image/*" multiple hidden onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
              <input ref={cameraRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
              <Button variant="outline" onClick={() => setCameraOpen(true)} disabled={upload.isPending}>
                <Camera className="h-4 w-4" />
                {label(S.camera)}
              </Button>
              <Button onClick={() => pickRef.current?.click()} disabled={upload.isPending}>
                <ImagePlus className="h-4 w-4" />
                {preparing ? `${label(S.preparing)} ${preparing}…` : label(S.addPhotos)}
              </Button>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-start gap-3">
          <ReaderPicker
            value={session.reader}
            readers={readers.data}
            disabled={disabled || switchReader.isPending}
            onChange={(reader) => switchReader.mutate({ reader, rereadAll: false })}
          />
          {!disabled && session.pages.length > 0 && (
            <Button
              size="sm"
              variant={readByOther ? "default" : "outline"}
              disabled={switchReader.isPending}
              onClick={() => switchReader.mutate({ reader: session.reader, rereadAll: true })}
            >
              <RotateCw className="h-3.5 w-3.5" />
              {`${label(S.rereadAll)} (${label(READER_LABELS[session.reader])})`}
            </Button>
          )}
        </div>
        {serviceDown && <p className="text-sm text-warning">{label(S.serviceDown)}</p>}
        <CameraDialog
          open={cameraOpen}
          onOpenChange={setCameraOpen}
          onShots={(files) => upload.mutate(files)}
          onFallback={() => cameraRef.current?.click()}
        />
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {session.pages.map((page) => (
          <PageCard
            key={page.id}
            page={page}
            disabled={disabled}
            included={included.has(page.id)}
            onInclude={(on) => onInclude(page.id, on)}
            onRemove={() => remove.mutate(page.id)}
            onReread={(hint) => reread.mutate({ pageId: page.id, hint })}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function PageCard({
  page, disabled, included, onInclude, onRemove, onReread,
}: {
  page: ScanPage; disabled: boolean; included: boolean; onInclude: (on: boolean) => void; onRemove: () => void; onReread: (hint: FormType | null) => void;
}) {
  const label = useLabel();
  const [hint, setHint] = useState<FormType | "">(page.form_hint ?? "");
  const verdict = page.attribution?.verdict;
  const importable = page.form_type === "fabrication" || page.form_type === "conditionnement";
  return (
    <div className="space-y-2 rounded-lg border border-border p-2">
      <PageImage pageId={page.id} rotation={page.rotation} alt={label(S.photo)} className="h-40 w-full rounded-md object-contain bg-muted" />
      <div className="flex flex-wrap gap-1">
        <Badge variant={STATUS_VARIANT[page.status]}>{label(PAGE_STATUS[page.status])}</Badge>
        {page.form_type && <Badge variant="outline">{label(FORM_LABELS[page.form_type])}</Badge>}
        {page.read_by && page.status !== "queued" && (
          <Badge variant="outline" title={label(S.readBy)}>{label(READER_LABELS[page.read_by])}</Badge>
        )}
        {page.form_type === "bobines" && <Badge variant="warning">{label(S.notImportable)}</Badge>}
        {verdict === "unknown" && <Badge variant="warning">{label(S.unknownShift)}</Badge>}
      </div>
      {verdict === "other_shift" && (
        <div className="space-y-1 text-xs">
          <p className="text-destructive">
            {label(S.otherShift)} — {page.attribution!.reasons.map((r) => label(VERDICT_REASONS[r] ?? S.otherShift)).join(", ")}
          </p>
          {importable && !disabled && (
            <label className="flex items-center gap-2">
              <Checkbox checked={included} onCheckedChange={(on) => onInclude(on === true)} />
              {label(S.includeAnyway)}
            </label>
          )}
        </div>
      )}
      {!disabled && (page.status === "failed" || page.status === "unrecognized") && (
        <div className="flex gap-1">
          <Select className="h-8 text-xs" value={hint} onChange={(e) => setHint(e.target.value as FormType | "")}>
            <option value="">{label(S.chooseForm)}</option>
            {(["fabrication", "conditionnement", "bobines"] as const).map((form) => (
              <option key={form} value={form}>{label(FORM_LABELS[form])}</option>
            ))}
          </Select>
          <Button size="sm" variant="outline" onClick={() => onReread(hint || null)}>
            <RotateCw className="h-3.5 w-3.5" />
            {label(S.reread)}
          </Button>
        </div>
      )}
      {!disabled && (
        <Button size="sm" variant="ghost" className="w-full text-muted-foreground" onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
          {label(S.remove)}
        </Button>
      )}
    </div>
  );
}
