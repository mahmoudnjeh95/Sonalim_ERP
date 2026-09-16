import { useState } from "react";
import { isRouteErrorResponse, Link, useNavigate, useRouteError } from "react-router-dom";
import { RotateCw } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { Card, CardContent } from "../components/ui/card";
import ErrorIllustration from "../assets/illustrations/empty-states/empty-error.svg?react";

// Errors thrown while rendering a route land here instead of tearing down the
// whole app (react-router's default crash screen). Placed on each leaf route
// rather than only on the layout route, so a broken page unmounts inside
// AppLayout's <Outlet /> and the sidebar/nav stay usable.
export function RouteErrorBoundary() {
  const error = useRouteError();
  const navigate = useNavigate();
  const { t } = useI18n();
  const [showDetails, setShowDetails] = useState(false);

  if (isRouteErrorResponse(error) && error.status === 404) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <ErrorIllustration className="h-8 w-8 text-muted-foreground" />
          <div>
            <p className="text-base font-semibold">{t("error.notFound.title")}</p>
            <p className="text-sm text-muted-foreground">{t("error.notFound.description")}</p>
          </div>
          <Link
            to="/crm"
            className="mt-1 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            {t("error.boundary.goHome")}
          </Link>
        </CardContent>
      </Card>
    );
  }

  const detail =
    error instanceof Error
      ? error.stack ?? error.message
      : isRouteErrorResponse(error)
        ? `${error.status} ${error.statusText}`
        : String(error);

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <ErrorIllustration className="h-8 w-8 text-destructive" />
        <div>
          <p className="text-base font-semibold">{t("error.boundary.title")}</p>
          <p className="text-sm text-muted-foreground">{t("error.boundary.description")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate(0)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            <RotateCw className="h-3.5 w-3.5" />
            {t("error.boundary.retry")}
          </button>
          <Link
            to="/crm"
            className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
          >
            {t("error.boundary.goHome")}
          </Link>
        </div>
        <button
          type="button"
          onClick={() => setShowDetails((v) => !v)}
          className="text-xs text-muted-foreground underline underline-offset-2"
        >
          {t("error.boundary.details")}
        </button>
        {showDetails && (
          <pre className="max-w-full overflow-x-auto rounded-lg bg-muted p-3 text-left text-xs text-muted-foreground">
            {detail}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}
