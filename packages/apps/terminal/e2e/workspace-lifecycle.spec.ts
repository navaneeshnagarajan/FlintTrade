import { expect, registerExploreAdvisorStatusProbe, registerOperatorStatusProbes, test } from "./fixture-registry";
import { seedExploreDemoSession } from "./helpers";

// Fresh app-scoped presentation layouts replace legacy workspace tabs and the
// backend preset editor. The endpoint stays UNREGISTERED: any reuse is fatal.
const LAYOUT_KEY = "flinttrade:app-layouts:v1:terminal";

test("creates, clones, switches, and restores two canonical workspaces", async ({ page, syntheticApi }) => {
  await seedExploreDemoSession(page);
  // Explore probes advisor status (FT-AI-001) and the Mode menu reads
  // Live-arm status. `useAdvisorLlmStatus` refetches on every mount
  // (staleTime 0). Template create, clone, the Options Desk switch, the
  // switch back, and the reload each remount that probe. This journey
  // makes 12 of those reads.
  registerExploreAdvisorStatusProbe(syntheticApi, {
    expectedCalls: { minimum: 1, maximum: 12 },
  });
  // The Laya chip polls this ping every 1.5 seconds for the whole journey.
  // Remounts plus that interval sit above the shared operator-probe cap.
  registerOperatorStatusProbes(syntheticApi, {
    pingCalls: { minimum: 1, maximum: 16 },
  });
  syntheticApi.register({
    name: "Mode menu Live-arm status",
    method: "GET",
    path: "/ft-api/v1/auth/status",
    expectedCalls: { minimum: 1, maximum: 6 },
    handler: (request) => {
      expect(request.postData()).toBeNull();
      const authorization = request.headers()["authorization"];
      if (authorization !== undefined) {
        expect(authorization.startsWith("Bearer ")).toBe(true);
      }
      return {
        json: {
          status: "success",
          data: {
            is_setup: true,
            is_locked: false,
            has_pin: false,
            totp_enabled: false,
          },
        },
      };
    },
  });
  await page.goto("/trade");
  await expect(page).toHaveURL("http://localhost:5173/terminal");
  const workspace = page.getByRole("region", { name: "Terminal app", exact: true });
  const preset = workspace.getByRole("combobox", { name: "Terminal preset", exact: true });
  const restore = workspace.getByRole("combobox", { name: "Restore saved layout", exact: true });
  await expect(workspace).toBeVisible();
  await expect(preset.locator("option")).toHaveText(["Choose layout", "Overview", "Trader", "Market watch", "Option Scalper", "Multi chart"]);
  await preset.selectOption("trader");
  await workspace.getByRole("button", { name: "Add widget", exact: true }).click();
  const catalogue = page.getByRole("dialog", { name: "Terminal widgets", exact: true });
  await catalogue.getByRole("button", { name: "Add Risk", exact: true }).click();
  await expect(workspace.getByText("Risk", { exact: true }).first()).toBeVisible();
  await workspace.getByRole("textbox", { name: "Layout name", exact: true }).fill("Trading Desk");
  await workspace.getByRole("button", { name: "Save layout", exact: true }).click();
  await expect(workspace.getByRole("status")).toHaveText("Saved Trading Desk");
  const original = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!)["Trading Desk"], LAYOUT_KEY);

  // Save-as is the clone owner. Prove identity first, then edit only the copy.
  await workspace.getByRole("textbox", { name: "Layout name", exact: true }).fill("Trading Desk (Copy)");
  await workspace.getByRole("button", { name: "Save layout", exact: true }).click();
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!)["Trading Desk (Copy)"], LAYOUT_KEY)).toEqual(original);
  await preset.selectOption("options-scalper");
  await expect(workspace.getByText("Option Chain", { exact: true }).first()).toBeVisible();
  await workspace.getByRole("button", { name: "Save layout", exact: true }).click();
  const copy = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!)["Trading Desk (Copy)"], LAYOUT_KEY);
  expect(copy).not.toEqual(original);
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!)["Trading Desk"], LAYOUT_KEY)).toEqual(original);
  await expect(restore.locator("option")).toHaveText(["Restore layout", "Trading Desk", "Trading Desk (Copy)"]);

  for (const [name, expected, label] of [["Trading Desk", original, "Risk"], ["Trading Desk (Copy)", copy, "Option Chain"], ["Trading Desk", original, "Risk"]] as const) {
    await restore.selectOption({ label: name });
    await expect(workspace.getByText(label, { exact: true }).first()).toBeVisible();
    await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key)!).Current, LAYOUT_KEY)).toEqual(expected);
  }
  await page.reload();
  await expect(workspace).toBeVisible();
  await expect(workspace.getByText("Risk", { exact: true }).first()).toBeVisible();
  const persisted = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), LAYOUT_KEY);
  expect(Object.keys(persisted).sort()).toEqual(["Current", "Trading Desk", "Trading Desk (Copy)"]);
  expect(persisted["Trading Desk"]).toEqual(original);
  expect(persisted["Trading Desk (Copy)"]).toEqual(copy);
  expect(persisted.Current).toEqual(original);
  expect(syntheticApi.callCount("GET", "/ft-api/api/v1/presets/")).toBe(0);
});

for (const draftMode of ["new", "edit"] as const) {
  test(`settings shortcuts and workspace views preserve an unsaved ${draftMode} preset draft`, async ({ page, syntheticApi }, testInfo) => {
    await seedExploreDemoSession(page);

    // The shell and the trade route can remount the read-only advisor probes.
    // Leave the provider unconfigured so no local-runtime probe is needed.
    registerExploreAdvisorStatusProbe(syntheticApi, {
      expectedCalls: { minimum: 1, maximum: 8 },
    });
    registerOperatorStatusProbes(syntheticApi, {
      expectedCalls: { minimum: 1, maximum: 8 },
      // A 30-second journey can see twenty 1.5-second ticks, plus mounts.
      pingCalls: { minimum: 1, maximum: 24 },
    });

    syntheticApi.register({
      name: "read synthetic Mode menu status",
      method: "GET",
      path: "/ft-api/v1/auth/status",
      expectedCalls: { minimum: 1, maximum: 4 },
      handler: (request) => {
        expect(request.url()).toBe("http://localhost:5173/ft-api/v1/auth/status");
        expect(request.postData()).toBeNull();
        expect(request.headers()["x-api-key"]).toBeUndefined();
        return {
          json: {
            status: "success",
            data: {
              is_setup: true,
              is_locked: false,
              has_pin: false,
              totp_enabled: false,
            },
          },
        };
      },
    });
    // Seed only a fresh presentation record through the current storage contract.
    // No account, mode, credential or execution authority is stored in layouts.
    await page.addInitScript(() => {
      localStorage.setItem("flinttrade:app-layouts:v1:terminal", JSON.stringify({
        "Synthetic saved layout": {
          global: {}, borders: [], layout: { type: "row", children: [{ type: "tabset", children: [
            { type: "tab", id: "synthetic-watchlist", component: "watchlist", name: "Watchlist" },
          ] }] },
        },
      }));
    });
    // Every registered API response is a GET. The automatic fixture boundary
    // rejects writes, other endpoints, excess calls, and client errors.
    await page.goto("/settings#appearance");
    await expect(page).toHaveURL("http://localhost:5173/settings#appearance");
    const settings = page.getByRole("region", { name: "Settings", exact: true });
    const appearance = settings.getByRole("tabpanel", { name: "Appearance", exact: true });
    await expect(settings.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
    await expect(settings.getByRole("tab", { name: "Appearance", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(appearance).toBeVisible();
    await expect(appearance.getByRole("group", { name: "Colour mode", exact: true })).toHaveCount(1);
    await expect(appearance.getByRole("switch", { name: "Toggle glass effects", exact: true })).toHaveCount(1);
    await expect(settings.getByRole("status", { name: "Settings save status" })).toHaveCount(0);
    const appearanceScreenshot = testInfo.outputPath(`settings-appearance-${draftMode}.png`);
    await page.screenshot({ path: appearanceScreenshot });
    await testInfo.attach(`settings-appearance-${draftMode}`, {
      path: appearanceScreenshot,
      contentType: "image/png",
    });

    await page.keyboard.press("Control+,");
    const quickSettings = page.getByRole("dialog", { name: "Quick settings", exact: true });
    await expect(quickSettings).toBeVisible();
    await expect(quickSettings.getByRole("group", { name: "Colour mode", exact: true })).toHaveCount(1);
    await expect(page).toHaveURL("http://localhost:5173/settings#appearance");
    await expect(quickSettings.getByRole("button", { name: "Dark mode", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(quickSettings).not.toBeVisible();
    await expect(appearance).toBeVisible();

    await page.goto("/settings#presets");
    await expect(page).toHaveURL("http://localhost:5173/terminal");
    const workspace = page.getByRole("region", { name: "Terminal app", exact: true });
    await expect(workspace).toBeVisible();
    const restore = workspace.getByRole("combobox", { name: "Restore saved layout", exact: true });
    await expect(restore.locator("option")).toHaveText(["Restore layout", "Synthetic saved layout"]);
    const before = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!)["Synthetic saved layout"], LAYOUT_KEY);
    if (draftMode === "edit") await restore.selectOption({ label: "Synthetic saved layout" });
    else await workspace.getByRole("combobox", { name: "Terminal preset", exact: true }).selectOption("trader");
    const draftName = `Unsaved ${draftMode} browser draft`;
    await workspace.getByRole("textbox", { name: "Layout name", exact: true }).fill(draftName);
    await workspace.getByRole("button", { name: "Add widget", exact: true }).click();
    const catalogue = page.getByRole("dialog", { name: "Terminal widgets", exact: true });
    await catalogue.getByRole("button", { name: "Add Risk", exact: true }).click();
    const expectDraft = async (): Promise<void> => {
      await expect(workspace).toBeVisible();
      await expect(workspace.getByRole("textbox", { name: "Layout name", exact: true })).toHaveValue(draftName);
      await expect(workspace.getByText("Risk", { exact: true }).first()).toBeVisible();
      await expect.poll(() => page.evaluate(key => JSON.stringify(JSON.parse(localStorage.getItem(key)!).Current), LAYOUT_KEY)).toContain('"riskdashboard"');
      const saved = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), LAYOUT_KEY);
      expect(saved[draftName]).toBeUndefined();
      expect(saved["Synthetic saved layout"]).toEqual(before);
      if (draftMode === "edit") expect(JSON.stringify(saved.Current)).toContain('"watchlist"');
    };
    await expectDraft();

    // A different app and chrome overlay replace the old manager's views.
    // Preserve the unsaved name/composition and the exact saved source bytes.
    const apps = page.getByRole("navigation", { name: "Apps", exact: true });
    await apps.getByRole("link", { name: "Learn", exact: true }).click();
    await expect(workspace).not.toBeVisible();
    await apps.getByRole("link", { name: "Terminal", exact: true }).click();
    await expectDraft();
    await page.keyboard.press("Control+,");
    await expect(quickSettings).toBeVisible();
    await expect(quickSettings.getByRole("button", { name: "Dark mode", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(quickSettings).not.toBeVisible();
    await expectDraft();

    for (const dismissal of ["Close", "Escape"] as const) {
      await workspace.getByRole("button", { name: "Add widget", exact: true }).click();
      await expect(catalogue).toBeVisible();
      await expect(catalogue.getByRole("button", { name: "Add Risk", exact: true })).toBeVisible();
      if (dismissal === "Close") await catalogue.getByRole("button", { name: "Close widget catalogue", exact: true }).click();
      else await page.keyboard.press("Escape");
      await expect(catalogue).not.toBeVisible();
      await expectDraft();
    }
    const draftScreenshot = testInfo.outputPath(`preserved-${draftMode}-preset-draft.png`);
    await page.screenshot({ path: draftScreenshot });
    await testInfo.attach(`preserved-${draftMode}-preset-draft`, { path: draftScreenshot, contentType: "image/png" });
    expect(syntheticApi.callCount("GET", "/ft-api/api/v1/presets/")).toBe(0);
    await expect(page).toHaveURL("http://localhost:5173/terminal");
  });
}
