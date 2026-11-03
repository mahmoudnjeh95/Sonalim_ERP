import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  ArrowRight,
  CalendarClock,
  Clock,
  Coins,
  Pencil,
  Search,
  Target,
  ThumbsDown,
  User,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { currentLocale, useI18n } from "../../../lib/i18n";
import { formatXofWithCode } from "../../../lib/currency";
import { ApiError } from "../../../lib/api";
import { cn } from "../../../lib/utils";
import { listUserDirectory, userDisplayName } from "../../../lib/usersApi";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { StatusBadge } from "../../../components/patterns/StatusBadge";
import { listPartners } from "../../partners/api";
import {
  listOpportunities,
  NEXT_STAGES,
  transitionOpportunity,
  type Opportunity,
  type OpportunityStage,
  type Priority,
} from "./api";
import { OpportunityFormDialog } from "./OpportunityFormDialog";
import { MarkLostDialog } from "./MarkLostDialog";
import { MarkWonDialog } from "./MarkWonDialog";

const stages: OpportunityStage[] = ["prospecting", "qualification", "proposal", "negotiation", "won", "lost"];
const OPPORTUNITIES_QUERY_KEY = ["crm", "opportunities"] as const;
const DASHBOARD_QUERY_KEY = ["crm", "dashboard"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
const USER_DIRECTORY_QUERY_KEY = ["core", "users", "directory"] as const;

/** A deal past this many days without closing gets flagged so it doesn't quietly die in a stage. */
const STALE_AFTER_DAYS = 30;

const PRIORITY_DOT: Record<Priority, string> = {
  low: "bg-muted-foreground/40",
  medium: "bg-warning",
  high: "bg-destructive",
};

function formatCurrency(amount: number) {
  return formatXofWithCode(amount);
}

function daysSince(iso: string) {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000));
}

export function PipelinePage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [draggedOpportunity, setDraggedOpportunity] = useState<Opportunity | null>(null);
  const [dragOverStage, setDragOverStage] = useState<OpportunityStage | null>(null);
  const [losingOpportunity, setLosingOpportunity] = useState<Opportunity | null>(null);
  const [winningOpportunity, setWinningOpportunity] = useState<Opportunity | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingOpportunity, setEditingOpportunity] = useState<Opportunity | null>(null);
  const [search, setSearch] = useState("");
  const [mineOnly, setMineOnly] = useState(false);

  const { data: opportunities = [] } = useQuery({ queryKey: OPPORTUNITIES_QUERY_KEY, queryFn: () => listOpportunities(token) });
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const { data: users = [] } = useQuery({ queryKey: USER_DIRECTORY_QUERY_KEY, queryFn: () => listUserDirectory(token) });
  const activePartners = partners.filter((p) => p.status === "active" && p.kind !== "supplier");

  const mutation = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: OpportunityStage }) =>
      transitionOpportunity(token, id, stage, { correlationId: crypto.randomUUID() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_QUERY_KEY });
      toast.success(t("crm.opportunities.updated"));
    },
    onError: (error) => toast.error(t("crm.pipeline.updateError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const partnerName = (id: string) => partners.find((partner) => partner.id === id)?.name ?? "—";
  const ownerName = (ownerId: string | null) => {
    if (!ownerId) return null;
    const user = users.find((u) => u.id === ownerId);
    return user ? userDisplayName(user) : null;
  };

  function moveToStage(opportunity: Opportunity, stage: OpportunityStage) {
    if (stage === "lost") {
      setLosingOpportunity(opportunity);
      return;
    }
    if (stage === "won") {
      setWinningOpportunity(opportunity);
      return;
    }
    mutation.mutate({ id: opportunity.id, stage });
  }

  function handleDrop(stage: OpportunityStage) {
    if (!draggedOpportunity) return;
    setDragOverStage(null);
    if (!NEXT_STAGES[draggedOpportunity.stage].includes(stage)) {
      toast.error(t("crm.pipeline.invalidMove"));
      return;
    }
    moveToStage(draggedOpportunity, stage);
    setDraggedOpportunity(null);
  }

  function openCreateDialog() {
    setEditingOpportunity(null);
    setFormOpen(true);
  }

  function openEditDialog(opportunity: Opportunity) {
    setEditingOpportunity(opportunity);
    setFormOpen(true);
  }

  const hasActiveFilter = search.trim().length > 0 || mineOnly;
  const term = search.trim().toLowerCase();
  const visibleOpportunities = opportunities.filter((opportunity) => {
    if (mineOnly && opportunity.owner_id !== session!.userId) return false;
    if (!term) return true;
    return opportunity.name.toLowerCase().includes(term) || partnerName(opportunity.partner_id).toLowerCase().includes(term);
  });
  const openValue = visibleOpportunities
    .filter((o) => o.stage !== "won" && o.stage !== "lost")
    .reduce((sum, o) => sum + o.amount, 0);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("crm.pipeline.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("crm.pipeline.subtitle")}</p>
      </motion.div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("crm.pipeline.search.placeholder")}
            className="pl-8"
          />
        </div>
        <Button variant={mineOnly ? "default" : "outline"} size="sm" onClick={() => setMineOnly((v) => !v)}>
          {t("crm.opportunities.filter.mine")}
        </Button>
        <span className="text-xs text-muted-foreground">
          {visibleOpportunities.length} {t("crm.pipeline.summary.deals")} · {formatCurrency(openValue)} {t("crm.pipeline.summary.open")}
        </span>
        <Button
          size="sm"
          className="ml-auto"
          onClick={openCreateDialog}
          disabled={activePartners.length === 0}
          title={activePartners.length === 0 ? t("crm.opportunities.noAccounts") : undefined}
        >
          <Target className="h-4 w-4" />
          {t("crm.opportunities.new")}
        </Button>
      </div>

      <div className="flex gap-4 overflow-x-auto pb-2">
        {stages.map((stage) => {
          const cards = visibleOpportunities.filter((item) => item.stage === stage);
          const total = cards.reduce((sum, item) => sum + item.amount, 0);
          const canDrop = draggedOpportunity ? NEXT_STAGES[draggedOpportunity.stage].includes(stage) : false;
          const isBlockedTarget = draggedOpportunity !== null && draggedOpportunity.stage !== stage && !canDrop;
          return (
            <Card
              key={stage}
              className={cn(
                "flex w-72 shrink-0 flex-col transition-all",
                dragOverStage === stage && "border-primary bg-primary/5",
                isBlockedTarget && "opacity-50",
              )}
              onDragOver={(event) => {
                if (canDrop) {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                  setDragOverStage(stage);
                }
              }}
              onDragLeave={() => setDragOverStage(null)}
              onDrop={() => handleDrop(stage)}
            >
              <CardHeader className="flex-col items-stretch gap-1 border-b px-4 py-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">
                    <StatusBadge status={stage} />
                  </CardTitle>
                  <span className="text-xs text-muted-foreground">{cards.length}</span>
                </div>
                <p className="text-xs font-medium text-muted-foreground">{formatCurrency(total)}</p>
              </CardHeader>
              <CardContent className="max-h-[65vh] space-y-3 overflow-y-auto p-3">
                {cards.map((opportunity) => {
                  const isUpdating = mutation.isPending && mutation.variables?.id === opportunity.id;
                  return (
                    <OpportunityCard
                      key={opportunity.id}
                      opportunity={opportunity}
                      partnerName={partnerName(opportunity.partner_id)}
                      ownerName={ownerName(opportunity.owner_id)}
                      isUpdating={isUpdating}
                      onAdvance={(nextStage) => moveToStage(opportunity, nextStage)}
                      onMarkLost={() => setLosingOpportunity(opportunity)}
                      onEdit={() => openEditDialog(opportunity)}
                      onDragStart={() => setDraggedOpportunity(opportunity)}
                      onDragEnd={() => {
                        setDraggedOpportunity(null);
                        setDragOverStage(null);
                      }}
                    />
                  );
                })}
                {cards.length === 0 && (
                  <p className="py-5 text-center text-xs text-muted-foreground">
                    {hasActiveFilter ? t("crm.pipeline.noMatches") : canDrop ? t("crm.pipeline.dropHere") : t("crm.pipeline.noDeals")}
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <OpportunityFormDialog open={formOpen} onOpenChange={setFormOpen} opportunity={editingOpportunity} />
      <MarkLostDialog opportunity={losingOpportunity} onOpenChange={(open) => !open && setLosingOpportunity(null)} />
      <MarkWonDialog opportunity={winningOpportunity} onOpenChange={(open) => !open && setWinningOpportunity(null)} />
    </div>
  );
}

function OpportunityCard({
  opportunity,
  partnerName,
  ownerName,
  isUpdating,
  onAdvance,
  onMarkLost,
  onEdit,
  onDragStart,
  onDragEnd,
}: {
  opportunity: Opportunity;
  partnerName: string;
  ownerName: string | null;
  isUpdating: boolean;
  onAdvance: (stage: OpportunityStage) => void;
  onMarkLost: () => void;
  onEdit: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
}) {
  const { t } = useI18n();
  const nextStages = NEXT_STAGES[opportunity.stage];
  const advanceStage = nextStages.find((stage) => stage !== "lost");
  const canMarkLost = nextStages.includes("lost");
  const age = daysSince(opportunity.created_at);
  const isStalled = canMarkLost && age > STALE_AFTER_DAYS;

  return (
    <div
      draggable
      role="button"
      tabIndex={0}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", opportunity.id);
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      onClick={onEdit}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onEdit();
        }
      }}
      className={cn(
        "group cursor-grab space-y-2.5 rounded-lg border bg-background p-3 shadow-sm transition-shadow hover:shadow-raised active:cursor-grabbing",
        opportunity.stage === "won" && "border-success/40 bg-success-soft/30",
      )}
    >
      <div className="flex items-start gap-2">
        <span
          className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", PRIORITY_DOT[opportunity.priority])}
          title={t(`priority.${opportunity.priority}` as Parameters<typeof t>[0])}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{opportunity.name}</p>
          <p className="truncate text-xs text-muted-foreground">{partnerName}</p>
        </div>
        <Pencil className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
      </div>

      {ownerName && (
        <p className="flex items-center gap-1 truncate text-xs text-muted-foreground" title={t("crm.opportunities.field.owner")}>
          <User className="h-3 w-3 shrink-0" />
          <span className="truncate">{ownerName}</span>
        </p>
      )}

      <div className="flex items-center justify-between text-xs">
        <span className="flex items-center gap-1 font-medium tabular-nums">
          <Coins className="h-3 w-3 shrink-0" />
          {formatCurrency(opportunity.amount)}
        </span>
        <span className="text-muted-foreground">{opportunity.probability}%</span>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        {opportunity.expected_close_date ? (
          <span className="flex min-w-0 items-center gap-1 truncate">
            <CalendarClock className="h-3 w-3 shrink-0" />
            {opportunity.expected_close_date}
          </span>
        ) : (
          <span />
        )}
        <span
          className={cn("flex shrink-0 items-center gap-1", isStalled && "font-medium text-warning")}
          title={`${t("crm.pipeline.createdOn")} ${new Date(opportunity.created_at).toLocaleDateString(currentLocale())}${
            isStalled ? ` · ${t("crm.pipeline.stalledHint")}` : ""
          }`}
        >
          <Clock className="h-3 w-3 shrink-0" />
          {age}
          {t("crm.pipeline.daysAbbrev")}
        </span>
      </div>

      {(advanceStage || canMarkLost) && (
        <div className="flex gap-1.5 pt-0.5" onClick={(event) => event.stopPropagation()}>
          {advanceStage && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 flex-1 px-2 text-xs"
              onClick={() => onAdvance(advanceStage)}
              disabled={isUpdating}
            >
              <ArrowRight className="h-3.5 w-3.5" />
              {t(`status.${advanceStage}` as Parameters<typeof t>[0])}
            </Button>
          )}
          {canMarkLost && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive"
              onClick={onMarkLost}
              disabled={isUpdating}
              title={t("crm.opportunities.markLost")}
              aria-label={t("crm.opportunities.markLost")}
            >
              <ThumbsDown className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
