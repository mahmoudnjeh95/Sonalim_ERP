import type { ComponentType } from "react";
import { AlertTriangle, CheckCircle2, Minus, XCircle } from "lucide-react";
import { Badge, type BadgeProps } from "../../components/ui/badge";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import type { Tone } from "./manufacturing/metrics";

const TONES: Record<Tone, { icon: ComponentType<{ className?: string }>; variant: BadgeProps["variant"]; labelKey: TranslationKey }> = {
  good: { icon: CheckCircle2, variant: "success", labelKey: "analytics.status.good" },
  warning: { icon: AlertTriangle, variant: "warning", labelKey: "analytics.status.attention" },
  danger: { icon: XCircle, variant: "destructive", labelKey: "analytics.status.critical" },
  neutral: { icon: Minus, variant: "default", labelKey: "analytics.status.stable" },
};

export const TONE_TEXT: Record<Tone, string> = {
  good: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
  neutral: "text-muted-foreground",
};

export const TONE_BORDER: Record<Tone, string> = {
  good: "border-l-success",
  warning: "border-l-warning",
  danger: "border-l-destructive",
  neutral: "border-l-border",
};

/** Status is always icon + label + colour, so it survives colour-blindness and greyscale print. */
export function AnalyticsStatusBadge({ tone, label }: { tone: Tone; label?: string }) {
  const { t } = useI18n();
  const { icon: Icon, variant, labelKey } = TONES[tone];
  return (
    <Badge variant={variant}>
      <Icon className="h-3 w-3" aria-hidden />
      {label ?? t(labelKey)}
    </Badge>
  );
}
