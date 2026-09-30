import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ScanLine } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label as FieldLabel } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { listWorkOrders } from "../production/api";
import { listShiftReports, SHIFT_REPORTS_QUERY_KEY } from "../production/shift/shiftApi";
import { useLabel } from "../production/shift/shiftText";
import { useShiftReferenceData } from "../production/shift/useShiftReferenceData";
import { createSession, SCAN_SESSIONS_QUERY_KEY } from "./scanApi";
import { S, SHIFT_STATUS } from "./scanText";

const today = () => new Date().toISOString().slice(0, 10);
const DONE = new Set(["submitted", "nothing_to_report", "draft"]);

export function ScanStart({ onCreated }: { onCreated: (sessionId: string) => void }) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const reference = useShiftReferenceData(true);
  const [date, setDate] = useState(() => params.get("date") || today());
  const [line, setLine] = useState(() => params.get("line") ?? "");
  const [shift, setShift] = useState(() => params.get("shift") ?? "");
  const [ofId, setOfId] = useState("");

  useEffect(() => {
    if (!line && reference.workCenters.length) setLine(reference.workCenters[0].id);
  }, [line, reference.workCenters]);
  useEffect(() => {
    if (!shift && reference.windows.length) setShift(reference.windows[0].shift);
  }, [shift, reference.windows]);

  const orders = useQuery({ queryKey: ["production", "shift", "orders"], queryFn: () => listWorkOrders(token) });
  const lineOrders = useMemo(
    () => (orders.data ?? []).filter((o) => o.status === "ongoing" && !o.is_regrind && o.work_center_id === line),
    [orders.data, line],
  );
  useEffect(() => {
    if (!lineOrders.some((o) => o.id === ofId)) setOfId(lineOrders[0]?.id ?? "");
  }, [lineOrders, ofId]);

  const reports = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "find", date, line],
    queryFn: () => listShiftReports(token, { report_date: date, work_center_id: line }),
    enabled: !!line,
  });
  const report = reports.data?.find((s) => s.shift.trim().toLowerCase() === shift.trim().toLowerCase());
  const validated = report?.status === "validated";
  const filled = report?.sections.filter((s) => DONE.has(s.status)).length ?? 0;
  // Until the lookup resolves we don't know whether this shift is validated, so neither the
  // "no report yet" line nor the start button may assume "no report".
  const lookupPending = !!line && (reports.isLoading || reports.isFetching);

  const create = useMutation({
    mutationFn: () => createSession(token, { work_center_id: line, report_date: date, shift, default_of_id: ofId || null }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: SCAN_SESSIONS_QUERY_KEY });
      onCreated(created.id);
    },
    onError: (error) => toast.error(label(S.failed), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Card>
      <CardContent className="space-y-4 py-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1">
            <FieldLabel htmlFor="scan-date">{label(S.date)}</FieldLabel>
            <Input id="scan-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="space-y-1">
            <FieldLabel htmlFor="scan-line">{label(S.line)}</FieldLabel>
            <Select id="scan-line" value={line} onChange={(e) => setLine(e.target.value)}>
              {reference.workCenters.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <FieldLabel htmlFor="scan-shift">{label(S.shift)}</FieldLabel>
            <Select id="scan-shift" value={shift} onChange={(e) => setShift(e.target.value)}>
              {reference.windows.map((w) => (
                <option key={w.shift} value={w.shift}>{`${w.shift} (${w.start_time.slice(0, 5)}–${w.end_time.slice(0, 5)})`}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <FieldLabel htmlFor="scan-of">{label(S.workOrder)}</FieldLabel>
            <Select id="scan-of" value={ofId} onChange={(e) => setOfId(e.target.value)} disabled={lineOrders.length === 0}>
              {lineOrders.length === 0 && <option value="">{label(S.noWorkOrder)}</option>}
              {lineOrders.map((o) => (
                <option key={o.id} value={o.id}>{o.reference}</option>
              ))}
            </Select>
          </div>
        </div>

        {report ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>{label(S.existingReport)}</span>
            <Badge variant={validated ? "destructive" : "primary"}>{label(SHIFT_STATUS[report.status])}</Badge>
            <span className="text-muted-foreground">{`${filled}/${report.sections.length} ${label(S.sectionsFilled)}`}</span>
          </div>
        ) : !lookupPending ? (
          <p className="text-sm text-muted-foreground">{label(S.noReport)}</p>
        ) : null}
        {validated && (
          <p className="flex items-start gap-2 rounded-md bg-destructive-soft px-3 py-2 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            {label(S.validatedBlock)}
          </p>
        )}

        <Button onClick={() => create.mutate()} disabled={!line || !shift || validated || lookupPending || create.isPending}>
          <ScanLine className="h-4 w-4" />
          {label(S.start)}
        </Button>
      </CardContent>
    </Card>
  );
}
