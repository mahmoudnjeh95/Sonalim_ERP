import SpinnerMark from "../../assets/animations/spinner-mark.svg?react";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";

interface AppLoaderProps {
  label?: string;
  className?: string;
  fullScreen?: boolean;
}

export function AppLoader({ label, className, fullScreen = false }: AppLoaderProps) {
  const { t } = useI18n();

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center gap-3 text-primary",
        fullScreen && "min-h-[60vh]",
        className,
      )}
    >
      <SpinnerMark className="h-10 w-10" />
      <span className="text-sm text-muted-foreground">{label ?? t("app.loading")}</span>
    </div>
  );
}
