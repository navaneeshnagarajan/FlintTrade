import fs from "node:fs/promises";
import {
  ACCOUNT_A, ACCOUNT_B, BROKER, CANCEL_WARNING, captureEvidence, deferredResponse,
  exitRow, expect, mountWidget, nativePath, registerAccountBooks, registerDeskReads,
  registerRead, selectAccount, test, tickUntil,
} from "./order-flow-fixtures";

const discoveryResponse = { json: { accounts: [ACCOUNT_A, ACCOUNT_B].map((account, index) => ({
  adapter_id: BROKER, account_id: account, label: account, is_primary: index === 0,
  has_session: true, read_only: false, needs_relogin: false, login_retryable: false,
})) } };

// This is the real Vite development root, StrictMode, QueryProvider, account
// hydration, useOrders and captured-account HTTP client. Only API response
// timing is controlled; no provider, getter, readiness or cache is replaced.
test("development StrictMode with discovery released after mount requires the surviving startup book", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi, false, { nativeAccounts: false });
  const discovery = deferredResponse();
  registerRead(syntheticApi, "/ft-api/api/v1/native/accounts", () => discovery.promise,
    { minimum: 1, maximum: 28 });
  registerAccountBooks(syntheticApi, {
    orderCalls: 1, orderReadPhase: "startup", orders: { json: { status: "success", data: [exitRow()] } },
  });
  const requests: Array<{ method: string; path: string; outcome: string }> = [];
  const entries = new Map<import("@playwright/test").Request, (typeof requests)[number]>();
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.endsWith("/orders")) return;
    const entry = { method: request.method(), path: `${url.pathname}${url.search}`, outcome: "pending" };
    entries.set(request, entry);
    requests.push(entry);
  });
  page.on("requestfailed", (request) => {
    const entry = entries.get(request);
    if (entry) entry.outcome = request.failure()?.errorText ?? "unknown failure";
  });
  page.on("requestfinished", (request) => {
    const entry = entries.get(request);
    if (entry) entry.outcome = "completed";
  });
  try {
    await page.setViewportSize({ width: 1280, height: 720 });
    await mountWidget(page, "positions", true);
    await page.clock.runFor(50);
    expect(syntheticApi.callCount("GET", nativePath("orders"))).toBe(0);
    expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(0);
    discovery.release(discoveryResponse);
    const narrow = page.getByRole("tabpanel", { name: "Narrow Positions", exact: true });
    const cards = narrow.getByRole("list", { name: "Positions", exact: true });
    await tickUntil(page, cards);
    await expect(cards).toContainText(CANCEL_WARNING);
    await expect(cards).toContainText("Qty 10 · LTP 101.00");
    await expect(narrow.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toBeDisabled();
    expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(1);
    expect(syntheticApi.callCount("GET", nativePath("orders", ACCOUNT_B))).toBe(0);
    presentationEvidence.assertWrites([]);
    await captureEvidence(page, info, "delayed-discovery-surviving-book");
    const baseline = await syntheticApi.retireRead(nativePath("orders"));
    expect(baseline).toEqual({ calls: 1, completed: 1, cancelled: 0, pending: 0, failed: 0 });
    expect(syntheticApi.callCount("GET", nativePath("orders"))).toBe(baseline.calls);
    const path = info.outputPath("delayed-startup-phase.json");
    await fs.writeFile(path, JSON.stringify(baseline, null, 2));
    await info.attach("delayed-startup-phase", { path, contentType: "application/json" });
  } finally {
    discovery.release(discoveryResponse);
    const path = info.outputPath("phase-book-requests.json");
    await fs.writeFile(path, JSON.stringify({ phase: "delayed discovery", requests }, null, 2));
    await info.attach("phase-book-requests", { path, contentType: "application/json" });
  }
});

test("an independently cancelled startup GET cannot replace the mandatory surviving A or B book", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi, true, { nativeAccounts: false });
  const discovery = deferredResponse();
  const held = deferredResponse();
  registerRead(syntheticApi, "/ft-api/api/v1/native/accounts", () => discovery.promise,
    { minimum: 1, maximum: 56 });
  let phase: "held startup" | "surviving startup" = "held startup";
  let entered!: () => void;
  const firstEntered = new Promise<void>((resolve) => { entered = resolve; });
  registerAccountBooks(syntheticApi, {
    orderCalls: 1, orderReadPhase: "startup", orders: () => {
      if (phase === "held startup") {
        entered();
        return held.promise;
      }
      return { json: { status: "success", data: [exitRow()] } };
    },
  });
  registerAccountBooks(syntheticApi, {
    account: ACCOUNT_B, orderCalls: 1, orderReadPhase: "required",
    orders: { json: { status: "success", data: [exitRow(ACCOUNT_B)] } },
  });
  try {
    await page.setViewportSize({ width: 1280, height: 720 });
    await mountWidget(page, "positions", true);
    await page.clock.runFor(50);
    discovery.release(discoveryResponse);
    await tickUntil(page, page.getByRole("tabpanel", { name: "Narrow Positions", exact: true })
      .getByText("SYNTHETIC-ALPHA", { exact: true }));
    await firstEntered;
    const cancelled = page.waitForEvent("requestfailed", (request) =>
      new URL(request.url()).pathname === nativePath("orders"));
    // Control cancellation through the public account selector, not an injected
    // query cancellation/provider. This is independent of replay timing.
    await selectAccount(page, ACCOUNT_B);
    expect((await cancelled).failure()?.errorText).toBe("net::ERR_ABORTED");
    const narrow = page.getByRole("tabpanel", { name: "Narrow Positions", exact: true });
    const cards = narrow.getByRole("list", { name: "Positions", exact: true });
    await tickUntil(page, cards);
    await expect(cards).toContainText("SYNTHETIC-BETA");
    await expect(cards).toContainText(CANCEL_WARNING);
    await expect(narrow.getByRole("button", { name: "Square off SYNTHETIC-BETA" })).toBeDisabled();
    const beforeRelease = syntheticApi.callCount("GET", nativePath("orders", ACCOUNT_B));
    expect(beforeRelease).toBe(1);
    phase = "surviving startup";
    held.release({ json: { status: "success", data: [] } });
    await page.clock.runFor(50);
    await expect(cards).toContainText("SYNTHETIC-BETA");
    await expect(cards).toContainText(CANCEL_WARNING);
    expect(syntheticApi.callCount("GET", nativePath("orders", ACCOUNT_B))).toBe(beforeRelease);
    await selectAccount(page, ACCOUNT_A);
    await tickUntil(page, cards);
    await expect(cards).toContainText("SYNTHETIC-ALPHA");
    await expect(cards).toContainText(CANCEL_WARNING);
    await expect(cards).toContainText("Qty 10 · LTP 101.00");
    await expect(narrow.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toBeDisabled();
    const a = await syntheticApi.retireRead(nativePath("orders"));
    expect(a).toEqual({ calls: 2, completed: 1, cancelled: 1, pending: 0, failed: 0 });
    const b = await syntheticApi.retireRead(nativePath("orders", ACCOUNT_B));
    expect(b).toEqual({ calls: 1, completed: 1, cancelled: 0, pending: 0, failed: 0 });
    expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(1);
    expect(syntheticApi.callCount("GET", nativePath("positions", ACCOUNT_B))).toBe(1);
    presentationEvidence.assertWrites([]);
    const path = info.outputPath("independent-cancellation-phases.json");
    await fs.writeFile(path, JSON.stringify({ a, b, beforeRelease }, null, 2));
    await info.attach("independent-cancellation-phases", { path, contentType: "application/json" });
    await captureEvidence(page, info, "independent-cancellation-surviving-books");
  } finally {
    discovery.release(discoveryResponse);
    held.release({ json: { status: "success", data: [] } });
  }
});
