import { expect, test } from "@playwright/test";
import { seedExploreDemoSession } from "./helpers";

interface PersistedWorkspaceState {
  layouts: {
    activeTabId: string;
    tabs: Array<{
      id: string;
      name: string;
      serializedLayout?: Record<string, unknown>;
    }>;
  };
  metadata: Record<string, { id: string; name: string; sourcePresetId?: string }>;
}

interface PersistedLayoutState {
  state: PersistedWorkspaceState["layouts"];
}

test("creates, clones, switches, and restores two canonical workspaces", async ({ page }) => {
  await seedExploreDemoSession(page);
  await page.route("**/v1/accounts", async (route) => {
    await route.fulfill({ json: { accounts: [] } });
  });
  await page.route("**/api/v1/native/accounts", async (route) => {
    await route.fulfill({ json: { accounts: [] } });
  });
  await page.route("**/api/v1/broker/capabilities", async (route) => {
    await route.fulfill({
      json: {
        broker_name: "Explore",
        broker_type: "multi",
        supported_exchanges: ["NSE", "BSE", "NFO", "BFO", "MCX"],
        features: {},
      },
    });
  });
  await page.goto("/trade");

  const workspace = page.locator('[data-tour-target="workspace"]');
  const switcher = page.getByRole("combobox", { name: "Active workspace" });
  await expect(workspace).toBeVisible();
  await expect(switcher).toBeVisible();

  await page.getByRole("button", { name: "Manage workspaces" }).click();
  await expect(page.getByRole("dialog", { name: "Choose a Workspace Template" })).toBeVisible();
  await page.getByRole("button", { name: "Workspace actions" }).click();
  await page.getByRole("menuitem", { name: "New from Template" }).click();
  await expect(page.getByRole("dialog", { name: "New Workspace from Template" })).toBeVisible();
  await page.getByRole("button", { name: /^Trading Desk / }).click();

  await expect(switcher).toHaveValue(/ws_/);
  await expect(switcher.locator("option:checked")).toHaveText("Trading Desk");

  await page.getByRole("button", { name: "Manage workspaces" }).click();
  await page.getByRole("button", { name: "Workspace actions" }).click();
  await page.getByRole("menuitem", { name: "Clone Current" }).click();

  await expect(switcher.locator("option:checked")).toHaveText("Trading Desk (Copy)");
  await expect(switcher.locator("option", { hasText: "Trading Desk" })).toHaveCount(2);

  // Make the clone observably different, then switch away. TerminalRoute flushes
  // the active model before rebinding, so this exercises real per-tab content.
  await page.getByRole("button", { name: "Manage workspaces" }).click();
  await page.getByRole("button", { name: /^Options Desk / }).click();
  await expect(page.getByText("Option Chain", { exact: true }).first()).toBeVisible();

  await switcher.selectOption({ label: "Trading Desk" });
  await expect(switcher.locator("option:checked")).toHaveText("Trading Desk");
  await expect(page.getByText("Risk", { exact: true }).first()).toBeVisible();

  await expect.poll(async () => page.evaluate(() => {
    const raw = localStorage.getItem("flinttrade:layouts");
    if (!raw) return false;
    const state = JSON.parse(raw) as PersistedLayoutState;
    const tabs = state.state.tabs.filter((tab) => tab.name.startsWith("Trading Desk"));
    return tabs.length === 2
      && tabs.every((tab) => tab.serializedLayout !== undefined)
      && JSON.stringify(tabs[0].serializedLayout) !== JSON.stringify(tabs[1].serializedLayout);
  })).toBe(true);

  const persisted = await page.evaluate<PersistedWorkspaceState>(() => {
    const layoutsRaw = localStorage.getItem("flinttrade:layouts");
    const metadataRaw = localStorage.getItem("flinttrade:workspaces");
    if (!layoutsRaw || !metadataRaw) throw new Error("workspace state was not persisted");
    const layoutsEnvelope = JSON.parse(layoutsRaw) as {
      state: PersistedWorkspaceState["layouts"];
    };
    return {
      layouts: layoutsEnvelope.state,
      metadata: JSON.parse(metadataRaw) as PersistedWorkspaceState["metadata"],
    };
  });
  const tradingTabs = persisted.layouts.tabs.filter((tab) => tab.name.startsWith("Trading Desk"));
  expect(tradingTabs).toHaveLength(2);
  expect(new Set(tradingTabs.map((tab) => tab.id)).size).toBe(2);
  for (const tab of tradingTabs) {
    expect(persisted.metadata[tab.id]).toMatchObject({ id: tab.id, name: tab.name });
    expect(tab.serializedLayout).toBeDefined();
  }
  expect(JSON.stringify(tradingTabs[0].serializedLayout)).not.toBe(
    JSON.stringify(tradingTabs[1].serializedLayout),
  );
  expect(persisted.metadata[tradingTabs[0].id].sourcePresetId).toBe("trading-desk");
  expect(persisted.metadata[tradingTabs[1].id].sourcePresetId).toBe("trading-desk");

  await page.reload();
  await expect(workspace).toBeVisible();
  await expect(switcher.locator("option:checked")).toHaveText("Trading Desk");
  await expect(switcher.locator("option", { hasText: "Trading Desk" })).toHaveCount(2);
  await expect(page.getByText("Risk", { exact: true }).first()).toBeVisible();
});
