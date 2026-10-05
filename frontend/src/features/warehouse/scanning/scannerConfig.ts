export type ScannerMode = "keyboard" | "serial";
export type ScannerTerminator = "Enter" | "Tab" | "none";

export interface ScannerConfig {
  mode: ScannerMode;
  terminator: ScannerTerminator;
  stripPrefix: string;
  stripSuffix: string;
  minLength: number;
  // Serial-only fields.
  baudRate?: number;
  usbVendorId?: number;
  usbProductId?: number;
  portLabel?: string;
  configuredAt: string;
}

const STORAGE_KEY = "sonalim-erp.scanner-config";

// Scanner configuration is tied to the physical device plugged into this
// workstation, not to whoever is logged in -- unlike table-column
// preferences it deliberately lives in localStorage rather than following
// the user's account across devices.
export function loadScannerConfig(): ScannerConfig | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ScannerConfig;
  } catch {
    return null;
  }
}

export function saveScannerConfig(config: ScannerConfig): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // Private browsing / blocked site data -- the wizard still works this
    // session, it just won't be remembered next time.
  }
}

export function clearScannerConfig(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
