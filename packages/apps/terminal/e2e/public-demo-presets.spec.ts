import { mkdir, readFile, writeFile } from "node:fs/promises";
import { expect, test } from "./fixture-registry";
import type { Request } from "@playwright/test";

interface LayoutNode { type: string; id?: string; name?: string; component?: string; config?: Record<string, unknown>; children?: LayoutNode[] }
interface Layout { layout: LayoutNode }
const storageKey = "flinttrade:app-layouts:v1:terminal";
function tabs(node: LayoutNode): LayoutNode[] {
  return node.type === "tab" ? [node] : (node.children ?? []).flatMap(tabs);
}

// Fresh-start contract: save-as is not rename. The obsolete manager entry,
// description editor and case-folded duplicate refusal are intentionally retired.
test("anonymous public preview saves, restores and safely exchanges app-local layouts", async ({ page, syntheticApi }, testInfo) => {
  const requests: Array<Record<string, unknown>> = [];
  const byRequest = new Map<Request, Record<string, unknown>>();
  const jobs: Promise<void>[] = [];
  const sockets: string[] = [];
  const cdpRows: unknown[] = [];
  const checkpoints: unknown[] = [];
  let document = 0;
  await mkdir(testInfo.outputPath("native-bodies"), { recursive: true });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  for (const event of ["Network.requestWillBeSent", "Network.responseReceived", "Network.loadingFinished", "Network.loadingFailed"] as const) {
    cdp.on(event, data => cdpRows.push({ event, data }));
  }
  await page.routeWebSocket("**/*", async socket => {
    sockets.push(socket.url());
    await socket.close({ code: 1008, reason: "Unexpected frozen-preview WebSocket" });
  });
  page.on("request", request => {
    const row = { index: requests.length, document, method: request.method(), url: request.url(), resourceType: request.resourceType(), requestHeaders: request.headers(), requestBody: request.postData() };
    requests.push(row); byRequest.set(request, row);
  });
  page.on("requestfailed", request => Object.assign(byRequest.get(request)!, { failed: request.failure() }));
  page.on("response", response => {
    const row = byRequest.get(response.request())!;
    jobs.push((async () => {
      Object.assign(row, { status: response.status(), responseHeaders: await response.allHeaders() });
      const finished = await response.finished();
      if (finished) Object.assign(row, { finishError: String(finished) });
      try {
        const body = await response.body();
        const file = `native-bodies/${row.index}.bin`;
        await writeFile(testInfo.outputPath(file), body);
        Object.assign(row, { responseBodyFile: file, responseBodyBytes: body.length });
      } catch (error) { Object.assign(row, { bodyError: String(error) }); }
    })());
  });
  // No auth/account seed and no API handlers. Retired and unexpected endpoints
  // remain fatal in the unchanged automatic HTTP registry, including at close.
  const app = page.getByRole("region", { name: "Terminal app", exact: true });
  const layouts = async (): Promise<Record<string, Layout>> => page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? "{}"), storageKey);
  const currentTabs = async () => tabs((await layouts())["Current"].layout);
  const chartIds = async () => (await currentTabs()).filter(tab => tab.component === "chart").map(tab => tab.id);
  const save = async (name: string) => {
    await app.getByRole("textbox", { name: "Layout name", exact: true }).fill(name);
    await app.getByRole("button", { name: "Save layout", exact: true }).click();
    await expect(app.getByRole("status")).toHaveText(`Saved ${name}`);
    expect((await layouts())[name]).toEqual((await layouts())["Current"]);
  };
  const restore = async (name: string) => {
    await app.getByRole("combobox", { name: "Restore saved layout", exact: true }).selectOption({ label: name });
    await expect(app.getByRole("status")).toHaveText(`Restored ${name}`);
    await expect.poll(async () => (await layouts())["Current"]).toEqual((await layouts())[name]);
  };
  const anonymous = async () => {
    await expect(page.getByTestId("public-preview-header")).toHaveText(/Example · frozen simulation.*No accounts, sign-in, provider connections or real orders\./);
    await expect(app.getByTestId("app-execution-scope")).toHaveText("Example · No execution account selected · Linking changes selections, never execution authority.");
    expect(await page.evaluate(() => ({ session: sessionStorage.getItem("flinttrade:auth-session"), local: localStorage.getItem("flinttrade:auth-session"), mode: JSON.parse(localStorage.getItem("flinttrade:mode") ?? "null") }))).toEqual({ session: null, local: null, mode: { state: { mode: "explore" }, version: 2 } });
    await expect(page.getByRole("dialog", { name: "Manage workspaces", exact: true })).toHaveCount(0);
  };
  const checkpoint = async (name: string) => {
    checkpoints.push({ name, document, url: page.url(), layouts: await layouts(), aria: await page.locator("body").ariaSnapshot() });
    const path = testInfo.outputPath(`${name}.png`);
    await page.screenshot({ path });
    await testInfo.attach(name, { path, contentType: "image/png" });
  };
  try {
    await page.goto("terminal");
    await expect(page).toHaveURL("http://127.0.0.1:5173/demo-app/terminal");
    await expect(app).toBeVisible();
    await anonymous();
    const frozenTime = await page.evaluate(() => Date.now());
    await expect(app.getByRole("combobox", { name: "Terminal preset", exact: true }).locator("option")).toHaveText(["Choose layout", "Overview", "Trader", "Market watch", "Option Scalper", "Multi chart"]);
    await app.getByRole("combobox", { name: "Terminal preset", exact: true }).selectOption("multi-chart");
    await expect(app.locator('[data-app-widget="chart"]')).toHaveCount(4);
    await expect.poll(chartIds).toHaveLength(4);
    const fourIds = await chartIds();
    expect(new Set(fourIds).size).toBe(4);
    expect((await currentTabs()).map(tab => tab.name)).toEqual(["NIFTY", "FINNIFTY", "BANKNIFTY", "MIDCPNIFTY"]);
    await save("Four charts");
    const four = (await layouts())["Four charts"];
    await checkpoint("four-charts");
    // Close one genuine docking tab, not a deduplicated widget-list entry.
    await app.getByRole("tab", { name: "FINNIFTY", exact: true }).press("Control+Delete");
    await expect(app.locator('[data-app-widget="chart"]')).toHaveCount(3);
    await expect.poll(chartIds).toEqual(fourIds.filter(id => id !== tabs(four.layout).find(tab => tab.name === "FINNIFTY")!.id));
    await save("Three charts");
    expect((await layouts())["Four charts"]).toEqual(four); // save-as retains source
    await restore("Four charts");
    await expect(app.locator('[data-app-widget="chart"]')).toHaveCount(4);
    await restore("Three charts");
    await expect(app.locator('[data-app-widget="chart"]')).toHaveCount(3);
    await app.getByRole("button", { name: "Add widget", exact: true }).click();
    await page.getByRole("dialog", { name: "Terminal widgets", exact: true }).getByRole("button", { name: "Add Watchlist", exact: true }).click();
    await expect.poll(async () => (await currentTabs()).map(tab => tab.component).sort()).toEqual(["chart", "chart", "chart", "watchlist"]);
    await save("Charts and watchlist");
    await app.getByRole("tab", { name: "Watchlist", exact: true }).press("Control+Delete");
    await app.getByRole("button", { name: "Add widget", exact: true }).click();
    await page.getByRole("dialog", { name: "Terminal widgets", exact: true }).getByRole("button", { name: "Add Risk", exact: true }).click();
    await expect.poll(async () => (await currentTabs()).map(tab => tab.component).sort()).toEqual(["chart", "chart", "chart", "riskdashboard"]);
    await save("Charts and risk");
    expect(tabs((await layouts())["Charts and watchlist"].layout).some(tab => tab.component === "watchlist")).toBe(true);
    const edited = (await layouts())["Charts and risk"];
    await app.getByText("Layout actions", { exact: true }).click();
    await expect(app.getByText("Presentation only. Saved named layouts and all non-layout records are retained.", { exact: true })).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await app.getByRole("button", { name: "Export layout", exact: true }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("flinttrade-terminal-layout.json");
    const exportPath = testInfo.outputPath(download.suggestedFilename());
    await download.saveAs(exportPath);
    const bytes = await readFile(exportPath);
    const exported = JSON.parse(bytes.toString()) as { version: number; app: string; layout: Layout };
    expect(exported).toEqual({ version: 1, app: "terminal", layout: edited });
    const nonLayouts = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([key]) => !key.startsWith("flinttrade:app-layouts:v1:"))));
    const named = Object.fromEntries(Object.entries(await layouts()).filter(([name]) => name !== "Current"));
    await app.getByRole("button", { name: "Reset app layout", exact: true }).click();
    await expect.poll(async () => (await currentTabs()).map(tab => tab.component)).toEqual(["overview:WelcomeCard", "watchlist", "chart", "positions", "orders"]);
    expect(Object.fromEntries(Object.entries(await layouts()).filter(([name]) => name !== "Current"))).toEqual(named);
    const afterReset = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([key]) => !key.startsWith("flinttrade:app-layouts:v1:"))));
    // Newly mounted default charts may add presentation preferences; the real
    // widget-usage metric advances, but existing records must not be deleted.
    expect(Object.keys(afterReset)).toEqual(expect.arrayContaining(Object.keys(nonLayouts)));
    for (const [key, value] of Object.entries(nonLayouts)) {
      if (key !== "flinttrade:skill") expect(afterReset[key], key).toBe(value);
    }
    const previousSkill = JSON.parse(nonLayouts["flinttrade:skill"]);
    const nextSkill = JSON.parse(afterReset["flinttrade:skill"]);
    previousSkill.state.metrics.trade.widgetsUsed += 1;
    expect(nextSkill).toEqual(previousSkill);
    checkpoints.push({ name: "reset-retained-records", before: nonLayouts, after: afterReset });
    await app.getByLabel("Import app layout", { exact: true }).setInputFiles(exportPath);
    await expect(app.getByRole("status")).toHaveText("Imported presentation layout; execution unchanged.");
    await expect.poll(async () => (await layouts())["Current"]).toEqual(edited);
    const rejected = [
      { ...exported, app: "testing" },
      { ...exported, layout: { layout: { type: "row", children: [{ type: "tabset", children: [{ type: "tab", component: "chart", name: "Authority", config: { accountId: "synthetic-live", grant: "armed" } }] }] } } },
      { ...exported, layout: { layout: { type: "row", children: [{ type: "tabset", children: [{ type: "tab", component: "preferences", name: "Wrong app" }] }] } } },
    ];
    for (const [index, payload] of rejected.entries()) {
      await restore("Charts and risk");
      await expect(app.getByRole("alert")).toHaveCount(0);
      await app.getByLabel("Import app layout", { exact: true }).setInputFiles({ name: `refused-${index}.json`, mimeType: "application/json", buffer: Buffer.from(JSON.stringify(payload)) });
      await expect(app.getByRole("alert")).toHaveText("Error: Not a compatible fresh app layout. Authority and legacy layouts cannot be imported.");
      expect((await layouts())["Current"]).toEqual(edited);
      expect(Object.fromEntries(Object.entries(await layouts()).filter(([name]) => name !== "Current"))).toEqual(named);
      await anonymous();
    }
    await checkpoint("safe-import-refusals");
    const beforeReload = await layouts();
    document = 1;
    await page.reload();
    await expect(app).toBeVisible();
    await anonymous();
    await expect.poll(layouts).toEqual(beforeReload);
    // FlexLayout lazily mounts an inactive tab after a cold document. Select
    // each persisted chart through its real tab before counting mounted charts.
    for (const tab of tabs(edited.layout).filter(item => item.component === "chart")) {
      await app.getByRole("tab", { name: tab.name!, exact: true }).click();
    }
    await expect(app.locator('[data-app-widget="chart"]')).toHaveCount(3);
    await restore("Charts and watchlist");
    await expect.poll(async () => (await currentTabs()).some(tab => tab.component === "watchlist")).toBe(true);
    await restore("Charts and risk");
    await expect.poll(async () => (await currentTabs()).some(tab => tab.component === "watchlist")).toBe(false);
    await checkpoint("restored-after-reload");
    expect(await page.evaluate(() => Date.now())).toBe(frozenTime);
    document = 2;
    await page.goto("settings");
    await expect(page.getByText("The frozen preview cannot configure providers, change security or grant Live authority.", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Terminal", exact: true }).click();
    await expect(page).toHaveURL("http://127.0.0.1:5173/demo-app/terminal");
    await anonymous();
    await expect.poll(async () => (await layouts())["Current"]).toEqual(edited);
    expect(await page.evaluate(() => Date.now())).toBe(frozenTime);
    await checkpoint("terminal-return");
    await syntheticApi.assertSatisfied();
  } finally {
    await page.close(); // observers and registry remain active through disposal
    await Promise.all(jobs);
    await writeFile(testInfo.outputPath("native-requests.json"), JSON.stringify(requests, null, 2));
    await writeFile(testInfo.outputPath("native-cdp.json"), JSON.stringify(cdpRows, null, 2));
    await writeFile(testInfo.outputPath("layout-checkpoints.json"), JSON.stringify(checkpoints, null, 2));
    await writeFile(testInfo.outputPath("layout-teardown.json"), JSON.stringify({ pageClosed: page.isClosed(), sockets, documents: document + 1 }, null, 2));
    expect(sockets, "Frozen preview must not open sockets").toEqual([]);
    expect(requests.filter(row => !["document", "script", "stylesheet", "image", "font", "manifest"].includes(String(row.resourceType))), "No API/provider/fetch/XHR traffic through close").toEqual([]);
    for (const row of requests) {
      expect(row.method).toBe("GET");
      expect(new URL(String(row.url)).origin).toBe("http://127.0.0.1:5173");
      expect(row.requestBody).toBeNull();
      expect(row.requestHeaders).not.toHaveProperty("authorization");
      expect(row.requestHeaders).not.toHaveProperty("x-api-key");
      expect(row).not.toHaveProperty("failed");
      expect(row).not.toHaveProperty("finishError");
      expect(row).not.toHaveProperty("bodyError");
      expect(row).toHaveProperty("responseBodyFile");
    }
    expect([0, 1, 2].map(index => requests.filter(row => row.document === index && new URL(String(row.url)).pathname === "/v1/auth/status").length)).toEqual([0, 0, 0]);
  }
});
