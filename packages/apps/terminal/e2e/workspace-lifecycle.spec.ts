import { expect, registerExploreAdvisorStatusProbe, registerOperatorStatusProbes, test } from "./fixture-registry";
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

test("creates, clones, switches, and restores two canonical workspaces", async ({
  page,
  syntheticApi,
}) => {
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

  const workspace = page.locator('[data-tour-target="workspace"]');
  const switcher = page.getByRole("combobox", { name: "Active workspace" });
  await expect(workspace).toBeVisible();
  await expect(switcher).toBeVisible();

  await page.getByRole("button", { name: "Manage workspaces" }).click();
  await expect(page.getByRole("dialog", { name: "Manage workspaces" })).toBeVisible();
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

for (const draftMode of ["new", "edit"] as const) {
  test(`settings shortcuts and workspace views preserve an unsaved ${draftMode} preset draft`, async ({
    page,
    syntheticApi,
  }, testInfo) => {
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
      name: "read empty Settings bridge configuration",
      method: "GET",
      path: "/ft-api/v1/config/openalgo",
      expectedCalls: { minimum: 1, maximum: 4 },
      handler: (request) => {
        expect(request.url()).toBe("http://localhost:5173/ft-api/v1/config/openalgo");
        expect(request.postData()).toBeNull();
        expect(request.headers()["x-api-key"]).toBeUndefined();
        return {
          json: {
            status: "success",
            data: {
              host: "",
              port: 5000,
              ws_port: 8765,
              api_key: "",
              api_key_configured: false,
              api_key_last4: "",
            },
          },
        };
      },
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
    syntheticApi.register({
      name: "read synthetic saved preset catalogue once",
      method: "GET",
      path: "/ft-api/api/v1/presets/",
      expectedCalls: 1,
      handler: (request) => {
        expect(request.url()).toBe("http://localhost:5173/ft-api/api/v1/presets/");
        expect(request.postData()).toBeNull();
        expect(request.headers()["x-api-key"]).toBeUndefined();
        return {
          json: {
            status: "success",
            data: {
              presets: [{
                id: "synthetic-saved-layout",
                name: "Synthetic saved layout",
                description: "Read-only browser fixture",
                is_builtin: false,
                widgets: ["watchlist"],
              }],
            },
          },
        };
      },
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
    await testInfo.attach(`settings-appearance-${draftMode}`, {
      body: await page.screenshot(),
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
    await expect(page).toHaveURL("http://localhost:5173/trade");
    await expect(page.locator('[data-tour-target="workspace"]')).toBeVisible();
    const manager = page.getByRole("dialog", { name: "Manage workspaces", exact: true });
    await expect(manager).toBeVisible();
    await manager.getByRole("button", { name: "Saved presets", exact: true }).click();
    await expect(manager.getByRole("button", { name: "Edit Synthetic saved layout", exact: true })).toBeVisible();

    if (draftMode === "new") {
      await manager.getByRole("button", { name: "Create a new workspace preset", exact: true }).click();
    } else {
      await manager.getByRole("button", { name: "Edit Synthetic saved layout", exact: true }).click();
    }
    const form = manager.getByRole("form", { name: draftMode === "new" ? "New Preset form" : "Edit Preset form" });
    const draftName = `Unsaved ${draftMode} browser draft`;
    const draftDescription = `Retain ${draftMode} name, description, and widgets`;
    await form.getByLabel("Name", { exact: false }).fill(draftName);
    await form.getByLabel("Description", { exact: true }).fill(draftDescription);
    await form.getByRole("button", { name: "Toggle widget list", exact: true }).click();
    await form.getByRole("button", { name: "Risk", exact: true }).click();

    const expectDraft = async (): Promise<void> => {
      await expect(manager).toBeVisible();
      await expect(form).toBeVisible();
      await expect(form.getByLabel("Name", { exact: false })).toHaveValue(draftName);
      await expect(form.getByLabel("Description", { exact: true })).toHaveValue(draftDescription);
      await expect(form.getByRole("button", { name: "Risk", exact: true })).toHaveAttribute("aria-pressed", "true");
      await expect(form.getByRole("button", { name: "Remove Risk", exact: true })).toBeVisible();
      if (draftMode === "edit") {
        await expect(form.getByRole("button", { name: "Remove Watchlist", exact: true })).toBeVisible();
      }
    };
    await expectDraft();
    await manager.getByRole("button", { name: "Built-in templates", exact: true }).click();
    await expect(form).not.toBeVisible();
    await expect(manager.getByRole("button", { name: /^Trading Desk / })).toBeVisible();
    await manager.getByRole("button", { name: "Saved presets", exact: true }).click();
    await expectDraft();

    for (const dismissal of ["Cancel", "Escape"] as const) {
      await manager.getByRole("button", { name: "Workspace actions", exact: true }).click();
      await page.getByRole("menuitem", { name: "New from Template", exact: true }).click();
      const template = page.getByRole("dialog", { name: "New Workspace from Template", exact: true });
      await expect(template).toBeVisible();
      await expect(template.getByRole("button", { name: /^Trading Desk / })).toBeVisible();
      await expect(form).not.toBeVisible();
      if (dismissal === "Cancel") {
        await template.getByRole("button", { name: "Cancel", exact: true }).click();
      } else {
        await page.keyboard.press("Escape");
      }
      await expect(template).not.toBeVisible();
      await expectDraft();
    }

    await testInfo.attach(`preserved-${draftMode}-preset-draft`, {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    expect(syntheticApi.callCount("GET", "/ft-api/api/v1/presets/")).toBe(1);
    await manager.getByRole("button", { name: "Close", exact: true }).click();
    await expect(manager).not.toBeVisible();
    await expect(page.getByRole("combobox", { name: "Active workspace" })).toBeVisible();
    await expect(page).toHaveURL("http://localhost:5173/trade");
  });
}
