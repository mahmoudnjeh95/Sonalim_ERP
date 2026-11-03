import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { AppLoader } from "../../components/patterns/AppLoader";

export interface HrTab<T extends string> {
  value: T;
  label: string;
  content: ReactNode;
  hidden?: boolean;
}

/** The active tab lives in `?tab=` so each tab can be linked to and reloaded. */
export function useTabParam<T extends string>(values: readonly T[], fallback: T): [T, (value: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const current = values.find((value) => value === raw) ?? fallback;
  const select = (value: T) => {
    const next = new URLSearchParams(params);
    next.set("tab", value);
    setParams(next, { replace: true });
  };
  return [current, select];
}

/** True from the first time `ready` is true: the branded loader shows for the first load only. */
export function useBooted(ready: boolean): boolean {
  const [booted, setBooted] = useState(ready);
  useEffect(() => {
    if (ready) setBooted(true);
  }, [ready]);
  return booted;
}

export function HrTabsPage<T extends string>({
  title, subtitle, tabs, active, onChange, layoutId, booted, loaderLabel, actions,
}: {
  title: string;
  subtitle: string;
  tabs: HrTab<T>[];
  active: T;
  onChange: (value: T) => void;
  layoutId: string;
  booted: boolean;
  loaderLabel: string;
  actions?: ReactNode;
}) {
  const visible = tabs.filter((tab) => !tab.hidden);
  const current = visible.find((tab) => tab.value === active) ?? visible[0];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        </div>
        {actions}
      </div>
      <Tabs value={current?.value} onValueChange={(value) => onChange(value as T)}>
        <StickyTabBar>
          <TabsList>
            {visible.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} active={current?.value === tab.value} layoutId={layoutId}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </StickyTabBar>
      </Tabs>
      {!booted && <AppLoader label={loaderLabel} />}
      {/* Kept mounted behind the loader so its reads start at once. */}
      <div hidden={!booted}>{current?.content}</div>
    </div>
  );
}
