// Minimal local surface of the WebSerial API -- narrower than the full spec,
// and declared locally rather than as a global ambient type so it can't
// clash with a future TS lib.dom update that adds its own Serial types.
export interface MinimalSerialPort {
  open(options: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  readonly readable: ReadableStream<Uint8Array> | null;
  readonly writable: WritableStream<Uint8Array> | null;
  getInfo(): { usbVendorId?: number; usbProductId?: number };
}

interface MinimalSerial {
  requestPort(): Promise<MinimalSerialPort>;
  getPorts(): Promise<MinimalSerialPort[]>;
}

function getSerial(): MinimalSerial | undefined {
  return (navigator as unknown as { serial?: MinimalSerial }).serial;
}

export function isSerialSupported(): boolean {
  return getSerial() !== undefined;
}

// Opens the browser's native device picker -- the one case in this feature
// where "detection" means real OS-level hardware enumeration, not a
// behavioral guess.
export async function requestSerialPort(): Promise<MinimalSerialPort> {
  const serial = getSerial();
  if (!serial) throw new Error("WebSerial is not supported in this browser");
  return serial.requestPort();
}

// Re-acquires a previously authorized port without prompting again --
// permission grants persist per origin, so a returning visit shouldn't
// have to re-pick the device.
export async function reacquireSerialPort(
  usbVendorId: number | undefined,
  usbProductId: number | undefined,
): Promise<MinimalSerialPort | null> {
  const serial = getSerial();
  if (!serial || usbVendorId === undefined || usbProductId === undefined) return null;
  const ports = await serial.getPorts();
  return (
    ports.find((port) => {
      const info = port.getInfo();
      return info.usbVendorId === usbVendorId && info.usbProductId === usbProductId;
    }) ?? null
  );
}

export const COMMON_BAUD_RATES = [9600, 115200, 19200, 57600] as const;

export async function closeSerialPort(port: MinimalSerialPort): Promise<void> {
  try {
    await port.close();
  } catch {
    // already closed
  }
}

interface ReadStep {
  value?: Uint8Array;
  done: boolean;
}

// Reads until the next line terminator or the timeout, whichever comes
// first -- used both to probe candidate baud rates during setup and to
// confirm a test scan came through cleanly.
export async function readOneLine(port: MinimalSerialPort, timeoutMs = 4000): Promise<string | null> {
  if (!port.readable) return null;
  const reader = port.readable.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const deadline = Date.now() + timeoutMs;
  try {
    while (Date.now() < deadline) {
      const remaining = deadline - Date.now();
      const timeout = new Promise<ReadStep>((resolve) =>
        window.setTimeout(() => resolve({ value: undefined, done: true }), Math.max(remaining, 0)),
      );
      const { value, done } = await Promise.race<ReadStep>([reader.read(), timeout]);
      if (done) break;
      if (value) buffer += decoder.decode(value, { stream: true });
      const newlineIndex = buffer.search(/[\r\n]/);
      if (newlineIndex >= 0) return buffer.slice(0, newlineIndex);
    }
    return null;
  } finally {
    reader.releaseLock();
  }
}

// Tries each common baud rate in turn, asking the caller to trigger a scan
// once the port is open, and returns the first one that yields a readable
// line. Closes every port it opens along the way, including the winner --
// callers reopen at the confirmed rate for continuous use afterwards.
export async function detectBaudRate(
  port: MinimalSerialPort,
  onAttempt: (baudRate: number) => void,
  perAttemptTimeoutMs = 6000,
): Promise<{ baudRate: number; raw: string } | null> {
  for (const baudRate of COMMON_BAUD_RATES) {
    onAttempt(baudRate);
    try {
      await port.open({ baudRate });
    } catch {
      continue;
    }
    const raw = await readOneLine(port, perAttemptTimeoutMs);
    await closeSerialPort(port);
    if (raw && raw.trim().length > 0) {
      return { baudRate, raw: raw.trim() };
    }
  }
  return null;
}
