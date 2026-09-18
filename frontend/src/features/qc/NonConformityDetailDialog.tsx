import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ExternalLink } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { formatQuantity, productUnit } from "../../lib/units";
import { getNonConformity, type NonConformity } from "./api";

/**
 * A non-conformity, opened from wherever it was mentioned.
 *
 * The list showed a row per case and offered no way to look at one — the only
 * clickable thing was the button that acted on it, so reading a case meant
 * deciding about it. This is the read: what was rejected, how much, why, where
 * it went, and what was done with it, including the dispositions that only
 * existed inside the action dialog before.
 */
export function NonConformityDetailDialog({
  nonConformity,
  ofReference,
  products,
  uoms,
  locations,
  onClose,
}: {
  nonConformity: NonConformity;
  ofReference: string;
  products: { id: string; name: string; uom_id: string }[];
  uoms: { id: string; code: string; symbol?: string | null }[];
  locations: { id: string; name: string }[];
  onClose: () => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();

  // The list payload has no dispositions on it, and the dispositions are the
  // half of the story that says what actually happened to the product.
  const { data: full, isLoading } = useQuery({
    queryKey: ["qc", "non-conformity", nonConformity.id],
    queryFn: () => getNonConformity(session!.token, nonConformity.id),
  });

  const productName = (id: string | null) =>
    (id && products.find((p) => p.id === id)?.name) || id || "—";
  const locationName = (id: string | null) =>
    (id && locations.find((l) => l.id === id)?.name) || id || "—";
  const unit = productUnit(nonConformity.product_id, products, uoms);

  const rows: { label: string; value: React.ReactNode }[] = [
    { label: t("qc.nc.column.product"), value: productName(nonConformity.product_id) },
    {
      label: t("qc.nc.column.quantity"),
      value: formatQuantity(nonConformity.quantity, unit),
    },
    { label: t("qc.nc.column.defect"), value: nonConformity.defect_type },
    {
      label: t("qc.nc.column.severity"),
      value: t(`qc.nc.severity.${nonConformity.severity}` as Parameters<typeof t>[0]),
    },
    { label: t("qc.nc.field.pulledFrom"), value: locationName(nonConformity.source_location_id) },
    { label: t("qc.nc.field.quarantine"), value: locationName(nonConformity.quarantine_location_id) },
    { label: t("qc.nc.field.description"), value: nonConformity.description || "—" },
    { label: t("qc.nc.field.correctiveAction"), value: nonConformity.corrective_action || "—" },
    { label: t("qc.nc.field.raisedAt"), value: nonConformity.raised_at?.slice(0, 16).replace("T", " ") || "—" },
    { label: t("qc.nc.field.closedAt"), value: nonConformity.closed_at?.slice(0, 16).replace("T", " ") || "—" },
  ];

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {nonConformity.reference}
            <StatusBadge status={nonConformity.status} />
          </DialogTitle>
          <DialogDescription>{ofReference}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
            {rows.map((row) => (
              <div key={row.label} className="flex items-baseline justify-between gap-3">
                <dt className="text-sm text-muted-foreground">{row.label}</dt>
                <dd className="text-right text-sm font-medium">{row.value}</dd>
              </div>
            ))}
          </dl>

          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("qc.nc.dispositions")}
            </p>
            {isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : (full?.dispositions ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("qc.nc.dispositionsEmpty")}</p>
            ) : (
              <ul className="space-y-1.5">
                {full!.dispositions.map((line, index) => (
                  <motion.li
                    key={`${line.component}:${line.disposition}:${index}`}
                    initial={{ opacity: 0, scale: 0.94 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1], delay: Math.min(index, 8) * 0.03 }}
                    className="flex flex-wrap items-baseline gap-2 rounded-lg border border-border p-2 text-sm"
                  >
                    <Badge variant="outline">
                      {t(`qc.nc.component.${line.component}` as Parameters<typeof t>[0])}
                    </Badge>
                    <span className="text-muted-foreground">
                      {t(`qc.nc.disposition.${line.disposition}` as Parameters<typeof t>[0])}
                    </span>
                    <span className="ml-auto tabular-nums">
                      {formatQuantity(line.quantity, line.unit)}
                    </span>
                    {line.note && <span className="w-full text-xs text-muted-foreground">{line.note}</span>}
                  </motion.li>
                ))}
              </ul>
            )}
          </div>

          {/* The OF is the case's context: which run produced the rejected
              product, and what else that run reported. */}
          <Button asChild variant="outline" size="sm">
            <Link to={`/production/work-orders/${nonConformity.of_id}`}>
              <ExternalLink className="h-3.5 w-3.5" />
              {t("qc.nc.openOf")}
            </Link>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
