import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { AppLoader } from "../../components/patterns/AppLoader";
import { useLabel } from "../production/shift/shiftText";
import { useShiftReferenceData } from "../production/shift/useShiftReferenceData";
import { PhotosPanel } from "./PhotosPanel";
import { ReviewPanel } from "./ReviewPanel";
import {
  discardSession, getSession, saveReview, SCAN_SESSIONS_QUERY_KEY, scanProposalPrefix, scanSessionKey,
  type ReviewState, type SessionDetail,
} from "./scanApi";
import { S, SESSION_STATUS, SHIFT_STATUS } from "./scanText";

const AUTOSAVE_MS = 1200;

export function ScanWorkspace({ sessionId, onBack }: { sessionId: string; onBack: () => void }) {
  const { session } = useAuth();
  const label = useLabel();
  const detail = useQuery({
    queryKey: scanSessionKey(sessionId),
    queryFn: () => getSession(session!.token, sessionId),
    refetchInterval: (query) =>
      query.state.data?.pages.some((p) => p.status === "queued" || p.status === "reading") ? 2000 : false,
  });
  if (detail.isLoading) return <AppLoader label={label(S.title)} />;
  if (!detail.data) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-muted-foreground">{label(S.failed)}</CardContent>
      </Card>
    );
  }
  return <Workspace session={detail.data} onBack={onBack} />;
}

function Workspace({ session, onBack }: { session: SessionDetail; onBack: () => void }) {
  const { session: auth } = useAuth();
  const token = auth!.token;
  const label = useLabel();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const reference = useShiftReferenceData(true);
  const [review, setReview] = useState<ReviewState>(() => session.review_state ?? {});
  const dirty = useRef(false);
  const latest = useRef({ token, sessionId: session.id, status: session.status, review });
  latest.current = { token, sessionId: session.id, status: session.status, review };

  const updateReview = useCallback((change: (current: ReviewState) => ReviewState) => {
    dirty.current = true;
    setReview(change);
  }, []);
  const autosave = useMutation({ mutationFn: (state: ReviewState) => saveReview(token, session.id, state) });
  useEffect(() => {
    if (!dirty.current || session.status !== "open") return;
    const timer = window.setTimeout(() => autosave.mutate(review), AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [review]);
  // Leaving the workspace before the debounce fires must not drop the last edit: flush it
  // fire-and-forget on unmount using the ref so this only reads on teardown, not every render.
  useEffect(() => () => {
    const current = latest.current;
    if (dirty.current && current.status === "open") {
      saveReview(current.token, current.sessionId, current.review).catch(() => {});
    }
  }, []);

  const included = new Set(review.include_pages ?? []);
  const setIncluded = async (pageId: string, on: boolean) => {
    const pages = new Set(review.include_pages ?? []);
    if (on) pages.add(pageId);
    else pages.delete(pageId);
    const next = { ...review, include_pages: [...pages] };
    setReview(next);
    await saveReview(token, session.id, next);  // the proposal reads it from the server
    queryClient.invalidateQueries({ queryKey: scanProposalPrefix(session.id) });
  };

  const discard = useMutation({
    mutationFn: () => discardSession(token, session.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SCAN_SESSIONS_QUERY_KEY });
      onBack();
    },
    onError: (error) => toast.error(label(S.failed), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const lineName = reference.workCenters.find((w) => w.id === session.work_center_id)?.name ?? "—";
  const validated = session.shift_report?.status === "validated";
  const open = session.status === "open";
  const shiftLink = `/production?tab=shift-report&line=${encodeURIComponent(session.work_center_id)}&date=${session.report_date}&shift=${encodeURIComponent(session.shift)}`;

  return (
    <div className="space-y-5">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 py-3">
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            {label(S.back)}
          </Button>
          <span className="font-medium">{`${lineName} · ${session.report_date} · ${session.shift}`}</span>
          {session.window && <span className="text-sm text-muted-foreground">{`${session.window.start}–${session.window.end}`}</span>}
          <Badge variant={open ? "warning" : "default"}>{label(SESSION_STATUS[session.status])}</Badge>
          {session.shift_report && <Badge variant={validated ? "destructive" : "primary"}>{label(SHIFT_STATUS[session.shift_report.status])}</Badge>}
          <div className="ml-auto flex gap-2">
            {session.shift_report_id && (
              <Button variant="outline" size="sm" onClick={() => navigate(shiftLink)}>{label(S.openShift)}</Button>
            )}
            {open && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => window.confirm(label(S.discardConfirm)) && discard.mutate()}
                disabled={discard.isPending}
              >
                <XCircle className="h-4 w-4" />
                {label(S.discard)}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {validated && open && (
        <p className="flex items-start gap-2 rounded-md bg-destructive-soft px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {label(S.validatedBlock)}
        </p>
      )}
      {session.status === "applied" && (
        <p className="flex items-center gap-2 rounded-md bg-success-soft px-3 py-2 text-sm text-success">
          <CheckCircle2 className="h-4 w-4" />
          {label(S.appliedCard)}
        </p>
      )}
      {session.status === "discarded" && <p className="text-sm text-muted-foreground">{label(S.discardedCard)}</p>}

      <PhotosPanel session={session} disabled={!open || validated} included={included} onInclude={setIncluded} />
      {open && !validated && session.pages.some((p) => p.status === "read") && (
        <ReviewPanel session={session} review={review} updateReview={updateReview} />
      )}
    </div>
  );
}
