import {
  expect,
  registerExploreAdvisorStatusProbe,
  registerOperatorStatusProbes,
  test,
  type SyntheticFixtureRegistry,
} from "./fixture-registry";
import { seedExploreDemoSession } from "./helpers";

test("public demo saves and restores presets through the legacy manager entry", async ({
  page,
  syntheticApi,
}, testInfo) => {
  const unexpectedSockets: string[] = [];
  const presetRequests: string[] = [];
  const modeStatusCalls = [0, 0, 0];
  let documentLoad = 0;
  // Production preview has no HMR. No application socket may reach a server.
  await page.routeWebSocket("**/*", async (socket) => {
    unexpectedSockets.push(socket.url());
    await socket.close({ code: 1008, reason: "Unexpected public-demo WebSocket" });
  });
  page.on("request", (request) => {
    if (/\/presets(?:\/|$)/.test(new URL(request.url()).pathname)) {
      presetRequests.push(`${request.method()} ${request.url()}`);
    }
  });
  await seedExploreDemoSession(page);

  // These existing, read-only shell fixtures cover three document loads.
  // There is deliberately no preset handler: every preset request fails the
  // automatic HTTP registry, including reads and writes hidden by the UI.
  // Production callers use root-relative API paths without Vite's /ft-api
  // prefix. Reuse the same exact shell fixtures, changing only that prefix.
  const productionPath = (path: string): string => path.replace(/^\/ft-api\//, "/");
  const shellApi: SyntheticFixtureRegistry = {
    name: syntheticApi.name,
    register: (registration) => {
      expect(registration.method).toBe("GET");
      syntheticApi.register({ ...registration, path: productionPath(registration.path) });
    },
    callCount: (method, path) => syntheticApi.callCount(method, productionPath(path)),
    assertSatisfied: () => syntheticApi.assertSatisfied(),
    dispose: () => syntheticApi.dispose(),
  };
  registerExploreAdvisorStatusProbe(shellApi, {
    expectedCalls: { minimum: 3, maximum: 12 },
  });
  registerOperatorStatusProbes(shellApi, {
    expectedCalls: { minimum: 3, maximum: 12 },
    // Thirty seconds allow twenty 1.5-second ping ticks, plus page mounts.
    pingCalls: { minimum: 3, maximum: 24 },
  });

  syntheticApi.register({
    name: "public-demo shell Mode status",
    method: "GET",
    path: "/v1/auth/status",
    // The first hosted trace made 1/2/2 reads across these three document
    // loads. Bound each load separately so a repeated request loop still fails.
    expectedCalls: { minimum: 3, maximum: 6 },
    handler: (request) => {
      modeStatusCalls[documentLoad] += 1;
      expect(modeStatusCalls[documentLoad]).toBeLessThanOrEqual(2);
      expect(request.url()).toBe("http://127.0.0.1:5173/v1/auth/status");
      expect(request.postData()).toBeNull();
      const authorization = request.headers()["authorization"];
      if (authorization !== undefined) expect(authorization.startsWith("Bearer ")).toBe(true);
      expect(request.headers()["x-api-key"]).toBeUndefined();
      return {
        json: {
          status: "success",
          data: { is_setup: true, is_locked: false, has_pin: false, totp_enabled: false },
        },
      };
    },
  });

  const manager = page.getByRole("dialog", { name: "Manage workspaces", exact: true });
  const newForm = manager.getByRole("form", { name: "New Preset form", exact: true });
  const forkForm = manager.getByRole("form", { name: "Fork Preset form", exact: true });
  const editForm = manager.getByRole("form", { name: "Edit Preset form", exact: true });
  const initialName = "Synthetic browser preset";
  const editedName = "Synthetic browser preset edited";
  const editedDescription = "Synthetic description retained after reload";
  const savedNotice = manager.getByText("In this public demo, custom presets are saved only in this browser. They are not synced to an installed account.", { exact: true });

  try {
    await page.goto("settings#presets");
    await expect(page).toHaveURL("http://127.0.0.1:5173/demo-app/trade");
    await expect(page.locator('[data-tour-target="workspace"]')).toBeVisible();
    await expect(manager).toBeVisible();
    await manager.getByRole("button", { name: "Saved presets", exact: true }).click();
    await expect(savedNotice).toBeVisible();
    await expect(manager.getByRole("button", { name: "Fork Trading Desk", exact: true })).toBeVisible();
    await expect(manager.getByText("Failed to load presets:", { exact: false })).toHaveCount(0);

    // Multi Chart intentionally repeats the chart widget four times. Forking
    // retains all four, and removing one occurrence must preserve the others.
    const forkName = "Synthetic four-chart browser preset";
    await manager.getByRole("button", { name: "Fork Multi Chart", exact: true }).click();
    await expect(forkForm.getByText("Create a copy, then edit its contents.", { exact: true })).toBeVisible();
    await expect(forkForm.getByLabel("Description", { exact: true })).toHaveAttribute("readonly", "");
    await expect(forkForm.getByText("Chart", { exact: true })).toHaveCount(4);
    await expect(forkForm.getByRole("button", { name: "Remove Chart", exact: true })).toHaveCount(0);
    await expect(forkForm.getByRole("button", { name: "Toggle widget list", exact: true })).toHaveCount(0);
    await forkForm.getByLabel("Name", { exact: false }).fill(forkName);
    await forkForm.getByRole("button", { name: "Save", exact: true }).click();
    await expect(forkForm).not.toBeVisible();
    await manager.getByRole("button", { name: `Edit ${forkName}`, exact: true }).click();
    await expect(editForm.getByRole("button", { name: "Remove Chart", exact: true })).toHaveCount(4);
    await editForm.getByRole("button", { name: "Remove Chart", exact: true }).nth(1).click();
    await expect(editForm.getByRole("button", { name: "Remove Chart", exact: true })).toHaveCount(3);
    await editForm.getByRole("button", { name: "Save", exact: true }).click();
    await expect(editForm).not.toBeVisible();
    await manager.getByRole("button", { name: `Edit ${forkName}`, exact: true }).click();
    await expect(editForm.getByRole("button", { name: "Remove Chart", exact: true })).toHaveCount(3);
    await editForm.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(editForm).not.toBeVisible();

    await manager.getByRole("button", { name: "Create a new workspace preset", exact: true }).click();
    await newForm.getByLabel("Name", { exact: false }).fill(initialName);
    await newForm.getByLabel("Description", { exact: true }).fill("Synthetic create description");
    await newForm.getByRole("button", { name: "Toggle widget list", exact: true }).click();
    await newForm.getByRole("button", { name: "Watchlist", exact: true }).click();
    await newForm.getByRole("button", { name: "Create", exact: true }).click();
    await expect(newForm).not.toBeVisible();

    await manager.getByRole("button", { name: `Edit ${initialName}`, exact: true }).click();
    await expect(editForm.getByLabel("Description", { exact: true })).toHaveValue("Synthetic create description");
    await expect(editForm.getByRole("button", { name: "Remove Watchlist", exact: true })).toBeVisible();
    await editForm.getByLabel("Name", { exact: false }).fill(editedName);
    await editForm.getByLabel("Description", { exact: true }).fill(editedDescription);
    await editForm.getByRole("button", { name: "Remove Watchlist", exact: true }).click();
    await editForm.getByRole("button", { name: "Toggle widget list", exact: true }).click();
    await editForm.getByRole("button", { name: "Risk", exact: true }).click();
    await editForm.getByRole("button", { name: "Save", exact: true }).click();
    await expect(editForm).not.toBeVisible();
    await expect(manager.getByRole("button", { name: `Edit ${editedName}`, exact: true })).toBeVisible();
    await expect(manager.getByRole("button", { name: `Edit ${initialName}`, exact: true })).toHaveCount(0);

    // Case-insensitive duplicate refusal must preserve the unsaved draft and
    // leave exactly one matching saved card in the local catalogue.
    const duplicateName = editedName.toUpperCase();
    const duplicateDescription = "Synthetic duplicate draft survives refusal";
    await manager.getByRole("button", { name: "Create a new workspace preset", exact: true }).click();
    await newForm.getByLabel("Name", { exact: false }).fill(duplicateName);
    await newForm.getByLabel("Description", { exact: true }).fill(duplicateDescription);
    await newForm.getByRole("button", { name: "Toggle widget list", exact: true }).click();
    await newForm.getByRole("button", { name: "Watchlist", exact: true }).click();
    await newForm.getByRole("button", { name: "Create", exact: true }).click();
    await expect(manager.getByText(/already exists/i)).toBeVisible();
    await expect(newForm).toBeVisible();
    await expect(newForm.getByLabel("Name", { exact: false })).toHaveValue(duplicateName);
    await expect(newForm.getByLabel("Description", { exact: true })).toHaveValue(duplicateDescription);
    await expect(newForm.getByRole("button", { name: "Remove Watchlist", exact: true })).toBeVisible();
    await expect(manager.getByRole("button", { name: /^Edit Synthetic browser preset edited$/i })).toHaveCount(1);
    await newForm.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(newForm).not.toBeVisible();

    const expectSavedPreset = async (): Promise<void> => {
      await expect(savedNotice).toBeVisible();
      await manager.getByRole("button", { name: `Edit ${editedName}`, exact: true }).click();
      await expect(editForm.getByLabel("Name", { exact: false })).toHaveValue(editedName);
      await expect(editForm.getByLabel("Description", { exact: true })).toHaveValue(editedDescription);
      await expect(editForm.getByRole("button", { name: "Remove Risk", exact: true })).toBeVisible();
      await expect(editForm.getByRole("button", { name: "Remove Watchlist", exact: true })).toHaveCount(0);
    };

    documentLoad = 1;
    await page.reload();
    await expect(page).toHaveURL("http://127.0.0.1:5173/demo-app/trade");
    await page.getByRole("button", { name: "Manage workspaces", exact: true }).click();
    await manager.getByRole("button", { name: "Saved presets", exact: true }).click();
    await expectSavedPreset();

    const screenshot = testInfo.outputPath("public-demo-preset-restored.png");
    await editForm.scrollIntoViewIfNeeded();
    await page.screenshot({ path: screenshot });
    await testInfo.attach("public-demo-preset-restored", { path: screenshot, contentType: "image/png" });

    // The historical Settings URL must still reopen the manager with the
    // persisted custom record, even after leaving an editor open on reload.
    documentLoad = 2;
    await page.goto("settings#presets");
    await expect(page).toHaveURL("http://127.0.0.1:5173/demo-app/trade");
    await expect(manager).toBeVisible();
    await manager.getByRole("button", { name: "Saved presets", exact: true }).click();
    await expectSavedPreset();
  } finally {
    // End the document while both boundaries remain installed, so a delayed
    // request cannot escape after the zero-network assertions.
    await page.close();
    expect(presetRequests, "Public-demo presets must stay browser-local").toEqual([]);
    expect(unexpectedSockets, "Public-demo presets must not open sockets").toEqual([]);
    for (const calls of modeStatusCalls) {
      expect(calls, "Mode status reads per document load").toBeGreaterThanOrEqual(1);
      expect(calls, "Mode status reads per document load").toBeLessThanOrEqual(2);
    }
  }
});
