import type { ReactNode } from "react";
import { Button } from "../../../components/ui/button";
import { StatusAnimation } from "../../../components/patterns/StatusAnimation";
import { useI18n } from "../../../lib/i18n";

/**
 * What a block says when it has nothing to show: what is missing and what to do
 * about it, never a zero that reads as a result.
 */
export function MissingState({
  illustration,
  title,
  description,
  action,
  compact = false,
}: {
  illustration: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={
        compact
          ? "flex items-center gap-4 rounded-xl border border-dashed border-border bg-white px-4 py-3"
          : "flex flex-col items-center gap-2 rounded-xl border border-dashed border-border bg-white px-4 py-6 text-center"
      }
    >
      <div aria-hidden="true" className="shrink-0 text-muted-foreground">
        {illustration}
      </div>
      <div className={compact ? "min-w-0 flex-1" : "space-y-1"}>
        <p className="text-sm font-semibold text-primary">{title}</p>
        <p className="text-sm text-muted-foreground">{description}</p>
        {action ? <div className="pt-2">{action}</div> : null}
      </div>
    </div>
  );
}

/** A block that failed to load, on its own: the rest of the page keeps working. */
export function BlockError({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <MissingState
      illustration={<StatusAnimation type="error" size={44} />}
      title={t("production.board.error.title")}
      description={t("production.board.error.desc")}
      action={
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t("production.board.error.retry")}
        </Button>
      }
    />
  );
}
