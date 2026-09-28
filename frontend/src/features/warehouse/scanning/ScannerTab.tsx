import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { CheckCircle2, ChevronDown, MapPin, Package, RefreshCw, ScanLine, Trash2, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { useProductCatalog } from "../../products/catalog";
import { listLocations } from "../api";
import { clearScannerConfig, loadScannerConfig, type ScannerConfig } from "./scannerConfig";
import { applyScanTransform, useBarcodeCapture, type CapturedScan } from "./useBarcodeScanner";
import { closeSerialPort, reacquireSerialPort, type MinimalSerialPort } from "./serialPort";
import { ScannerWizard } from "./ScannerWizard";
import { BarcodesPanel } from "./BarcodesPanel";
import { resolveScan, scanResolveQueryKey, type ScanResolution } from "./barcodesApi";

const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;

interface ScanEntry {
  key: string;
  value: string;
  timestamp: number;
  // "pending" while the server resolves the read; null when nothing matched.
  match: { type: "product" | "location" | "lot"; label: string } | null | "pending";
}

export function ScannerTab() {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const { products } = useProductCatalog();
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const queryClient = useQueryClient();

  const [config, setConfig] = useState<ScannerConfig | null>(() => loadScannerConfig());
  const [wizardOpen, setWizardOpen] = useState(false);
  const [scans, setScans] = useState<ScanEntry[]>([]);
  const [serialPort, setSerialPort] = useState<MinimalSerialPort | null>(null);
  const [serialConnectFailed, setSerialConnectFailed] = useState(false);
  const serialPortRef = useRef<MinimalSerialPort | null>(null);

  useEffect(() => {
    if (!config || config.mode !== "serial") return;
    let cancelled = false;
    setSerialConnectFailed(false);
    (async () => {
      const port = await reacquireSerialPort(config.usbVendorId, config.usbProductId);
      if (!port) {
        if (!cancelled) setSerialConnectFailed(true);
        return;
      }
      try {
        await port.open({ baudRate: config.baudRate ?? 9600 });
      } catch {
        if (!cancelled) setSerialConnectFailed(true);
        return;
      }
      if (cancelled) {
        await closeSerialPort(port);
        return;
      }
      serialPortRef.current = port;
      setSerialPort(port);
    })();
    return () => {
      cancelled = true;
      if (serialPortRef.current) {
        closeSerialPort(serialPortRef.current);
        serialPortRef.current = null;
      }
      setSerialPort(null);
    };
  }, [config?.mode, config?.usbVendorId, config?.usbProductId, config?.baudRate]);

  const describeResolution = useCallback(
    (resolution: ScanResolution): ScanEntry["match"] => {
      const productName = (id: string) => products.find((p) => p.id === id)?.name ?? id;
      switch (resolution.kind) {
        case "product": {
          const quantity = resolution.quantity !== 1 ? ` ×${resolution.quantity}` : "";
          const lot = resolution.lot_number ? ` · ${resolution.lot_number}` : "";
          return { type: "product", label: `${productName(resolution.product_id)}${quantity}${lot}` };
        }
        case "location":
          return { type: "location", label: locations.find((l) => l.id === resolution.location_id)?.name ?? resolution.location_id };
        case "lot":
          return { type: "lot", label: `${t("warehouse.scanner.live.match.lot")} · ${productName(resolution.product_id)}` };
        default:
          return null;
      }
    },
    [products, locations, t],
  );

  const handleCapture = useCallback(
    (scan: CapturedScan) => {
      if (!config) return;
      const value = applyScanTransform(scan.raw, {
        stripPrefix: config.stripPrefix,
        stripSuffix: config.stripSuffix,
        minLength: config.minLength,
      });
      if (value === null) return;
      const key = `${scan.timestamp}-${value}`;
      setScans((prev) => [{ key, value, timestamp: scan.timestamp, match: "pending" as const }, ...prev].slice(0, 20));
      // The server owns what a read means (GS1 labels, carton GTINs, SKUs,
      // location codes, lot numbers) so every scanning screen agrees.
      queryClient
        .fetchQuery({ queryKey: scanResolveQueryKey(value), queryFn: () => resolveScan(token, value), staleTime: 30_000 })
        .then((resolution) => {
          const match = describeResolution(resolution);
          setScans((prev) => prev.map((entry) => (entry.key === key ? { ...entry, match } : entry)));
        })
        .catch(() => setScans((prev) => prev.map((entry) => (entry.key === key ? { ...entry, match: null } : entry))));
    },
    [config, queryClient, token, describeResolution],
  );

  useBarcodeCapture({
    active: config?.mode === "keyboard",
    mode: "keyboard",
    terminator: config?.terminator,
    onCapture: handleCapture,
  });
  useBarcodeCapture({
    active: config?.mode === "serial" && serialPort !== null,
    mode: "serial",
    serialPort,
    onCapture: handleCapture,
  });

  const handleClear = () => {
    clearScannerConfig();
    setConfig(null);
    setScans([]);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScanLine className="h-4 w-4 text-primary" />
            {t("warehouse.scanner.title")}
          </CardTitle>
          {config ? (
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setWizardOpen(true)}>
                <RefreshCw className="h-3.5 w-3.5" />
                {t("warehouse.scanner.reconfigure")}
              </Button>
              <Button variant="ghost" size="sm" onClick={handleClear}>
                <Trash2 className="h-3.5 w-3.5" />
                {t("warehouse.scanner.clear")}
              </Button>
            </div>
          ) : (
            <Button size="sm" onClick={() => setWizardOpen(true)}>
              {t("warehouse.scanner.runWizard")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {!config ? (
            <p className="text-sm text-muted-foreground">{t("warehouse.scanner.notConfigured.description")}</p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-4">
              <SummaryField label={t("warehouse.scanner.summary.mode")} value={t(config.mode === "keyboard" ? "warehouse.scanner.summary.mode.keyboard" : "warehouse.scanner.summary.mode.serial")} />
              {config.mode === "keyboard" ? (
                <SummaryField
                  label={t("warehouse.scanner.summary.terminator")}
                  value={t(
                    config.terminator === "Enter"
                      ? "warehouse.scanner.summary.terminator.enter"
                      : config.terminator === "Tab"
                        ? "warehouse.scanner.summary.terminator.tab"
                        : "warehouse.scanner.summary.terminator.none",
                  )}
                />
              ) : (
                <SummaryField label={t("warehouse.scanner.summary.baudRate")} value={`${config.baudRate ?? "—"}`} />
              )}
              <SummaryField label={t("warehouse.scanner.summary.minLength")} value={`${config.minLength}`} />
            </dl>
          )}
          {config?.mode === "serial" && serialConnectFailed && (
            <p className="mt-3 text-sm text-destructive">{t("warehouse.scanner.live.connectionFailed")}</p>
          )}
          {config?.mode === "serial" && !serialConnectFailed && !serialPort && (
            <p className="mt-3 text-sm text-muted-foreground">{t("warehouse.scanner.live.connecting")}</p>
          )}
        </CardContent>
      </Card>

      {config && (
        <Card>
          <CardHeader>
            <CardTitle>{t("warehouse.scanner.live.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">{t("warehouse.scanner.live.description")}</p>
            {scans.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">{t("warehouse.scanner.live.empty")}</p>
            ) : (
              <ul className="space-y-1.5">
                {scans.map((scan) => (
                  <motion.li
                    key={scan.key}
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
                  >
                    <span className="truncate font-mono">{scan.value}</span>
                    {scan.match === "pending" ? (
                      <span className="shrink-0 text-muted-foreground">…</span>
                    ) : scan.match ? (
                      <span className="flex shrink-0 items-center gap-1.5 text-success">
                        {scan.match.type === "product" ? <Package className="h-3.5 w-3.5" /> : <MapPin className="h-3.5 w-3.5" />}
                        <span className="max-w-[10rem] truncate">{scan.match.label}</span>
                        <CheckCircle2 className="h-3.5 w-3.5" />
                      </span>
                    ) : (
                      <span className="flex shrink-0 items-center gap-1.5 text-muted-foreground">
                        <XCircle className="h-3.5 w-3.5" />
                        {t("warehouse.scanner.live.match.none")}
                      </span>
                    )}
                  </motion.li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      <BarcodesPanel />

      <HelpFaq />

      <ScannerWizard open={wizardOpen} onOpenChange={setWizardOpen} onSaved={() => setConfig(loadScannerConfig())} />
    </div>
  );
}

function SummaryField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

const FAQ_KEYS = ["wrongField", "nothingHappens", "notListed", "browser", "bluetooth"] as const;

function HelpFaq() {
  const { t } = useI18n();
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("warehouse.scanner.help.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5 text-sm">
          <p className="font-medium">{t("warehouse.scanner.help.install.title")}</p>
          <p className="text-muted-foreground">{t("warehouse.scanner.help.install.keyboard")}</p>
          <p className="text-muted-foreground">{t("warehouse.scanner.help.install.serial")}</p>
        </div>
        <div className="divide-y divide-border rounded-md border border-border">
          {FAQ_KEYS.map((id) => {
            const isOpen = openId === id;
            return (
              <div key={id}>
                <button
                  type="button"
                  onClick={() => setOpenId(isOpen ? null : id)}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left text-sm font-medium"
                >
                  {t(`warehouse.scanner.help.faq.${id}.q`)}
                  <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
                </button>
                {isOpen && <p className="px-3 pb-2.5 text-sm text-muted-foreground">{t(`warehouse.scanner.help.faq.${id}.a`)}</p>}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
