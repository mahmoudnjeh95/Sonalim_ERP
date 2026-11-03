import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IdCard } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { AppLoader } from "../../components/patterns/AppLoader";
import { EmptyState } from "../../components/patterns/EmptyState";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Checkbox } from "../../components/ui/checkbox";
import { Label } from "../../components/ui/label";
import { hrKeys, listPositions } from "../hr/api";
import {
  SHIFT_ROLE_PEOPLE_QUERY_KEY,
  listShiftRolePeople,
  setShiftRolePositions,
} from "./shift/shiftApi";

/** The fiche de shift's four person fields, in the order the paper header has them. */
const ROLES = ["conducteur", "agent_fabrication", "machiniste", "aide_machiniste"] as const;
type Role = (typeof ROLES)[number];

/**
 * Who may be named in each of the fiche de shift's four person fields.
 *
 * The fields were free text, so the same person arrived spelled three ways. They are now
 * lists of the plant's own people -- and this is where the plant says who belongs in which
 * list, by ticking the HR positions whose holders may be named. Matching on how a job title
 * is spelled would empty a list the first time somebody wrote it differently, so the mapping
 * is kept as configuration and held by position, not by name.
 */
export function ShiftRolePositionsCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: positions = [], isLoading: positionsLoading } = useQuery({
    queryKey: hrKeys.positions,
    queryFn: () => listPositions(token),
  });
  const { data: roles, isLoading: rolesLoading } = useQuery({
    queryKey: SHIFT_ROLE_PEOPLE_QUERY_KEY,
    queryFn: () => listShiftRolePeople(token),
  });

  // What the boxes say while they are being ticked; the server's mapping until then.
  const [draft, setDraft] = useState<Record<string, string[]> | null>(null);
  useEffect(() => {
    if (roles) setDraft(roles.positions);
  }, [roles]);

  const save = useMutation({
    mutationFn: async (next: Record<string, string[]>) => {
      for (const role of ROLES) await setShiftRolePositions(token, role, next[role] ?? []);
    },
    onSuccess: () => {
      toast.success(t("production.settings.saved"));
      queryClient.invalidateQueries({ queryKey: SHIFT_ROLE_PEOPLE_QUERY_KEY });
    },
    onError: (error) => {
      toast.error(t("production.settings.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const toggle = (role: Role, positionId: string) =>
    setDraft((current) => {
      const held = current?.[role] ?? [];
      const next = held.includes(positionId) ? held.filter((id) => id !== positionId) : [...held, positionId];
      return { ...(current ?? {}), [role]: next };
    });

  const loading = positionsLoading || rolesLoading;
  const counted = (role: Role) => roles?.people[role]?.length ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          <IdCard className="h-4 w-4" />
          {t("production.settings.shiftRoles.title")}
          <HelpTooltip text={t("production.settings.shiftRoles.help")} />
        </CardTitle>
        <p className="mt-0.5 text-sm text-muted-foreground">{t("production.settings.shiftRoles.description")}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <AppLoader size={96} className="py-4" />
        ) : positions.length === 0 ? (
          <EmptyState
            icon={<IdCard className="h-5 w-5" />}
            title={t("production.settings.shiftRoles.empty.title")}
            description={t("production.settings.shiftRoles.empty.description")}
          />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {ROLES.map((role) => (
                <div key={role} className="space-y-2 rounded-lg border border-border p-3">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-sm font-medium">{t(`production.settings.shiftRoles.role.${role}` as const)}</p>
                    <span className="text-xs text-muted-foreground">
                      {t("production.settings.shiftRoles.peopleCount").replace("{count}", String(counted(role)))}
                    </span>
                  </div>
                  <div className="max-h-48 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">
                    {positions.map((position) => {
                      const id = `shift-role-${role}-${position.id}`;
                      return (
                        <div key={position.id} className="flex items-center gap-2">
                          <Checkbox
                            id={id}
                            checked={(draft?.[role] ?? []).includes(position.id)}
                            onCheckedChange={() => toggle(role, position.id)}
                          />
                          <Label htmlFor={id} className="text-sm font-normal">
                            {position.title}
                          </Label>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
            <Button size="sm" disabled={!draft || save.isPending} onClick={() => draft && save.mutate(draft)}>
              {save.isPending ? t("common.saving") : t("common.save")}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
