// Minimal Chrome DevTools Protocol client for the brand scripts: a private
// headless Chrome on its own port and profile (other sessions share the
// Playwright browser), driven over the WebSocket that Node 22+ has built in.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const CHROME = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function launchChrome({ port = 9344, flags = [] } = {}) {
  const profile = mkdtempSync(join(tmpdir(), "sonalim-brand-"));
  const proc = spawn(
    CHROME,
    [
      "--headless=new",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      "--use-angle=swiftshader",
      "--enable-unsafe-swiftshader",
      "--ignore-gpu-blocklist",
      "--hide-scrollbars",
      ...flags,
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  let wsUrl = null;
  for (let i = 0; i < 50 && !wsUrl; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      wsUrl = targets.find((t) => t.type === "page")?.webSocketDebuggerUrl ?? null;
    } catch {
      // Chrome is not listening yet.
    }
    if (!wsUrl) await sleep(200);
  }
  if (!wsUrl) {
    proc.kill();
    throw new Error(`Chrome did not open a page on port ${port} (CHROME=${CHROME})`);
  }
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    const waiter = pending.get(msg.id);
    if (!waiter) return;
    pending.delete(msg.id);
    if (msg.error) waiter.reject(new Error(msg.error.message));
    else waiter.resolve(msg.result);
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const n = ++id;
      pending.set(n, { resolve, reject });
      ws.send(JSON.stringify({ id: n, method, params }));
    });
  /** Evaluates `expression` in the page, awaiting a promise, and returns its JSON value. */
  const evaluate = async (expression) => {
    const { result, exceptionDetails } = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
    return result.value;
  };
  /** Re-evaluates `expression` until it is truthy (a navigation may replace the page in between). */
  const waitFor = async (expression, timeoutMs = 60000) => {
    const end = Date.now() + timeoutMs;
    for (;;) {
      try {
        const value = await evaluate(expression);
        if (value) return value;
      } catch {
        // The page is still loading.
      }
      if (Date.now() > end) throw new Error(`timed out waiting for: ${expression}`);
      await sleep(200);
    }
  };
  const close = () => {
    ws.close();
    proc.kill();
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {
      // Chrome may still hold the profile for a moment on Windows.
    }
  };
  return { send, evaluate, waitFor, close };
}
