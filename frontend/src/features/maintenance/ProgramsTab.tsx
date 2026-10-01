import { useState, type ReactNode } from "react";
import { AlertTriangle, Pencil, Play, Plus, Repeat } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Switch } from "../../components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { AppLoader } from "../../components/patterns/AppLoader";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useIsMobile } from "../../lib/useIsMobile";
import { usePrograms, useRunDuePrograms, useUpdateProgram, type Program } from "./api";
import { useHasPermission } from "./hooks";
import { ProgramDialog } from "./programs/ProgramDialog";
import { apiErrorMessage, formatDay } from "./jobs/jobFormat";

const INTERVAL_UNIT_LABEL_KEY: Record<Program["interval_unit"], { one: TranslationKey; many: TranslationKey }> = {
  day: { one: "maintenance.programs.everyDay", many: "maintenance.programs.everyDays" },
  week: { one: "maintenance.programs.everyWeek", many: "maintenance.programs.everyWeeks" },
  month: { one: "maintenance.programs.everyMonth", many: "maintenance.programs.everyMonths" },
};

/** "Tous les N jours/semaines/mois" — the program's recurrence in one line. */
function intervalLabel(program: Program, t: (key: TranslationKey) => string): string {
  const { interval_value: value, interval_unit: unit } = program;
  const keys = INTERVAL_UNIT_LABEL_KEY[unit];
  return value === 1 ? t(keys.one) : t(keys.many).replace("{count}", String(value));
}

/**
 * Preventive programs: recurring checks on a machine, materialised into jobs
 * by the sweep (worker, every `MAINTENANCE_SWEEP_INTERVAL_SECONDS`) or by
 * "Lancer les échéances" here, run by hand. A program never itself has a
 * status chip on the calendar — it only ever appears there as a projected
 * occurrence (not yet due) or as the job it eventually produced.
 */
export function ProgramsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const isMobile = useIsMobile();
  const canPlan = useHasPermission("maintenance.plan_jobs");

  const { data: programs, isLoading, isError, error } = usePrograms(token);
  const update = useUpdateProgram(token);
  const runDue = useRunDuePrograms(token);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProgram, setEditingProgram] = useState<Program | null>(null);

  function openCreate() {
    setEditingProgram(null);
    setDialogOpen(true);
  }
  function openEdit(program: Program) {
    setEditingProgram(program);
    setDialogOpen(true);
  }

  function toggleActive(program: Program) {
    update.mutate(
      { programId: program.id, input: { active: !program.active } },
      {
        onError: (mutationError) => {
          toast.error(apiErrorMessage(mutationError, t("maintenance.programs.toggleError")));
        },
      },
    );
  }

  function handleRunDue() {
    runDue.mutate(undefined, {
      onSuccess: (result) => {
        toast.success(
          t("maintenance.programs.runDue.result")
            .replace("{created}", String(result.created))
            .replace("{overdue}", String(result.overdue_notified)),
        );
      },
      onError: (mutationError) => {
        toast.error(apiErrorMessage(mutationError, t("maintenance.programs.runDue.error")));
      },
    });
  }

  const rows = programs ?? [];
  const emptyIcon = isError ? <AlertTriangle className="h-5 w-5" /> : <Repeat className="h-5 w-5" />;
  const emptyTitle = isError ? t("maintenance.programs.loadError.title") : t("maintenance.programs.empty.title");
  const emptyDescription = isError
    ? apiErrorMessage(error, t("maintenance.programs.loadError.description"))
    : canPlan
      ? t("maintenance.programs.empty.description.planner")
      : t("maintenance.programs.empty.description");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {canPlan && (
          <>
            <Button variant="outline" onClick={handleRunDue} disabled={runDue.isPending}>
              <Play className="h-4 w-4" />
              {runDue.isPending ? t("maintenance.programs.runDue.running") : t("maintenance.programs.runDue")}
            </Button>
            <Button onClick={openCreate}>
              <Plus className="h-4 w-4" />
              {t("maintenance.programs.new")}
            </Button>
          </>
        )}
      </div>

      {isLoading ? (
        <AppLoader className="py-16" />
      ) : isMobile ? (
        <MobileProgramList
          programs={rows}
          canPlan={canPlan}
          onEdit={openEdit}
          onToggleActive={toggleActive}
          toggling={update.isPending ? update.variables?.programId : undefined}
          emptyIcon={emptyIcon}
          emptyTitle={emptyTitle}
          emptyDescription={emptyDescription}
        />
      ) : rows.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("maintenance.programs.column.machine")}</TableHead>
                  <TableHead>{t("maintenance.programs.column.name")}</TableHead>
                  <TableHead>{t("maintenance.programs.column.interval")}</TableHead>
                  <TableHead>{t("maintenance.programs.column.nextOccurrence")}</TableHead>
                  <TableHead>{t("maintenance.programs.column.leadDays")}</TableHead>
                  <TableHead>{t("maintenance.programs.column.team")}</TableHead>
                  <TableHead>{t("maintenance.programs.column.active")}</TableHead>
                  <TableHead aria-label={t("common.actions")} />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((program) => (
                  <TableRow key={program.id} className={!program.active ? "opacity-60" : undefined}>
                    <TableCell>{program.equipment_name}</TableCell>
                    <TableCell className="font-medium">{program.name}</TableCell>
                    <TableCell className="whitespace-nowrap">{intervalLabel(program, t)}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDay(program.next_occurrence)}</TableCell>
                    <TableCell>{program.lead_days}</TableCell>
                    <TableCell>{program.default_team_name ?? <span className="text-muted-foreground">{t("maintenance.programs.noTeam")}</span>}</TableCell>
                    <TableCell>
                      <Switch
                        aria-label={t("maintenance.programs.field.active")}
                        checked={program.active}
                        onCheckedChange={() => toggleActive(program)}
                        disabled={!canPlan || (update.isPending && update.variables?.programId === program.id)}
                      />
                    </TableCell>
                    <TableCell>
                      {canPlan && (
                        <Button variant="ghost" size="sm" onClick={() => openEdit(program)}>
                          <Pencil className="h-3.5 w-3.5" />
                          {t("common.edit")}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {canPlan && <ProgramDialog open={dialogOpen} onOpenChange={setDialogOpen} program={editingProgram} />}
    </div>
  );
}

function MobileProgramList({
  programs,
  canPlan,
  onEdit,
  onToggleActive,
  toggling,
  emptyIcon,
  emptyTitle,
  emptyDescription,
}: {
  programs: Program[];
  canPlan: boolean;
  onEdit: (program: Program) => void;
  onToggleActive: (program: Program) => void;
  toggling: string | undefined;
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
}) {
  const { t } = useI18n();
  if (programs.length === 0) {
    return (
      <Card>
        <CardContent>
          <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-2">
      {programs.map((program) => (
        <Card key={program.id} className={!program.active ? "opacity-60" : undefined}>
          <CardContent className="space-y-2 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate font-medium">{program.name}</p>
                <p className="truncate text-sm text-muted-foreground">{program.equipment_name}</p>
              </div>
              <Switch
                aria-label={t("maintenance.programs.field.active")}
                checked={program.active}
                onCheckedChange={() => onToggleActive(program)}
                disabled={!canPlan || toggling === program.id}
              />
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <Badge variant="outline">{intervalLabel(program, t)}</Badge>
              <span>
                {t("maintenance.programs.column.nextOccurrence")}: {formatDay(program.next_occurrence)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>{program.default_team_name ?? t("maintenance.programs.noTeam")}</span>
              {canPlan && (
                <Button variant="ghost" size="sm" onClick={() => onEdit(program)}>
                  <Pencil className="h-3.5 w-3.5" />
                  {t("common.edit")}
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
