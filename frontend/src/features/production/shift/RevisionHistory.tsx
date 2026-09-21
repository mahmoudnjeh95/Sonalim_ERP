import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { currentLocale } from "../../../lib/i18n";
import { listUserDirectory, userDisplayName } from "../../../lib/usersApi";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import type { OptionMap } from "./ShiftGrid";
import { Part } from "./SectionCard";
import type { SectionDef } from "./sectionConfig";
import { toDraft } from "./shiftModel";
import { listSectionRevisions, type SectionRevision } from "./shiftApi";
import { T, useLabel } from "./shiftText";
import { AppLoader } from "../../../components/patterns/AppLoader";

/**
 * Every time a section is handed in, and every edit after that, freezes what it held.
 * This lists them newest first, with who, when and why, and shows what each held.
 */
export function RevisionHistory({
  def,
  shiftId,
  revision,
  options,
}: {
  def: SectionDef;
  shiftId: string;
  revision: number;
  options: OptionMap;
}) {
  const label = useLabel();
  const [open, setOpen] = useState(false);
  if (revision <= 0) return null;

  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        <History className="h-3.5 w-3.5" />
        {label(T.history)} ({revision})
      </Button>
      {open && <HistoryDialog def={def} shiftId={shiftId} options={options} onClose={() => setOpen(false)} />}
    </>
  );
}

function HistoryDialog({
  def,
  shiftId,
  options,
  onClose,
}: {
  def: SectionDef;
  shiftId: string;
  options: OptionMap;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const [expanded, setExpanded] = useState<number | null>(null);

  const revisions = useQuery({
    queryKey: ["production", "shift-reports", "revisions", shiftId, def.key],
    queryFn: () => listSectionRevisions(token, shiftId, def.key),
  });
  const users = useQuery({ queryKey: ["core", "user-directory"], queryFn: () => listUserDirectory(token) });
  const who = (id: string | null) => {
    const user = users.data?.find((u) => u.id === id);
    return user ? userDisplayName(user) : "—";
  };
  const when = (iso: string) =>
    new Date(iso).toLocaleString(currentLocale(), { dateStyle: "medium", timeStyle: "short" });

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{label(T.historyTitle)}</DialogTitle>
          <DialogDescription>{label(def.title)}</DialogDescription>
        </DialogHeader>

        {revisions.isLoading ? (
          <AppLoader size={96} className="py-4" />
        ) : (revisions.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">{label(T.noHistory)}</p>
        ) : (
          <ol className="space-y-2">
            {(revisions.data ?? []).map((revision, index) => (
              <li key={revision.revision} className="overflow-hidden rounded-lg border border-border">
                <button
                  type="button"
                  onClick={() => setExpanded(expanded === revision.revision ? null : revision.revision)}
                  aria-expanded={expanded === revision.revision}
                  className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 bg-muted/50 px-3 py-2 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                >
                  <span className="font-medium">
                    {label(T.revision)} {revision.revision}
                  </span>
                  {index === 0 && <Badge variant="primary">{label(T.latest)}</Badge>}
                  <span className="text-muted-foreground">{when(revision.created_at)}</span>
                  <span className="text-muted-foreground">{who(revision.actor_id)}</span>
                  {revision.reason && <span className="min-w-0 flex-1 truncate text-muted-foreground">“{revision.reason}”</span>}
                </button>
                {expanded === revision.revision && <Snapshot def={def} revision={revision} options={options} />}
              </li>
            ))}
          </ol>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Snapshot({ def, revision, options }: { def: SectionDef; revision: SectionRevision; options: OptionMap }) {
  const label = useLabel();
  // Revisions carried over from the old Daily / Conditionnement reports hold that report's own
  // JSON, not a shift section's rows; say so rather than show an empty table.
  if ("legacy_report_id" in revision.snapshot) {
    return <p className="px-3 py-3 text-sm text-muted-foreground">{label(T.legacySnapshot)}</p>;
  }
  const draft = toDraft(def, revision.snapshot);
  return (
    <div className="space-y-3 px-3 py-3">
      {def.parts.map((part) => (
        <Part
          key={part.payloadKey}
          part={part}
          sectionKey={`history-${def.key}-${revision.revision}`}
          value={draft[part.payloadKey]}
          onChange={() => undefined}
          options={options}
          disabled
        />
      ))}
    </div>
  );
}
