import type { ComponentType, ReactNode, SVGProps } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, RotateCw } from "lucide-react";
import { Button } from "../../components/ui/button";
import { AppLoader } from "../../components/patterns/AppLoader";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import ErrorIllustration from "../../assets/illustrations/empty-states/empty-error.svg?react";

export type SvgComponent = ComponentType<SVGProps<SVGSVGElement>>;

/** A missing-data state that says what is missing, using one of the supplied illustrations. */
export function AnalyticsEmptyState({
  illustration: Illustration,
  title,
  description,
  action,
  className,
  iconOnly = false,
}: {
  illustration: SvgComponent;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
  /** For line-icon assets (64px), which must not be scaled up to illustration size. */
  iconOnly?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.22 }}
      className={cn("flex flex-col items-center justify-center gap-3 px-4 py-8 text-center", className)}
    >
      <Illustration aria-hidden className={iconOnly ? "h-14 w-14 text-destructive" : "h-auto w-56 max-w-full"} />
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="mx-auto max-w-sm text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </motion.div>
  );
}

/** Same branded loader as the rest of the app; its CSS animation loops for as long as the data takes to arrive. */
export function AnalyticsLoadingState({ label, className }: { label?: string; className?: string }) {
  const { t } = useI18n();
  return <AppLoader label={label ?? t("analytics.state.loading")} className={cn("py-8", className)} />;
}

/** Says what the failure means for the reader (which figures are missing), not just that a request failed. */
export function AnalyticsErrorState({
  title,
  impact,
  onRetry,
  className,
}: {
  title: string;
  impact: string;
  onRetry: () => void;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <AnalyticsEmptyState
      illustration={ErrorIllustration}
      iconOnly
      title={title}
      description={impact}
      className={className}
      action={
        <Button type="button" variant="outline" size="sm" onClick={onRetry} className="gap-1.5">
          <RotateCw className="h-3.5 w-3.5" />
          {t("analytics.state.retry")}
        </Button>
      }
    />
  );
}

/** For a failed source that only removes part of a view: the rest still renders, and this says what is missing. */
export function AnalyticsInlineError({
  title,
  impact,
  onRetry,
  className,
}: {
  title: string;
  impact: string;
  onRetry: () => void;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <div
      role="alert"
      className={cn("flex items-start gap-3 rounded-lg border border-warning/30 bg-warning-soft p-3", className)}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-sm text-muted-foreground">{impact}</p>
      </div>
      <Button type="button" variant="ghost" size="sm" className="h-7 shrink-0 gap-1 px-2 text-xs" onClick={onRetry}>
        <RotateCw className="h-3.5 w-3.5" aria-hidden />
        {t("analytics.state.retry")}
      </Button>
    </div>
  );
}
