import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Lock, ScanLine } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { Card, CardContent } from "../../components/ui/card";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { useLabel } from "../production/shift/shiftText";
import { AliasesTable } from "./AliasesTable";
import { ScanSessionsTable } from "./ScanSessionsTable";
import { ScanStart } from "./ScanStart";
import { ScanWorkspace } from "./ScanWorkspace";
import { S } from "./scanText";

type View = "new" | "history" | "dictionary";

export function ScanTab() {
  const { hasPermission } = useAuth();
  const label = useLabel();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<View>("new");
  const sessionId = params.get("session");

  if (!hasPermission("scan.use_scanner")) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 py-8 text-sm text-muted-foreground">
          <Lock className="mt-0.5 h-4 w-4 shrink-0" />
          {label(S.noAccess)}
        </CardContent>
      </Card>
    );
  }
  const open = (id: string) => setParams({ tab: "scan", session: id });
  if (sessionId) return <ScanWorkspace sessionId={sessionId} onBack={() => setParams({ tab: "scan" })} />;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <ScanLine className="h-5 w-5 text-primary" />
          {label(S.title)}
        </h2>
        <p className="text-sm text-muted-foreground">{label(S.subtitle)}</p>
      </div>
      <FilterTabs
        value={view}
        onChange={setView}
        options={[
          { value: "new", label: label(S.viewNew) },
          { value: "history", label: label(S.viewHistory) },
          { value: "dictionary", label: label(S.viewDictionary) },
        ]}
      />
      {view === "new" && <ScanStart onCreated={open} />}
      {view === "history" && <ScanSessionsTable onOpen={open} />}
      {view === "dictionary" && <AliasesTable />}
    </div>
  );
}
