import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { Truck } from "lucide-react";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { Card, CardContent } from "../../components/ui/card";
import { EmptyState } from "../../components/patterns/EmptyState";

function ComingSoonPage({
  icon,
  titleKey,
  subtitleKey,
  descriptionKey,
}: {
  icon: ReactNode;
  titleKey: TranslationKey;
  subtitleKey: TranslationKey;
  descriptionKey: TranslationKey;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t(titleKey)}</h1>
        <p className="text-sm text-muted-foreground">{t(subtitleKey)}</p>
      </motion.div>
      <Card>
        <CardContent className="p-0">
          <EmptyState icon={icon} title={t("nav.soon")} description={t(descriptionKey)} />
        </CardContent>
      </Card>
    </div>
  );
}


export function ShipmentsPage() {
  return (
    <ComingSoonPage
      icon={<Truck className="h-5 w-5" />}
      titleKey="shipments.title"
      subtitleKey="shipments.subtitle"
      descriptionKey="shipments.comingSoon.description"
    />
  );
}
