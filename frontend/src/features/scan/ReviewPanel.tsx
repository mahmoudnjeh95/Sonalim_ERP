import { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/utils";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label as FieldLabel } from "../../components/ui/label";
import { Skeleton } from "../../components/ui/skeleton";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { SECTIONS, type PartDef, type SectionDef } from "../production/shift/sectionConfig";
import { Part } from "../production/shift/SectionCard";
import { DECOR_CLASS, type CellDecor, type GridRow, type OptionMap } from "../production/shift/ShiftGrid";
import type { Row, SectionKey } from "../production/shift/shiftApi";
import { useLabel, type Label } from "../production/shift/shiftText";
import { useShiftReferenceData } from "../production/shift/useShiftReferenceData";
import { ApplyDialog } from "./ApplyDialog";
import { PhotoViewer } from "./PhotoViewer";
import {
  APPLY_ORDER, fieldPath, isBlocking, isEmpty, mergeProposal, missingRequired, openDoubts, rowRef, sameValue,
  sectionNotice, sectionsToWrite, valuesByPath, valuesFromProposal,
} from "./reviewModel";
import {
  getProposal, scanProposalPrefix, type Choice, type FlagEntry, type ReviewState, type SessionDetail, type SetAsideEntry,
  type ShiftSectionState,
} from "./scanApi";
import { REASONS, S, SECTION_STATUS } from "./scanText";

// Columns pointing at saved rows of the shift (a run, a packing row) cannot be chosen before the scan is saved.
const HIDDEN_OPTIONS = new Set(["runs", "packingRows"]);
const HEADER_FIELDS: [string, Label][] = [
  ["team", S.team], ["conducteur", S.conducteur], ["agent_fabrication", S.agent], ["machiniste", S.machiniste], ["aide_machiniste", S.aide],
];

export function ReviewPanel({
  session, review, updateReview,
}: { session: SessionDetail; review: ReviewState; updateReview: (change: (current: ReviewState) => ReviewState) => void }) {
  const { session: auth } = useAuth();
  const label = useLabel();
  const reference = useShiftReferenceData(true);
  const signature = `${session.pages.filter((p) => p.status === "read").map((p) => p.id).join(",")}|${(review.include_pages ?? []).join(",")}`;
  const query = useQuery({
    queryKey: [...scanProposalPrefix(session.id), signature],
    queryFn: () => getProposal(auth!.token, session.id),
    placeholderData: keepPreviousData,
  });
  const [active, setActive] = useState<string | null>(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const data = query.data;

  // A new reading refreshes the sections nobody touched; the first one starts (or restores) the working copy.
  const firstReading = useRef(true);
  useEffect(() => {
    if (!data) return;
    if (!firstReading.current) toast.info(label(S.newReading));
    firstReading.current = false;
    updateReview((current) => ({
      ...current,
      values: current.values ? mergeProposal(current.values, data.proposal, new Set(current.touched ?? [])) : valuesFromProposal(data.proposal),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const options = useMemo<OptionMap>(() => {
    const built = reference.buildOptions(undefined, session.work_center_id);
    // Before the scan is saved there are no saved runs or packed rows to narrow these lists by.
    return { ...built, shiftOrders: built.orders, packedProducts: built.finishedProducts };
  }, [reference.buildOptions, session.work_center_id]);
  const proposed = useMemo(() => (data ? valuesByPath(valuesFromProposal(data.proposal)) : new Map<string, unknown>()), [data]);

  if (!data || !review.values) return <Skeleton className="h-64 w-full" />;
  const { proposal, shift } = data;
  const values = review.values;
  const choices = review.choices ?? {};
  const confirmed = new Set(review.confirmed ?? []);
  const writing = sectionsToWrite(values, choices, shift);
  const doubts = openDoubts(proposal, values, confirmed, writing);
  const missing = missingRequired(values, SECTIONS, writing);

  const flagsAt = (path: string): FlagEntry[] => proposal.flags[path] ?? [];
  const isDoubt = (path: string, value: unknown) => flagsAt(path).length > 0 && !confirmed.has(path) && sameValue(value, proposed.get(path));
  const reasons = (path: string) =>
    flagsAt(path).map((f) => `${label(REASONS[f.reason] ?? S.toCheck)}${f.detail ? ` (${f.detail})` : ""}`).join(" · ");

  const setPart = (key: SectionKey, part: string, value: GridRow[] | Row) =>
    updateReview((current) => ({
      ...current,
      touched: [...new Set([...(current.touched ?? []), key])],
      values: { ...current.values!, sections: { ...current.values!.sections, [key]: { ...current.values!.sections[key], [part]: value } } },
    }));
  const setHeader = (field: string, value: string) =>
    updateReview((current) => ({ ...current, values: { ...current.values!, header: { ...current.values!.header, [field]: value || null } } }));
  const setChoice = (key: SectionKey, choice: Choice) => updateReview((current) => ({ ...current, choices: { ...current.choices, [key]: choice } }));
  const confirm = (path: string) => updateReview((current) => ({ ...current, confirmed: [...new Set([...(current.confirmed ?? []), path])] }));

  const activeSource = active ? proposal.sources[active]?.[0] : undefined;
  const activePage = session.pages.find((p) => p.id === activeSource?.page_id);
  const defs = SECTIONS.filter((def) => APPLY_ORDER.includes(def.key) && values.sections[def.key]);
  const excluded = Object.entries(proposal.pages).filter(([, p]) => p.importable && !p.included).length;

  return (
    <div className="space-y-4">
      <div className="sticky top-24 z-10 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-background/95 px-4 py-3 shadow-soft backdrop-blur">
        <div>
          <h3 className="font-semibold">{label(S.review)}</h3>
          <p className="text-xs text-muted-foreground">{label(S.reviewHint)}</p>
        </div>
        <Badge variant="warning">{`${doubts.length} ${label(S.toCheck)}`}</Badge>
        <Badge variant={missing.length ? "destructive" : "default"}>{`${missing.length} ${label(S.required)}`}</Badge>
        {excluded > 0 && <Badge variant="outline">{`${excluded} ${label(S.otherShift)}`}</Badge>}
        <Button className="ml-auto" onClick={() => setApplyOpen(true)} disabled={writing.length === 0}>
          <Save className="h-4 w-4" />
          {label(S.applyButton)}
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{label(S.header)}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {HEADER_FIELDS.map(([field, fieldLabel]) => {
                const path = fieldPath("header", "-", "-", field);
                const doubt = isDoubt(path, values.header[field]);
                return (
                  <div key={field} className={cn("space-y-1 rounded-md p-1", doubt && DECOR_CLASS.doubt)} title={doubt ? reasons(path) : undefined}>
                    <FieldLabel htmlFor={`scan-header-${field}`} className="text-xs text-muted-foreground">{label(fieldLabel)}</FieldLabel>
                    <Input
                      id={`scan-header-${field}`}
                      value={values.header[field] ?? ""}
                      onFocus={() => setActive(path)}
                      onChange={(e) => setHeader(field, e.target.value)}
                    />
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {defs.map((def) => (
            <SectionReview
              key={def.key}
              def={def}
              parts={values.sections[def.key]!}
              existing={shift?.sections[def.key]}
              choice={choices[def.key]}
              notices={flagsAt(sectionNotice(def.key))}
              setAside={(proposal.set_aside[def.key] ?? []).filter(
                (entry) => !((values.sections[def.key]?.[entry.part] as GridRow[] | undefined) ?? []).some((row) => row._scan_ref === entry.row._scan_ref),
              )}
              options={options}
              onChoice={(choice) => setChoice(def.key, choice)}
              onPart={(part, value) => setPart(def.key, part, value)}
              decorate={(part, row, key) => {
                const column = part.columns.find((c) => c.key === key);
                const path = fieldPath(def.key, part.payloadKey, part.shape === "rows" ? rowRef(row) : "-", key);
                if (column?.required && isEmpty(row[key])) {
                  return { tone: "required", title: label(isBlocking(def.key, part.payloadKey, key) ? S.requiredBlocking : S.requiredLater) };
                }
                if (isDoubt(path, row[key])) return { tone: "doubt", title: reasons(path) };
                return undefined;
              }}
              onFocus={(part, row, key) => setActive(fieldPath(def.key, part.payloadKey, part.shape === "rows" ? rowRef(row) : "-", key))}
            />
          ))}
        </div>

        <div className="lg:sticky lg:top-[184px] lg:self-start">
          <PhotoViewer
            page={activePage}
            source={activeSource}
            flagged={!!active && flagsAt(active).length > 0 && !confirmed.has(active)}
            onConfirm={() => active && confirm(active)}
          />
        </div>
      </div>

      <ApplyDialog
        open={applyOpen}
        onOpenChange={setApplyOpen}
        session={session}
        values={values}
        shift={shift}
        writing={writing}
        missing={missing}
        doubts={doubts.length}
      />
    </div>
  );
}

function SectionReview({
  def, parts, existing, choice, notices, setAside, options, onChoice, onPart, decorate, onFocus,
}: {
  def: SectionDef;
  parts: Record<string, GridRow[] | Row>;
  existing: ShiftSectionState | undefined;
  choice: Choice | undefined;
  notices: FlagEntry[];
  setAside: SetAsideEntry[];
  options: OptionMap;
  onChoice: (choice: Choice) => void;
  onPart: (part: string, value: GridRow[] | Row) => void;
  decorate: (part: PartDef, row: Row, key: string) => CellDecor | undefined;
  onFocus: (part: PartDef, row: Row, key: string) => void;
}) {
  const label = useLabel();
  const Icon = def.icon;
  const filled = (existing?.rows ?? 0) > 0;
  const keeping = filled && choice !== "replace";
  return (
    <Card className={cn(keeping && "opacity-70")}>
      <CardContent className="space-y-3 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Icon className="h-4 w-4 text-primary" />
          <h3 className="font-medium">{label(def.title)}</h3>
          {filled && (
            <>
              <Badge variant="warning">{`${label(S.existingRows)} ${existing!.rows} · ${label(SECTION_STATUS[existing!.status])}`}</Badge>
              <FilterTabs
                value={keeping ? "keep" : "replace"}
                onChange={(value) => onChoice(value as Choice)}
                options={[
                  { value: "keep", label: label(S.keep) },
                  { value: "replace", label: label(S.replace) },
                ]}
              />
            </>
          )}
        </div>
        {notices.map((notice) => (
          <p key={notice.reason} className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">{label(REASONS[notice.reason] ?? S.toCheck)}</p>
        ))}
        {keeping ? (
          <p className="text-sm text-muted-foreground">{label(S.keptHint)}</p>
        ) : (
          def.parts
            .filter((part) => parts[part.payloadKey] !== undefined)
            .map((part) => {
              const shown = { ...part, columns: part.columns.filter((c) => !HIDDEN_OPTIONS.has(c.options ?? "")) };
              return (
                <Part
                  key={part.payloadKey}
                  part={shown}
                  sectionKey={`scan-${def.key}`}
                  value={parts[part.payloadKey]}
                  onChange={(value) => onPart(part.payloadKey, value)}
                  options={options}
                  disabled={false}
                  decorate={(row, key) => decorate(shown, row, key)}
                  onCellFocus={(row, key) => onFocus(shown, row, key)}
                />
              );
            })
        )}
        {!keeping && setAside.length > 0 && (
          <div className="space-y-2 rounded-md border border-dashed border-warning/60 p-3">
            <p className="text-xs font-medium text-warning">{label(S.setAsideTitle)}</p>
            {setAside.map((entry) => (
              <div key={String(entry.row._scan_ref)} className="flex flex-wrap items-center gap-2 text-sm">
                <span>{`${entry.row.quantity ?? "—"} kg · ${entry.row.lot_number ?? ""} · ${entry.row.note ?? ""}`}</span>
                <span className="text-xs text-muted-foreground">{label(REASONS[entry.reason] ?? S.toCheck)}</span>
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  onClick={() => {
                    const rows = (parts[entry.part] as GridRow[] | undefined) ?? [];
                    onPart(entry.part, [...rows, { ...entry.row, _key: String(entry.row._scan_ref) }]);
                  }}
                >
                  {label(S.addBack)}
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
