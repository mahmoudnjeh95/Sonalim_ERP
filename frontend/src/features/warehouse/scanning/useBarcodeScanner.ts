import { useEffect, useRef } from "react";
import type { ScannerMode, ScannerTerminator } from "./scannerConfig";
import { readOneLine, type MinimalSerialPort } from "./serialPort";

export interface CapturedScan {
  raw: string;
  /** Which terminator ended the burst -- null for serial reads, which are already line-framed. */
  terminator: ScannerTerminator | null;
  timestamp: number;
  /** Gaps between consecutive keystrokes, in ms -- empty for serial. Used for the "does this look like a scanner" heuristic. */
  interKeyMs: number[];
}

// A gap larger than this between keystrokes reads as human typing, not a
// scanner burst, and restarts the buffer. Real scanners emit characters a
// few ms apart; even a fast typist rarely holds under this consistently.
const MAX_INTER_KEY_MS = 50;
// When the terminator is "none" (or during discovery, as a fallback), this
// idle gap after the last keystroke ends the burst.
const IDLE_FLUSH_MS = 150;

export function looksLikeScanner(interKeyMs: number[]): boolean {
  if (interKeyMs.length < 2) return true; // too short a sample to call it human typing
  const avg = interKeyMs.reduce((sum, ms) => sum + ms, 0) / interKeyMs.length;
  return avg <= MAX_INTER_KEY_MS;
}

interface UseBarcodeCaptureOptions {
  active: boolean;
  mode: ScannerMode;
  /** Omit during wizard discovery to accept Enter, Tab, or an idle gap and report whichever fired. */
  terminator?: ScannerTerminator;
  /** Required, and must already be open, for mode: "serial". */
  serialPort?: MinimalSerialPort | null;
  onCapture: (scan: CapturedScan) => void;
}

export function useBarcodeCapture({ active, mode, terminator, serialPort, onCapture }: UseBarcodeCaptureOptions) {
  const onCaptureRef = useRef(onCapture);
  onCaptureRef.current = onCapture;

  useEffect(() => {
    if (!active || mode !== "keyboard") return;

    let buffer = "";
    let lastKeyTime = 0;
    const interKeyMs: number[] = [];
    let idleTimer: number | undefined;

    const flush = (firedTerminator: ScannerTerminator) => {
      window.clearTimeout(idleTimer);
      if (buffer.length > 0) {
        onCaptureRef.current({ raw: buffer, terminator: firedTerminator, timestamp: Date.now(), interKeyMs: [...interKeyMs] });
      }
      buffer = "";
      lastKeyTime = 0;
      interKeyMs.length = 0;
    };

    const scheduleIdleFlush = () => {
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => flush("none"), IDLE_FLUSH_MS);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      const acceptsEnter = terminator === undefined || terminator === "Enter";
      const acceptsTab = terminator === undefined || terminator === "Tab";
      if (event.key === "Enter" && acceptsEnter) {
        event.preventDefault();
        flush("Enter");
        return;
      }
      if (event.key === "Tab" && acceptsTab) {
        event.preventDefault();
        flush("Tab");
        return;
      }
      if (event.key.length !== 1) return; // ignore modifiers/navigation keys
      const now = performance.now();
      if (lastKeyTime) {
        const gap = now - lastKeyTime;
        if (gap > MAX_INTER_KEY_MS && terminator === undefined) {
          // Discovery mode: a long gap looks like manual typing -- restart.
          buffer = "";
          interKeyMs.length = 0;
        } else {
          interKeyMs.push(gap);
        }
      }
      buffer += event.key;
      lastKeyTime = now;
      if (terminator === "none" || terminator === undefined) scheduleIdleFlush();
    };

    window.addEventListener("keydown", handleKeyDown, true);
    return () => {
      window.removeEventListener("keydown", handleKeyDown, true);
      window.clearTimeout(idleTimer);
    };
  }, [active, mode, terminator]);

  useEffect(() => {
    if (!active || mode !== "serial" || !serialPort) return;
    let cancelled = false;

    (async () => {
      while (!cancelled) {
        const raw = await readOneLine(serialPort, 5000);
        if (cancelled) break;
        if (raw && raw.trim().length > 0) {
          onCaptureRef.current({ raw: raw.trim(), terminator: null, timestamp: Date.now(), interKeyMs: [] });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [active, mode, serialPort]);
}

export function applyScanTransform(
  raw: string,
  options: { stripPrefix?: string; stripSuffix?: string; minLength?: number },
): string | null {
  let value = raw;
  if (options.stripPrefix && value.startsWith(options.stripPrefix)) {
    value = value.slice(options.stripPrefix.length);
  }
  if (options.stripSuffix && value.endsWith(options.stripSuffix)) {
    value = value.slice(0, value.length - options.stripSuffix.length);
  }
  value = value.trim();
  if (options.minLength && value.length < options.minLength) return null;
  return value;
}
