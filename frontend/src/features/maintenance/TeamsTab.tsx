import { useMemo, useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Archive, ArchiveRestore, Pencil, Plus, Search, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { AppLoader } from "../../components/patterns/AppLoader";
import { useHasPermission } from "./hooks";
import {
  useChefCandidates,
  useCreateTeam,
  useSetTeamMembers,
  useTeamCandidates,
  useTeams,
  useUpdateTeam,
  type Team,
} from "./api";

/** The create/edit dialog's own fields; member assignment is a separate step (PUT /teams/{id}/members) because a brand-new team has no id to attach members to yet. */
interface TeamFormState {
  name: string;
  chef_user_id: string;
}

const EMPTY_FORM: TeamFormState = { name: "", chef_user_id: "" };

export function TeamsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const canManage = useHasPermission("maintenance.manage_teams");

  const { data: teams = [], isLoading } = useTeams(token);
  const { data: teamCandidates = [] } = useTeamCandidates(token);
  const { data: chefCandidates = [] } = useChefCandidates(token);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTeam, setEditingTeam] = useState<Team | null>(null);
  const [form, setForm] = useState<TeamFormState>(EMPTY_FORM);

  const [membersDialogTeam, setMembersDialogTeam] = useState<Team | null>(null);
  const [memberSearch, setMemberSearch] = useState("");
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([]);

  const createMutation = useCreateTeam(token);
  const updateMutation = useUpdateTeam(token);
  const setMembersMutation = useSetTeamMembers(token);

  function openCreateDialog() {
    setEditingTeam(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  }

  function openEditDialog(team: Team) {
    setEditingTeam(team);
    setForm({ name: team.name, chef_user_id: team.chef_user_id ?? "" });
    setDialogOpen(true);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const input = { name: form.name.trim(), chef_user_id: form.chef_user_id || null };
    if (!input.name) return;

    if (editingTeam) {
      updateMutation.mutate(
        { teamId: editingTeam.id, input },
        {
          onSuccess: () => {
            setDialogOpen(false);
            setEditingTeam(null);
            toast.success(t("maintenance.teams.saved"));
          },
          onError: (error) => {
            toast.error(t("maintenance.teams.saveError"), { description: error instanceof ApiError ? error.message : undefined });
          },
        },
      );
    } else {
      createMutation.mutate(input, {
        onSuccess: () => {
          setDialogOpen(false);
          toast.success(t("maintenance.teams.created"));
        },
        onError: (error) => {
          toast.error(t("maintenance.teams.createError"), { description: error instanceof ApiError ? error.message : undefined });
        },
      });
    }
  }

  function handleToggleArchive(team: Team) {
    updateMutation.mutate(
      { teamId: team.id, input: { archived: !team.archived_at } },
      {
        onSuccess: () => {
          toast.success(team.archived_at ? t("maintenance.teams.unarchived") : t("maintenance.teams.archived"));
        },
        onError: (error) => {
          toast.error(t("maintenance.teams.archiveError"), { description: error instanceof ApiError ? error.message : undefined });
        },
      },
    );
  }

  function openMembersDialog(team: Team) {
    setMembersDialogTeam(team);
    setSelectedMemberIds(team.members.map((m) => m.employee_id));
    setMemberSearch("");
  }

  function toggleMember(employeeId: string) {
    setSelectedMemberIds((current) =>
      current.includes(employeeId) ? current.filter((id) => id !== employeeId) : [...current, employeeId],
    );
  }

  function handleSaveMembers() {
    if (!membersDialogTeam) return;
    setMembersMutation.mutate(
      { teamId: membersDialogTeam.id, employeeIds: selectedMemberIds },
      {
        onSuccess: () => {
          setMembersDialogTeam(null);
          toast.success(t("maintenance.teams.membersSaved"));
        },
        onError: (error) => {
          toast.error(t("maintenance.teams.membersSaveError"), { description: error instanceof ApiError ? error.message : undefined });
        },
      },
    );
  }

  const filteredCandidates = useMemo(() => {
    const query = memberSearch.trim().toLowerCase();
    if (!query) return teamCandidates;
    return teamCandidates.filter((person) => person.name.toLowerCase().includes(query));
  }, [teamCandidates, memberSearch]);

  // Keep a currently-selected candidate visible even if a search term hides
  // it — unchecking by search text, rather than the box the user actually
  // sees, would be a confusing way to lose a selection.
  const visibleCandidates = useMemo(() => {
    const visibleIds = new Set(filteredCandidates.map((p) => p.id));
    const stillSelected = teamCandidates.filter((p) => selectedMemberIds.includes(p.id) && !visibleIds.has(p.id));
    return [...filteredCandidates, ...stillSelected];
  }, [filteredCandidates, teamCandidates, selectedMemberIds]);

  if (isLoading) {
    return <AppLoader className="py-16" />;
  }

  return (
    <div className="space-y-4">
      {canManage && (
        <div className="flex justify-end">
          <Dialog
            open={dialogOpen}
            onOpenChange={(open) => {
              setDialogOpen(open);
              if (!open) setEditingTeam(null);
            }}
          >
            <DialogTrigger asChild>
              <Button onClick={openCreateDialog}>
                <Plus className="h-4 w-4" />
                {t("maintenance.teams.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{editingTeam ? t("maintenance.teams.dialog.editTitle") : t("maintenance.teams.dialog.title")}</DialogTitle>
                <DialogDescription>
                  {editingTeam ? t("maintenance.teams.dialog.editDescription") : t("maintenance.teams.dialog.description")}
                </DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit}>
                <div className="space-y-1.5">
                  <Label htmlFor="team-name">{t("maintenance.teams.field.name")}</Label>
                  <Input
                    id="team-name"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="team-chef">{t("maintenance.teams.field.chef")}</Label>
                  <Select
                    id="team-chef"
                    value={form.chef_user_id}
                    onChange={(e) => setForm((f) => ({ ...f, chef_user_id: e.target.value }))}
                  >
                    <option value="">{t("maintenance.teams.field.chef.none")}</option>
                    {chefCandidates.map((person) => (
                      <option key={person.id} value={person.id}>
                        {person.name}
                      </option>
                    ))}
                  </Select>
                </div>
                {(() => {
                  const isError = editingTeam ? updateMutation.isError : createMutation.isError;
                  const error: unknown = editingTeam ? updateMutation.error : createMutation.error;
                  if (!isError) return null;
                  return (
                    <p className="text-sm text-destructive">
                      {error instanceof ApiError ? error.message : t(editingTeam ? "maintenance.teams.saveError" : "maintenance.teams.createError")}
                    </p>
                  );
                })()}
                <Button type="submit" className="w-full" disabled={editingTeam ? updateMutation.isPending : createMutation.isPending}>
                  {editingTeam
                    ? updateMutation.isPending
                      ? t("maintenance.teams.saving")
                      : t("maintenance.teams.saveChanges")
                    : createMutation.isPending
                      ? t("maintenance.teams.creating")
                      : t("maintenance.teams.create")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      )}

      {teams.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={<Users className="h-5 w-5" />}
              title={t("maintenance.teams.empty.title")}
              description={t("maintenance.teams.empty.description")}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <AnimatePresence initial={false}>
            {teams.map((team, i) => (
              <motion.div
                key={team.id}
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                exit={{ opacity: 0 }}
              >
                <Card className="flex h-full flex-col p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{team.name}</p>
                      <p className="truncate text-sm text-muted-foreground">
                        {team.chef_name ? t("maintenance.teams.chefPrefix") + team.chef_name : t("maintenance.teams.noChef")}
                      </p>
                    </div>
                    {team.archived_at && (
                      <Badge variant="outline" dot>
                        {t("maintenance.teams.archived.badge")}
                      </Badge>
                    )}
                  </div>

                  <div className="mt-3 flex flex-1 flex-wrap items-start gap-1.5">
                    {team.members.length === 0 ? (
                      <span className="text-xs text-muted-foreground">{t("maintenance.teams.noMembers")}</span>
                    ) : (
                      team.members.map((member) => (
                        <Badge key={member.employee_id} variant="default">
                          {member.name}
                        </Badge>
                      ))
                    )}
                  </div>

                  {canManage && (
                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button size="sm" variant="outline" onClick={() => openMembersDialog(team)}>
                        <Users className="h-3.5 w-3.5" />
                        {t("maintenance.teams.manageMembers")}
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => openEditDialog(team)}>
                        <Pencil className="h-3.5 w-3.5" />
                        {t("maintenance.teams.edit")}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleToggleArchive(team)}
                        disabled={updateMutation.isPending && updateMutation.variables?.teamId === team.id}
                      >
                        {team.archived_at ? (
                          <>
                            <ArchiveRestore className="h-3.5 w-3.5" />
                            {t("maintenance.teams.unarchive")}
                          </>
                        ) : (
                          <>
                            <Archive className="h-3.5 w-3.5" />
                            {t("maintenance.teams.archive")}
                          </>
                        )}
                      </Button>
                    </div>
                  )}
                </Card>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      <Dialog open={!!membersDialogTeam} onOpenChange={(open) => !open && setMembersDialogTeam(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("maintenance.teams.members.dialogTitle")}</DialogTitle>
            <DialogDescription>{membersDialogTeam?.name}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder={t("maintenance.teams.members.searchPlaceholder")}
                value={memberSearch}
                onChange={(e) => setMemberSearch(e.target.value)}
              />
            </div>
            <div className="max-h-72 space-y-1 overflow-y-auto rounded-md border border-border p-2">
              {visibleCandidates.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">{t("maintenance.teams.members.noMatch")}</p>
              ) : (
                visibleCandidates.map((person) => {
                  const checked = selectedMemberIds.includes(person.id);
                  return (
                    <label
                      key={person.id}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                    >
                      <Checkbox checked={checked} onCheckedChange={() => toggleMember(person.id)} />
                      <span>{person.name}</span>
                    </label>
                  );
                })
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {t("maintenance.teams.members.selectedCount").replace("{count}", String(selectedMemberIds.length))}
            </p>
            <Button className="w-full" onClick={handleSaveMembers} disabled={setMembersMutation.isPending}>
              {setMembersMutation.isPending ? t("maintenance.teams.members.saving") : t("maintenance.teams.members.save")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
