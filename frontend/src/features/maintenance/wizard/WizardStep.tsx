import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Ban,
  Camera,
  CheckCircle2,
  ChevronDown,
  Gauge,
  History,
  ImageOff,
  RotateCcw,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "../../../components/ui/badge";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { fetchViewImageBlob, type JobCheck, type Outcome, type Person } from "../api";
import { CHECK_ACTION_ICON, CHECK_ACTION_LABEL_KEY, OUTCOME_LABEL_KEY } from "../labels";
import { PinnedPhoto, type Pin } from "../map/PinnedPhoto";
import { useAuthedImage } from "../useAuthedImage";
import { CheckHistory } from "../jobs/CheckHistory";
import { EntryPhoto } from "../jobs/EntryPhoto";
import { formatDay, formatMeasure, formatTime, latestRejection } from "../jobs/jobFormat";
import { PhotoProofInput } from "./PhotoProofInput";
import { StepTimer } from "./StepTimer";
import { currentEntry, formatSpan, needsMeasure, timerPhase, type DraftField, type StepDraft, type TimerState } from "./wizardModel";

export const fieldId = (field: DraftField) => `wizard-field-${field}`;

const OUTCOME_STYLE: Record<Outcome, { icon: LucideIcon; idle: string; selected: string }> = {
  ok: {
    icon: CheckCircle2,
    idle: "border-success/30 bg-success-soft text-success hover:border-success/60",
    selected: "border-success bg-success text-success-foreground shadow-raised",
  },
  issue: {
    icon: AlertTriangle,
    idle: "border-destructive/30 bg-destructive-soft text-destructive hover:border-destructive/60",
    selected: "border-destructive bg-destructive text-destructive-foreground shadow-raised",
  },
  not_done: {
    icon: Ban,
    idle: "border-border bg-muted text-muted-foreground hover:border-foreground/30",
    selected: "border-foreground/80 bg-foreground/80 text-background shadow-raised",
  },
};

const OUTCOME_PILL: Record<Outcome, string> = {
  ok: "bg-success text-success-foreground",
  issue: "bg-destructive text-destructive-foreground",
  not_done: "bg-foreground/80 text-background",
};

const NOTE_PLACEHOLDER: Record<Outcome, TranslationKey> = {
  ok: "maintenance.wizard.note.placeholder.ok",
  issue: "maintenance.wizard.note.placeholder.issue",
  not_done: "maintenance.wizard.note.placeholder.not_done",
};

function FieldLabel({ htmlFor, children, required }: { htmlFor?: string; children: ReactNode; required?: boolean }) {
  const { t } = useI18n();
  return (
    <label htmlFor={htmlFor} className="flex items-baseline gap-2 text-sm font-medium">
      {children}
      {required !== undefined && (
        <span className={cn("text-xs font-normal", required ? "text-destructive" : "text-muted-foreground")}>
          {required ? t("maintenance.wizard.required") : t("maintenance.wizard.optional")}
        </span>
      )}
    </label>
  );
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p className="text-sm font-medium text-destructive" role="alert">
      {message}
    </p>
  );
}

/** The machine photo with the point's pin pulsing, or — for an ad-hoc task with no photo — a plain card (Review Focus 4). */
function StepPhoto({
  check,
  equipmentName,
  pins,
  viewsReady,
  viewVersion,
  onPinClick,
}: {
  check: JobCheck;
  equipmentName: string;
  pins: Pin[];
  viewsReady: boolean;
  viewVersion: string | null;
  onPinClick: (checkId: string) => void;
}) {
  const { t } = useI18n();
  const hasPin = check.view_id !== null && check.x_pct !== null && check.y_pct !== null;
  const { url, isError } = useAuthedImage(fetchViewImageBlob, hasPin && viewsReady ? check.view_id : null, viewVersion);
  const ActionIcon = CHECK_ACTION_ICON[check.action];

  if (!hasPin || isError) {
    return (
      <div className="flex items-center gap-4 rounded-xl border border-border bg-gradient-to-br from-primary/[0.06] to-accent/[0.08] p-4">
        <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-raised">
          <ActionIcon className="h-8 w-8" />
        </span>
        <div className="min-w-0 text-sm">
          <p className="font-medium">{equipmentName}</p>
          <p className="flex items-center gap-1.5 text-muted-foreground">
            {isError && <ImageOff className="h-3.5 w-3.5 shrink-0" />}
            {isError ? t("maintenance.jobs.views.photoError") : t("maintenance.wizard.noPhoto")}
          </p>
        </div>
      </div>
    );
  }
  if (!url) return <Skeleton className="aspect-[4/3] w-full rounded-xl" />;
  return <PinnedPhoto src={url} pins={pins} onPinClick={onPinClick} className="rounded-xl shadow-soft" />;
}

/** The entry recorded on this point's current attempt, read-only, with "Refaire". */
function RecordedEntry({ check, onRedo, disabled }: { check: JobCheck; onRedo: () => void; disabled: boolean }) {
  const { t } = useI18n();
  const entry = currentEntry(check);
  const earlier = check.entries.filter((item) => item.id !== entry?.id);
  const [showHistory, setShowHistory] = useState(false);
  if (!entry) return null;
  const OutcomeIcon = OUTCOME_STYLE[entry.outcome].icon;

  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-xl border border-border bg-background shadow-soft">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <p className="text-sm font-semibold">{t("maintenance.wizard.recorded")}</p>
          <span className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold", OUTCOME_PILL[entry.outcome])}>
            <OutcomeIcon className="h-4 w-4" />
            {t(OUTCOME_LABEL_KEY[entry.outcome])}
          </span>
        </div>
        <div className="flex gap-3 p-4">
          <dl className="min-w-0 flex-1 space-y-2 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">{t("maintenance.wizard.performer")}</dt>
              <dd className="font-medium">{entry.performer_name}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{t("maintenance.wizard.duration")}</dt>
              <dd className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-lg font-semibold tabular-nums">{formatSpan(entry.duration_seconds)}</span>
                <span className="text-xs text-muted-foreground">
                  {formatDay(entry.started_at)} · {formatTime(entry.started_at)} – {formatTime(entry.finished_at)}
                </span>
                {entry.duration_source === "manual" && <Badge variant="outline">{t("maintenance.jobs.entry.manual")}</Badge>}
              </dd>
            </div>
            {entry.measured_value !== null && (
              <div>
                <dt className="text-xs text-muted-foreground">{t("maintenance.wizard.measure")}</dt>
                <dd className="text-lg font-semibold tabular-nums">{formatMeasure(entry.measured_value, check.measure_unit)}</dd>
              </div>
            )}
            {entry.note && (
              <div>
                <dt className="text-xs text-muted-foreground">{t("maintenance.wizard.note")}</dt>
                <dd className="whitespace-pre-wrap break-words">{entry.note}</dd>
              </div>
            )}
          </dl>
          {entry.has_photo && <EntryPhoto entryId={entry.id} className="h-24 w-24 rounded-lg" />}
        </div>
      </div>

      {check.state === "done" && (
        <button
          type="button"
          onClick={onRedo}
          disabled={disabled}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-border bg-background text-base font-semibold shadow-soft transition-colors hover:border-primary/30 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          <RotateCcw className="h-5 w-5" />
          {t("maintenance.wizard.redo")}
        </button>
      )}

      {earlier.length > 0 && (
        <div className="rounded-xl border border-border bg-background">
          <button
            type="button"
            onClick={() => setShowHistory((value) => !value)}
            aria-expanded={showHistory}
            className="flex min-h-11 w-full items-center justify-between gap-2 px-4 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="flex items-center gap-2">
              <History className="h-4 w-4 text-muted-foreground" />
              {t("maintenance.wizard.history")}
            </span>
            <ChevronDown className={cn("h-4 w-4 transition-transform", showHistory && "rotate-180")} />
          </button>
          {showHistory && (
            <div className="border-t border-border p-4">
              <CheckHistory check={check} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export interface WizardStepProps {
  check: JobCheck;
  /** Shown on the plain card of a point that has no machine photo. */
  equipmentName: string;
  /** The point's number on the job (its row in the job's checks table), as on the pins. */
  number: number;
  pins: Pin[];
  viewsReady: boolean;
  viewVersion: string | null;
  onPinClick: (checkId: string) => void;
  draft: StepDraft;
  performerId: string;
  performerOptions: Person[];
  performersLoading: boolean;
  /** The team list is the default; this widens the select to every active employee. */
  showEveryone: boolean;
  canShowEveryone: boolean;
  onShowEveryoneChange: (value: boolean) => void;
  timer: TimerState | null;
  /** Translated, shown only once a save was attempted. */
  errors: Partial<Record<DraftField, string>>;
  saving: boolean;
  onDraftChange: (patch: Partial<StepDraft>) => void;
  onResetTimer: () => void;
  onRedo: () => void;
  onCancelRedo: () => void;
}

/**
 * One point of the guided check: where it is (photo + pin), what to do, then — while it is to
 * record — who does it, the timer, and once Terminé the outcome, measure, note and photo proof.
 * A point already recorded shows its entry read-only with "Refaire".
 */
export function WizardStep(props: WizardStepProps) {
  const { check, number, draft, timer, errors, saving } = props;
  const { t } = useI18n();
  const ActionIcon = CHECK_ACTION_ICON[check.action];
  const recording = check.state === "pending" || draft.redo;
  const phase = timerPhase(draft, timer);
  const showResult = phase === "finished" || phase === "manual";
  const rejection = latestRejection(check);
  const showRejection = rejection !== null && rejection.attempt < check.attempt;
  const measureRequired = needsMeasure(check) && draft.outcome !== "not_done";
  const noteRequired = draft.outcome === "issue" || draft.outcome === "not_done";
  const photoRequired = check.requires_photo && draft.outcome !== "not_done";
  const resultRef = useRef<HTMLDivElement>(null);
  const previousPhase = useRef(phase);

  // Terminé reveals the outcome block below the fold on a phone: bring it up.
  useEffect(() => {
    if (previousPhase.current === "running" && phase === "finished") {
      window.setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
    }
    previousPhase.current = phase;
  }, [phase]);

  return (
    <div className="space-y-4">
      {showRejection && (
        <div className="flex gap-3 rounded-xl border border-destructive/30 bg-destructive-soft p-4" role="note">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
          <div className="min-w-0 space-y-1 text-sm">
            <p className="font-semibold text-destructive">
              {t("maintenance.wizard.rejected").replace("{name}", rejection.reviewer_name)}
            </p>
            {rejection.reason && <p className="whitespace-pre-wrap break-words text-foreground">« {rejection.reason} »</p>}
            {check.state === "pending" && <p className="text-muted-foreground">{t("maintenance.wizard.rejectedHint")}</p>}
          </div>
        </div>
      )}

      <StepPhoto check={check} equipmentName={props.equipmentName} pins={props.pins} viewsReady={props.viewsReady} viewVersion={props.viewVersion} onPinClick={props.onPinClick} />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-7 min-w-7 items-center justify-center rounded-full bg-accent px-2 text-sm font-bold text-accent-foreground">
            {number}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 text-sm font-semibold text-primary">
            <ActionIcon className="h-4 w-4" />
            {t(CHECK_ACTION_LABEL_KEY[check.action])}
          </span>
          {check.requires_photo && (
            <Badge variant="outline">
              <Camera className="h-3 w-3" />
              {t("maintenance.jobs.photo.required")}
            </Badge>
          )}
          {needsMeasure(check) && (
            <Badge variant="outline">
              <Gauge className="h-3 w-3" />
              {check.measure_unit
                ? t("maintenance.wizard.measureIn").replace("{unit}", check.measure_unit)
                : t("maintenance.wizard.measureRequired")}
            </Badge>
          )}
        </div>
        <h2 className="break-words text-xl font-semibold leading-snug tracking-tight">{check.label}</h2>
        {check.instructions && (
          <p className="whitespace-pre-wrap break-words rounded-lg bg-background px-3 py-2 text-[15px] leading-relaxed text-foreground shadow-soft ring-1 ring-border">
            {check.instructions}
          </p>
        )}
      </div>

      {!recording ? (
        <RecordedEntry check={check} onRedo={props.onRedo} disabled={saving} />
      ) : (
        <div className="space-y-4">
          {draft.redo && (
            <div className="flex flex-col gap-2 rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <p>{t("maintenance.wizard.redoHint")}</p>
              <button
                type="button"
                onClick={props.onCancelRedo}
                disabled={saving}
                className="inline-flex min-h-11 shrink-0 items-center gap-1.5 self-start rounded-md px-2 font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:self-auto"
              >
                <Undo2 className="h-4 w-4" />
                {t("maintenance.wizard.redoCancel")}
              </button>
            </div>
          )}

          <div id={fieldId("performer")} className="space-y-2 scroll-mt-4">
            <FieldLabel htmlFor="wizard-performer">{t("maintenance.wizard.performer")}</FieldLabel>
            {props.performersLoading ? (
              <Skeleton className="h-12 w-full" />
            ) : (
              <Select
                id="wizard-performer"
                value={props.performerId}
                disabled={saving}
                onChange={(event) => props.onDraftChange({ performerId: event.target.value })}
                className={cn("h-12 text-base sm:h-12 sm:text-base", errors.performer && "border-destructive")}
              >
                <option value="">{t("maintenance.wizard.performer.placeholder")}</option>
                {props.performerOptions.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </Select>
            )}
            <FieldError message={errors.performer} />
            {props.canShowEveryone && (
              <button
                type="button"
                onClick={() => props.onShowEveryoneChange(!props.showEveryone)}
                className="inline-flex min-h-11 items-center rounded-md px-1 text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {props.showEveryone ? t("maintenance.wizard.performer.showTeam") : t("maintenance.wizard.performer.showEveryone")}
              </button>
            )}
          </div>

          <div id={fieldId("timing")} className="scroll-mt-4">
            <StepTimer
              phase={phase}
              timer={timer}
              manualMinutes={draft.manualMinutes}
              onReset={props.onResetTimer}
              onManualChange={(manual) => props.onDraftChange({ manual })}
              onManualMinutesChange={(manualMinutes) => props.onDraftChange({ manualMinutes })}
              error={errors.timing}
              disabled={saving}
            />
          </div>

          <AnimatePresence initial={false}>
            {showResult && (
              <motion.div
                ref={resultRef}
                key="result"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 12 }}
                transition={{ duration: 0.2 }}
                className="scroll-mt-4 space-y-5"
              >
                <div id={fieldId("outcome")} className="space-y-2 scroll-mt-4">
                  <FieldLabel>{t("maintenance.wizard.outcome")}</FieldLabel>
                  <div role="radiogroup" aria-label={t("maintenance.wizard.outcome")} className="grid grid-cols-3 gap-2">
                    {(Object.keys(OUTCOME_STYLE) as Outcome[]).map((outcome) => {
                      const style = OUTCOME_STYLE[outcome];
                      const Icon = style.icon;
                      const selected = draft.outcome === outcome;
                      return (
                        <motion.button
                          key={outcome}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          disabled={saving}
                          whileTap={{ scale: 0.96 }}
                          onClick={() => props.onDraftChange({ outcome })}
                          className={cn(
                            "flex h-20 flex-col items-center justify-center gap-1.5 rounded-xl border-2 px-1 text-center text-sm font-semibold leading-tight transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50 sm:text-base",
                            selected ? style.selected : style.idle,
                            errors.outcome && !draft.outcome && "border-destructive/60",
                          )}
                        >
                          <Icon className="h-6 w-6" />
                          {t(OUTCOME_LABEL_KEY[outcome])}
                        </motion.button>
                      );
                    })}
                  </div>
                  <FieldError message={errors.outcome} />
                </div>

                {needsMeasure(check) && (
                  <div id={fieldId("measure")} className="space-y-2 scroll-mt-4">
                    <FieldLabel htmlFor="wizard-measure" required={measureRequired}>
                      {t("maintenance.wizard.measure")}
                    </FieldLabel>
                    <div
                      className={cn(
                        "flex h-14 items-stretch overflow-hidden rounded-lg border bg-background shadow-sm focus-within:ring-2 focus-within:ring-ring",
                        errors.measure ? "border-destructive" : "border-border",
                      )}
                    >
                      <input
                        id="wizard-measure"
                        type="text"
                        inputMode="decimal"
                        autoComplete="off"
                        value={draft.measure}
                        disabled={saving}
                        onChange={(event) => props.onDraftChange({ measure: event.target.value })}
                        placeholder="0"
                        aria-invalid={errors.measure ? true : undefined}
                        className="min-w-0 flex-1 bg-transparent px-4 text-2xl font-semibold tabular-nums focus-visible:outline-none"
                      />
                      {check.measure_unit && (
                        <span className="flex shrink-0 items-center border-l border-border bg-muted px-4 text-base font-medium text-muted-foreground">
                          {check.measure_unit}
                        </span>
                      )}
                    </div>
                    <FieldError message={errors.measure} />
                  </div>
                )}

                <div id={fieldId("note")} className="space-y-2 scroll-mt-4">
                  <FieldLabel htmlFor="wizard-note" required={noteRequired}>
                    {t("maintenance.wizard.note")}
                  </FieldLabel>
                  <textarea
                    id="wizard-note"
                    rows={3}
                    value={draft.note}
                    disabled={saving}
                    onChange={(event) => props.onDraftChange({ note: event.target.value })}
                    placeholder={t(NOTE_PLACEHOLDER[draft.outcome ?? "ok"])}
                    aria-invalid={errors.note ? true : undefined}
                    className={cn(
                      "flex w-full rounded-lg border bg-background px-3 py-2.5 text-base shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      errors.note ? "border-destructive" : "border-border",
                    )}
                  />
                  <FieldError message={errors.note} />
                </div>

                {/* Required by the point, or offered (optional) to show an anomaly. */}
                {(check.requires_photo || draft.outcome === "issue" || draft.photo !== null) && (
                  <div id={fieldId("photo")} className="scroll-mt-4">
                    <PhotoProofInput
                      file={draft.photo}
                      onChange={(photo) => props.onDraftChange({ photo })}
                      required={photoRequired}
                      error={errors.photo}
                      disabled={saving}
                    />
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

    </div>
  );
}
