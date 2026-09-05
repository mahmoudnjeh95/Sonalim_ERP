import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, DollarSign, Target } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { ApiError } from "../../../lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { StatusBadge } from "../../../components/patterns/StatusBadge";
import { listPartners } from "../../partners/api";
import { listOpportunities, NEXT_STAGES, transitionOpportunity, type Opportunity, type OpportunityStage } from "./api";

const stages: OpportunityStage[] = ["prospecting", "qualification", "proposal", "negotiation", "won", "lost"];
const queryKey = ["crm", "opportunities"] as const;

export function PipelinePage() {
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [draggedOpportunity, setDraggedOpportunity] = useState<Opportunity | null>(null);
  const [dragOverStage, setDragOverStage] = useState<OpportunityStage | null>(null);
  const { data: opportunities = [] } = useQuery({ queryKey, queryFn: () => listOpportunities(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const mutation = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: OpportunityStage }) => transitionOpportunity(token, id, stage),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey }); toast.success("Pipeline updated"); },
    onError: (error) => toast.error("Could not update pipeline", { description: error instanceof ApiError ? error.message : undefined }),
  });
  const partnerName = (id: string) => partners.find((partner) => partner.id === id)?.name ?? "—";
  function handleDrop(stage: OpportunityStage) {
    if (!draggedOpportunity) return;
    setDragOverStage(null);
    if (!NEXT_STAGES[draggedOpportunity.stage].includes(stage)) {
      toast.error(`A ${draggedOpportunity.stage} deal cannot move directly to ${stage}`);
      return;
    }
    mutation.mutate({ id: draggedOpportunity.id, stage });
    setDraggedOpportunity(null);
  }

  return <div className="space-y-6"><div><h1 className="text-xl font-semibold tracking-tight">Opportunity pipeline</h1><p className="text-sm text-muted-foreground">Drag a deal to its next stage, or use the action on the card.</p></div><div className="grid gap-4 xl:grid-cols-6">{stages.map((stage) => { const cards = opportunities.filter((item) => item.stage === stage); const total = cards.reduce((sum, item) => sum + item.amount, 0); const canDrop = draggedOpportunity ? NEXT_STAGES[draggedOpportunity.stage].includes(stage) : false; return <Card key={stage} className={`min-w-0 transition-colors ${dragOverStage === stage ? "border-primary bg-primary/5" : ""}`} onDragOver={(event) => { if (canDrop) { event.preventDefault(); event.dataTransfer.dropEffect = "move"; setDragOverStage(stage); } }} onDragLeave={() => setDragOverStage(null)} onDrop={() => handleDrop(stage)}><CardHeader className="border-b px-4 py-3"><div className="flex items-center justify-between"><CardTitle className="text-sm"><StatusBadge status={stage} /></CardTitle><span className="text-xs text-muted-foreground">{cards.length}</span></div><p className="text-xs text-muted-foreground">${total.toLocaleString()}</p></CardHeader><CardContent className="space-y-3 p-3">{cards.map((opportunity) => <OpportunityCard key={opportunity.id} opportunity={opportunity} partnerName={partnerName(opportunity.partner_id)} onMove={(nextStage) => mutation.mutate({ id: opportunity.id, stage: nextStage })} onDragStart={() => setDraggedOpportunity(opportunity)} onDragEnd={() => { setDraggedOpportunity(null); setDragOverStage(null); }} />)}{cards.length === 0 && <p className="py-5 text-center text-xs text-muted-foreground">{canDrop ? "Drop deal here" : "No deals"}</p>}</CardContent></Card>; })}</div></div>;
}

function OpportunityCard({ opportunity, partnerName, onMove, onDragStart, onDragEnd }: { opportunity: Opportunity; partnerName: string; onMove: (stage: OpportunityStage) => void; onDragStart: () => void; onDragEnd: () => void }) {
  const next = NEXT_STAGES[opportunity.stage][0];
  return <div draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", opportunity.id); onDragStart(); }} onDragEnd={onDragEnd} className="cursor-grab space-y-3 rounded-lg border bg-background p-3 shadow-sm active:cursor-grabbing"><div className="flex items-start gap-2"><Target className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><div className="min-w-0"><p className="truncate text-sm font-medium">{opportunity.name}</p><p className="truncate text-xs text-muted-foreground">{partnerName}</p></div></div><div className="flex items-center justify-between text-xs"><span className="flex items-center gap-1"><DollarSign className="h-3 w-3" />{opportunity.amount.toLocaleString()}</span>{opportunity.expected_close_date && <span className="flex items-center gap-1 text-muted-foreground"><CalendarClock className="h-3 w-3" />{opportunity.expected_close_date}</span>}</div>{next && <Button variant="outline" size="sm" className="w-full" onClick={() => onMove(next)}><ArrowRight className="h-3.5 w-3.5" />{next === "lost" ? "Mark lost" : `Move to ${next}`}</Button>}</div>;
}
