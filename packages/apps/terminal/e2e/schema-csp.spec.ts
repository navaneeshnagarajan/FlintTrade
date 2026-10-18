import { createWriteStream } from "node:fs";
import { fileURLToPath } from "node:url";
import fs from "node:fs/promises";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { test as base, expect, type Page } from "@playwright/test";
import { createSyntheticFixtureRegistry } from "./fixture-registry";

// Public source-only carrier; collection needs neither a private controller nor
// a running listener. The maintained default command builds the installed app.
const serverPath = fileURLToPath(new URL("../../../../tools/acceptance/csp_server.py", import.meta.url));
const test = base.extend<{ normalCore: void }>({
  normalCore: [async ({ context }, use, info) => {
    const key = createHash("sha256").update(info.testId).digest("hex");
    const python = process.env["FLINTTRADE_E2E_PYTHON"];
    if (!python) throw new Error("Explicit qualified CSP Python required; use the public acceptance carrier");
    const child = spawn(python, [serverPath, "--case-key", key, "--output", info.outputPath("normal-core")], { stdio: ["pipe", "pipe", "pipe"] });
    const log = createWriteStream(info.outputPath("normal-core.log"));
    child.stdout.pipe(log, { end: false }); child.stderr.pipe(log, { end: false });
    const lines = createInterface({ input: child.stdout });
    const exited = new Promise<{ code: number | null; signal: string | null }>((resolve, reject) => {
      child.once("error", reject);
      child.once("close", (code, signal) => { log.end(); resolve({ code, signal }); });
    });
    let readyTimer: ReturnType<typeof setTimeout> | undefined;
    try {
      await new Promise<void>((resolve, reject) => {
        readyTimer = setTimeout(() => reject(new Error("CSP factory readiness timeout")), 30000);
        lines.on("line", line => { if (line === "R33_CORE_READY") { clearTimeout(readyTimer); resolve(); } });
        void exited.then(result => reject(new Error("Factory exited before readiness: " + JSON.stringify(result))), reject);
      });
      await use();
    } finally {
      clearTimeout(readyTimer);
      await context.close();
      child.stdin.end("STOP\n");
      let stopTimer: ReturnType<typeof setTimeout> | undefined;
      try {
        const result = await Promise.race([exited, new Promise<never>((_, reject) => {
          stopTimer = setTimeout(() => reject(new Error("CSP factory shutdown timeout")), 30000);
        })]);
        expect(result).toEqual({ code: 0, signal: null });
        const shutdown: unknown = JSON.parse(await fs.readFile(info.outputPath("normal-core/shutdown.json"), "utf8"));
        expect(shutdown).toMatchObject({ admission_drained: true, listener_stopped: true, listener_closed_probe: true, remaining_threads: [] });
      } finally {
        clearTimeout(stopTimer); lines.close();
        if (child.exitCode === null && child.signalCode === null) { child.kill("SIGKILL"); await exited; }
      }
    }
  }, { auto: true, timeout: 60000 }],
});

async function observe(page: Page) {
  const reports: unknown[] = [];
  const consoleRows: unknown[] = [];
  const errors: string[] = [];
  const urls: string[] = [];
  page.on("request", request => {
    urls.push(request.url());
    if (new URL(request.url()).pathname === "/csp-report") reports.push(JSON.parse(request.postData() ?? "null"));
  });
  page.on("console", message => { consoleRows.push({ type: message.type(), text: message.text(), location: message.location() }); });
  page.on("pageerror", error => { errors.push(error.message); });
  await page.addInitScript(() => {
    const events: unknown[] = [];
    Object.defineProperty(window, "__r33CspEvents", { value: events });
    document.addEventListener("securitypolicyviolation", event => {
      events.push({ effectiveDirective: event.effectiveDirective, blockedURI: event.blockedURI, sourceFile: event.sourceFile, lineNumber: event.lineNumber, columnNumber: event.columnNumber, disposition: event.disposition });
    });
  });
  return { reports, consoleRows, errors, urls };
}
async function events(page: Page): Promise<unknown> {
  return page.evaluate(() => Reflect.get(window, "__r33CspEvents"));
}
async function openInstalledEntry(page: Page) {
  const response = await page.goto("/r33-csp-bootstrap-missing");
  expect(response?.status()).toBe(200);
  const headers = await response!.allHeaders();
  const csp = headers["content-security-policy"];
  expect(csp).toContain("script-src 'self' 'strict-dynamic' 'nonce-");
  expect(csp).toContain("report-uri /csp-report");
  expect(csp).not.toContain("'unsafe-eval'");
  expect(csp).not.toContain("'wasm-unsafe-eval'");
  await expect(page.getByRole("heading", { name: "Page not found", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  return headers;
}

test("cold installed production entry and strict schemas avoid CSP eval", async ({ page }, info) => {
  const registry = await createSyntheticFixtureRegistry(page, { name: info.title, frontendOrigin: "http://127.0.0.1:5173", closePageOnDispose: true });
  const observed = await observe(page);
  try {
    const headers = await openInstalledEntry(page);
    // The companion probe is a separately bundled parser control. It never sets
    // Zod configuration: the actual main entry must already have established it.
    const result: unknown = await page.evaluate(async () => {
      const path = "/assets/r33-schema-probe.js";
      const module: { checkSchemas(): Promise<unknown> } = await import(/* @vite-ignore */ path);
      return module.checkSchemas();
    });
    await info.attach("schema-checks", { body: JSON.stringify(result, null, 2), contentType: "application/json" });
    expect(result).toMatchObject({ jitless: true, valid: true, invalid: [false, false, false, false, false, false], asyncValid: true, asyncInvalid: false, absentPreserved: true, nullPreserved: true });
    await fs.writeFile(info.outputPath("headers.json"), JSON.stringify(headers, null, 2));
    await page.screenshot({ path: info.outputPath("installed-bootstrap.png") });
    expect(await events(page)).toEqual([]);
    expect(observed.reports).toEqual([]);
    expect(observed.errors).toEqual([]);
    expect(observed.urls.some(url => /\/assets\/vendor-forms-/.test(url))).toBe(true);
    expect(observed.urls.some(url => /\/assets\/Application-/.test(url))).toBe(true);
    registry.assertSatisfied();
  } finally {
    await fs.writeFile(info.outputPath("csp-observations.json"), JSON.stringify({ ...observed, violations: await events(page) }, null, 2));
    await registry.dispose();
  }
});

test("separate eval-negative control retains CSP enforcement and fatal registry", async ({ page }, info) => {
  const registry = await createSyntheticFixtureRegistry(page, { name: info.title, frontendOrigin: "http://127.0.0.1:5173", closePageOnDispose: true });
  const observed = await observe(page);
  let disposal: Error | undefined;
  try {
    await openInstalledEntry(page);
    expect(await events(page)).toEqual([]);
    expect(observed.reports).toEqual([]);
    // A real external script executes the negative control, not DevTools eval
    // (Runtime.evaluate can itself bypass CSP's eval prohibition).
    await page.evaluate(() => new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      const entry = document.querySelector<HTMLScriptElement>("script[nonce]");
      if (!entry?.nonce) throw new Error("Normal factory entry nonce missing");
      script.nonce = entry.nonce;
      script.src = "/assets/r33-eval-negative.js";
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("Negative control script did not load"));
      document.head.append(script);
    }));
    await expect.poll(() => observed.reports.length).toBe(1);
    expect(await page.evaluate(() => Reflect.get(window, "__r33EvalNegative"))).toBe("EvalError");
    expect(await page.evaluate(() => Reflect.get(window, "__r33EvalExecuted"))).toBeUndefined();
    expect(await events(page)).toEqual([expect.objectContaining({ effectiveDirective: "script-src", blockedURI: "eval", disposition: "enforce", sourceFile: "http://127.0.0.1:5173/assets/r33-eval-negative.js" })]);
    expect(observed.reports).toEqual([{ "csp-report": expect.objectContaining({ "effective-directive": "script-src", "blocked-uri": "eval", disposition: "enforce", "source-file": "http://127.0.0.1:5173/assets/r33-eval-negative.js" }) }]);
  } finally {
    await fs.writeFile(info.outputPath("eval-negative-observations.json"), JSON.stringify({ ...observed, violations: await events(page) }, null, 2));
    try { await registry.dispose(); } catch (error) { if (!(error instanceof Error)) throw error; disposal = error; }
  }
  // No report registration or console allowance. The same unchanged guard
  // explicitly rejects the attack control; it cannot become an accepted load.
  expect(disposal?.message).toBe(
    `[fail-closed registry "${info.title}"] 2 failure(s):\n` +
    "1. unexpected request: received POST /csp-report; no related handler is registered\n" +
    "2. console error: Failed to load resource: net::ERR_FAILED at http://127.0.0.1:5173/csp-report",
  );
  await info.attach("expected-guard-rejection", { body: disposal!.message, contentType: "text/plain" });
});
