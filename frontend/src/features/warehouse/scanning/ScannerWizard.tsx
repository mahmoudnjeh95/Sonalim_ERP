import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronLeft, Keyboard, Loader2, Usb } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { applyScanTransform, looksLikeScanner, useBarcodeCapture, type CapturedScan } from "./useBarcodeScanner";
import { detectBaudRate, isSerialSupported, requestSerialPort } from "./serialPort";
import { saveScannerConfig, type ScannerConfig, type ScannerMode, type ScannerTerminator } from "./scannerConfig";

type Step = "connection" | "serial-pick" | "serial-test" | "keyboard-test" | "configure" | "confirm";

interface Draft {
  mode: ScannerMode;
  terminator: ScannerTerminator;
  stripPrefix: string;
  stripSuffix: string;
  minLength: number;
  baudRate?: number;
  usbVendorId?: number;
  usbProductId?: number;
  portLabel?: string;
}

// AIM symbology identifiers (e.g. "]C1" for Code 128, "]E0" for EAN) are a
// common leading artifact -- worth suggesting as a default strip so the
// configured value matches the plain code printed on the label.
function suggestPrefixStrip(raw: string): string {
  return /^\][A-Za-z]\d/.test(raw) ? raw.slice(0, 3) : "";
}

export function ScannerWizard({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [step, setStep] = useState<Step>("connection");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [capture, setCapture] = useState<CapturedScan | null>(null);
  const [serialAttemptRate, setSerialAttemptRate] = useState<number | null>(null);
  const [serialStatus, setSerialStatus] = useState<"idle" | "trying" | "failed">("idle");

  useEffect(() => {
    if (!open) {
      setStep("connection");
      setDraft(null);
      setCapture(null);
      setSerialStatus("idle");
    }
  }, [open]);

  const handleKeyboardCapture = useCallback((scan: CapturedScan) => {
    setCapture(scan);
    setDraft((prev) =>
      prev && {
        ...prev,
        terminator: scan.terminator ?? "none",
        stripPrefix: suggestPrefixStrip(scan.raw),
        minLength: Math.max(1, scan.raw.length - suggestPrefixStrip(scan.raw).length),
      },
    );
    setStep("configure");
  }, []);

  useBarcodeCapture({
    active: open && step === "keyboard-test",
    mode: "keyboard",
    onCapture: handleKeyboardCapture,
  });

  const chooseKeyboard = () => {
    setDraft({ mode: "keyboard", terminator: "Enter", stripPrefix: "", stripSuffix: "", minLength: 1 });
    setCapture(null);
    setStep("keyboard-test");
  };

  const chooseSerial = () => {
    setDraft({ mode: "serial", terminator: "none", stripPrefix: "", stripSuffix: "", minLength: 1 });
    setCapture(null);
    setStep("serial-pick");
  };

  const pickSerialDevice = async () => {
    try {
      const port = await requestSerialPort();
      setStep("serial-test");
      setSerialStatus("trying");
      const result = await detectBaudRate(port, (rate) => setSerialAttemptRate(rate));
      if (result) {
        const info = port.getInfo();
        setDraft((prev) =>
          prev && {
            ...prev,
            baudRate: result.baudRate,
            usbVendorId: info.usbVendorId,
            usbProductId: info.usbProductId,
            portLabel:
              info.usbVendorId !== undefined && info.usbProductId !== undefined
                ? `USB ${info.usbVendorId.toString(16)}:${info.usbProductId.toString(16)}`
                : undefined,
          },
        );
        setCapture({ raw: result.raw, terminator: null, timestamp: Date.now(), interKeyMs: [] });
        setStep("configure");
      } else {
        setSerialStatus("failed");
      }
    } catch {
      // Picker cancelled or permission denied -- stay put, let the user retry.
    }
  };

  if (!draft) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("warehouse.scanner.wizard.title")}</DialogTitle>
            <DialogDescription>{t("warehouse.scanner.wizard.step.connectionType.description")}</DialogDescription>
          </DialogHeader>
          <ConnectionChoice onChooseKeyboard={chooseKeyboard} onChooseSerial={chooseSerial} />
        </DialogContent>
      </Dialog>
    );
  }

  const preview = capture
    ? applyScanTransform(capture.raw, { stripPrefix: draft.stripPrefix, stripSuffix: draft.stripSuffix, minLength: 0 })
    : null;
  const isValid = preview !== null && preview.length >= draft.minLength;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("warehouse.scanner.wizard.title")}</DialogTitle>
        </DialogHeader>

        {step === "serial-pick" && (
          <div className="space-y-4">
            <StepHeading title={t("warehouse.scanner.wizard.step.serialPick.title")} description={t("warehouse.scanner.wizard.step.serialPick.description")} />
            <Button onClick={pickSerialDevice} className="w-full">
              <Usb className="h-4 w-4" />
              {t("warehouse.scanner.wizard.serialPick.button")}
            </Button>
          </div>
        )}

        {step === "serial-test" && (
          <div className="space-y-4">
            <StepHeading title={t("warehouse.scanner.wizard.step.serialTest.title")} description={t("warehouse.scanner.wizard.step.serialTest.description")} />
            {serialStatus === "trying" && (
              <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>
                  {t("warehouse.scanner.wizard.serialTest.trying")} {serialAttemptRate ?? "…"}{" "}
                  {t("warehouse.scanner.wizard.serialTest.baudUnit")}
                </span>
              </div>
            )}
            {serialStatus === "failed" && (
              <div className="space-y-3">
                <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{t("warehouse.scanner.wizard.serialTest.failed")}</span>
                </div>
                <Button variant="outline" onClick={pickSerialDevice} className="w-full">
                  {t("warehouse.scanner.wizard.serialTest.retry")}
                </Button>
              </div>
            )}
          </div>
        )}

        {step === "keyboard-test" && (
          <div className="space-y-4">
            <StepHeading title={t("warehouse.scanner.wizard.step.keyboardTest.title")} description={t("warehouse.scanner.wizard.step.keyboardTest.description")} />
            <div className="flex h-24 items-center justify-center rounded-md border-2 border-dashed border-border bg-muted/30 text-sm text-muted-foreground">
              {t("warehouse.scanner.wizard.keyboardTest.placeholder")}
            </div>
          </div>
        )}

        {step === "configure" && capture && (
          <div className="space-y-4">
            <StepHeading title={t("warehouse.scanner.wizard.step.configure.title")} description={t("warehouse.scanner.wizard.step.configure.description")} />

            <div className="flex items-center gap-2 rounded-md border border-success/30 bg-success-soft px-3 py-2 text-sm text-success">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>
                {draft.mode === "keyboard" && !looksLikeScanner(capture.interKeyMs)
                  ? t("warehouse.scanner.wizard.keyboardTest.looksSlow")
                  : t("warehouse.scanner.wizard.keyboardTest.looksGood")}
              </span>
            </div>

            <div>
              <Label>{t("warehouse.scanner.wizard.configure.rawValue")}</Label>
              <p className="mt-1 break-all rounded-md border border-border bg-muted/40 px-3 py-1.5 font-mono text-sm">{capture.raw}</p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="scanner-strip-prefix">{t("warehouse.scanner.wizard.configure.stripPrefix")}</Label>
                <Input
                  id="scanner-strip-prefix"
                  value={draft.stripPrefix}
                  onChange={(e) => setDraft({ ...draft, stripPrefix: e.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="scanner-strip-suffix">{t("warehouse.scanner.wizard.configure.stripSuffix")}</Label>
                <Input
                  id="scanner-strip-suffix"
                  value={draft.stripSuffix}
                  onChange={(e) => setDraft({ ...draft, stripSuffix: e.target.value })}
                />
              </div>
            </div>

            <div>
              <Label htmlFor="scanner-min-length">{t("warehouse.scanner.wizard.configure.minLength")}</Label>
              <Input
                id="scanner-min-length"
                type="number"
                min={1}
                value={draft.minLength}
                onChange={(e) => setDraft({ ...draft, minLength: Math.max(1, Number(e.target.value) || 1) })}
              />
            </div>

            <div>
              <Label>{t("warehouse.scanner.wizard.configure.preview")}</Label>
              <p
                className={cn(
                  "mt-1 break-all rounded-md border px-3 py-1.5 font-mono text-sm",
                  isValid ? "border-border bg-background" : "border-destructive/40 bg-destructive-soft text-destructive",
                )}
              >
                {preview || "—"}
              </p>
            </div>

            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setStep(draft.mode === "keyboard" ? "keyboard-test" : "serial-pick")}
                className="flex-1"
              >
                <ChevronLeft className="h-4 w-4" />
                {t("warehouse.scanner.wizard.nav.back")}
              </Button>
              <Button onClick={() => setStep("confirm")} disabled={!isValid} className="flex-1">
                {t("warehouse.scanner.wizard.nav.next")}
              </Button>
            </div>
          </div>
        )}

        {step === "confirm" && (
          <div className="space-y-4">
            <StepHeading title={t("warehouse.scanner.wizard.step.confirm.title")} description={t("warehouse.scanner.wizard.step.confirm.description")} />
            <dl className="space-y-1.5 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
              <SummaryRow
                label={t("warehouse.scanner.summary.mode")}
                value={t(draft.mode === "keyboard" ? "warehouse.scanner.summary.mode.keyboard" : "warehouse.scanner.summary.mode.serial")}
              />
              {draft.mode === "keyboard" && (
                <SummaryRow
                  label={t("warehouse.scanner.summary.terminator")}
                  value={t(
                    draft.terminator === "Enter"
                      ? "warehouse.scanner.summary.terminator.enter"
                      : draft.terminator === "Tab"
                        ? "warehouse.scanner.summary.terminator.tab"
                        : "warehouse.scanner.summary.terminator.none",
                  )}
                />
              )}
              {draft.mode === "serial" && draft.baudRate && (
                <SummaryRow label={t("warehouse.scanner.summary.baudRate")} value={`${draft.baudRate}`} />
              )}
              <SummaryRow label={t("warehouse.scanner.summary.minLength")} value={`${draft.minLength}`} />
            </dl>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep("configure")} className="flex-1">
                <ChevronLeft className="h-4 w-4" />
                {t("warehouse.scanner.wizard.nav.back")}
              </Button>
              <Button
                onClick={() => {
                  const config: ScannerConfig = { ...draft, configuredAt: new Date().toISOString() };
                  saveScannerConfig(config);
                  onSaved();
                  onOpenChange(false);
                }}
                className="flex-1"
              >
                {t("warehouse.scanner.wizard.confirm.save")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ConnectionChoice({ onChooseKeyboard, onChooseSerial }: { onChooseKeyboard: () => void; onChooseSerial: () => void }) {
  const { t } = useI18n();
  const serialSupported = isSerialSupported();
  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onChooseKeyboard}
        className="flex w-full items-start gap-3 rounded-lg border border-border p-4 text-left transition-colors hover:border-primary/40 hover:bg-muted/40"
      >
        <Keyboard className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
        <span>
          <span className="block text-sm font-medium">{t("warehouse.scanner.wizard.connectionType.keyboard.title")}</span>
          <span className="mt-0.5 block text-sm text-muted-foreground">{t("warehouse.scanner.wizard.connectionType.keyboard.description")}</span>
        </span>
      </button>
      <button
        type="button"
        onClick={onChooseSerial}
        disabled={!serialSupported}
        className="flex w-full items-start gap-3 rounded-lg border border-border p-4 text-left transition-colors hover:border-primary/40 hover:bg-muted/40 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Usb className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
        <span>
          <span className="block text-sm font-medium">{t("warehouse.scanner.wizard.connectionType.serial.title")}</span>
          <span className="mt-0.5 block text-sm text-muted-foreground">
            {serialSupported
              ? t("warehouse.scanner.wizard.connectionType.serial.description")
              : t("warehouse.scanner.wizard.connectionType.serial.unsupported")}
          </span>
        </span>
      </button>
    </div>
  );
}

function StepHeading({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
