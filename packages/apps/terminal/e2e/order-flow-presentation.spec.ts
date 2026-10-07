import type { SyntheticResponse } from "./fixture-registry";
import {
  ACCOUNT_A,
  ACCOUNT_B,
  BROKER,
  EXECUTION_WARNING,
  GTT_READ_FROZEN,
  GTT_REFUSAL,
  deferredResponse,
  exitRow,
  notifications,
  positionSurface,
  registerAccountBooks,
  selectAccount,
  CANCEL_WARNING,
  CHILD_CAVEAT,
  GTT_EMPTY,
  assertRequest,
  captureEvidence,
  captureNarrow,
  expect,
  foreverPath,
  mountWidget,
  nativePath,
  positionRow,
  registerDeskReads,
  registerRead,
  test,
  tickUntil,
  triggerRow,
} from "./order-flow-fixtures";

test("a cancellation ACK and a missing trigger retain execution uncertainty", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi);
  registerRead(syntheticApi, nativePath("positions"), {
    json: { status: "success", data: [positionRow()] },
  }, { minimum: 0, maximum: 2 });
  registerRead(syntheticApi, nativePath("orders"), {
    json: { status: "success", data: [] },
  }, { minimum: 0, maximum: 2 });
  registerRead(syntheticApi, nativePath("funds"), {
    json: { status: "success", data: { available_balance: 100_000, used_margin: 0, total_balance: 100_000 } },
  }, { minimum: 0, maximum: 2 });

  registerRead(syntheticApi, foreverPath(), {
    json: { status: "success", data: [triggerRow()] },
  }, 1, "required");
  const pendingRead = deferredResponse();
  const pendingBook = { status: "success", data: [triggerRow(ACCOUNT_A, "CANCEL_PENDING")] };
  const cancelPath = `/ft-api/api/v1/orders/forever/SYNTHETIC-GTT-${ACCOUNT_A}?broker=dhan&account_id=${ACCOUNT_A}`;
  syntheticApi.register({
    name: "one exact synthetic cancellation ACK", method: "DELETE", path: cancelPath, expectedCalls: 1,
    handler: (request) => {
      assertRequest(request, "DELETE", cancelPath);
      return { json: { status: "success", data: { accepted: true } } };
    },
  });

  try {
    await mountWidget(page, "foreverorders");
    const table = page.getByRole("table", { name: "Forever orders" });
    await tickUntil(page, table);
    await expect(table.getByText("SYNTHETIC-FUTURE", { exact: true })).toBeVisible();
    await expect(page.getByText("Your broker may execute this GTT while FlintTrade is offline.", { exact: false })).toBeVisible();
    await expect(page.getByText(CHILD_CAVEAT, { exact: true })).toBeVisible();
    await captureEvidence(page, info, "desktop-active-trigger");
    const initialReads = await syntheticApi.retireRead(foreverPath());
    expect(initialReads).toEqual({ calls: 1, completed: 1, cancelled: 0, pending: 0, failed: 0 });
    registerRead(syntheticApi, foreverPath(), () => pendingRead.promise, 1, "required");
    await table.getByRole("button", { name: "Cancel", exact: true }).click();
    await tickUntil(page, page.getByText(CANCEL_WARNING, { exact: true }).first());
    // An ACK can paint before its invalidated book finishes. Hold that actual
    // response until the warning is visible, then drive the book's own scheduled
    // query notification; waiting on ACK copy alone leaves the clock paused.
    expect(syntheticApi.callCount("GET", foreverPath())).toBe(initialReads.calls + 1);
    await expect(table.getByText("ACTIVE", { exact: true })).toBeVisible();
    await expect(table.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
    const pendingArrived = page.waitForResponse((response) => response.url().endsWith(foreverPath()));
    pendingRead.release({ json: pendingBook });
    expect(await (await pendingArrived).json()).toEqual(pendingBook);
    await tickUntil(page, table.getByText("CANCEL_PENDING", { exact: true }));
    await expect(table.getByText("CANCEL_PENDING", { exact: true })).toBeVisible();
    await expect(table.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
    await expect(page.getByText(/Order cancelled successfully|Position closed|Every open position was squared off/i)).toHaveCount(0);
    await captureEvidence(page, info, "desktop-cancel-ack-not-terminal");
    const pendingReads = await syntheticApi.retireRead(foreverPath());
    expect(pendingReads).toEqual({ calls: initialReads.calls + 1, completed: initialReads.completed + 1,
      cancelled: 0, pending: 0, failed: 0 });
    registerRead(syntheticApi, foreverPath(), { json: { status: "success", data: [] } }, 1, "required");

    await page.clock.runFor(50);
    await page.getByRole("button", { name: "Refresh forever orders" }).click();
    await tickUntil(page, page.getByText(GTT_EMPTY, { exact: true }));
    // Empty listing after this ACK does NOT prove cancellation, absence of a
    // spawned child, or risk release. The warning must survive without its row.
    await expect(page.getByText(CANCEL_WARNING, { exact: false }).first()).toBeVisible();
    await expect(page.getByText(CHILD_CAVEAT, { exact: true })).toBeVisible();
    await captureEvidence(page, info, "desktop-missing-trigger-uncertainty");
    await captureNarrow(page, info, "narrow-missing-trigger-uncertainty");
    await expect(page.getByText(CANCEL_WARNING, { exact: false }).first()).toBeVisible();

    const missingReads = await syntheticApi.retireRead(foreverPath());
    expect(missingReads).toEqual({ calls: pendingReads.calls + 1, completed: pendingReads.completed + 1,
      cancelled: 0, pending: 0, failed: 0 });
    registerRead(syntheticApi, foreverPath(), {
      json: { status: "success", data: [triggerRow(ACCOUNT_A, "CANCELLED")] },
    }, 1, "required");
    await page.clock.runFor(50);
    await page.getByRole("button", { name: "Refresh forever orders" }).click();
    await tickUntil(page, table.getByText("CANCELLED", { exact: true }));
    await expect(page.getByText(CANCEL_WARNING, { exact: false })).toHaveCount(0);
    await expect(page.getByText(CHILD_CAVEAT, { exact: true })).toBeVisible();
    presentationEvidence.assertWrites([{ method: "DELETE", path: cancelPath, body: null }]);
    expect(syntheticApi.callCount("GET", foreverPath())).toBe(4);
    const terminalReads = await syntheticApi.retireRead(foreverPath());
    expect(terminalReads).toEqual({ calls: missingReads.calls + 1, completed: missingReads.completed + 1,
      cancelled: 0, pending: 0, failed: 0 });
    await info.attach("cancellation-book-phases", { body: JSON.stringify({ initialReads, pendingReads, missingReads, terminalReads }),
      contentType: "application/json" });
  } finally {
    pendingRead.release({ json: pendingBook });
  }
});

const malformedGttListings: Array<{ name: string; response: SyntheticResponse }> = [
  { name: "null book", response: { json: { status: "success", data: null } } },
  { name: "partially malformed book", response: { json: { status: "success", data: [triggerRow(), null] } } },
  { name: "invalid JSON", response: { body: "not-json", contentType: "application/json" } },
];

for (const malformed of malformedGttListings) {
  test(`a ${malformed.name} is unavailable, unlike an actual empty GTT book`, async ({
    page, syntheticApi, presentationEvidence,
  }, info) => {
    registerDeskReads(syntheticApi);
    registerAccountBooks(syntheticApi);
    let calls = 0;
    registerRead(syntheticApi, foreverPath(), () => {
      calls += 1;
      return calls === 1 ? malformed.response : { json: { status: "success", data: [] } };
    }, 2);
    await mountWidget(page, "foreverorders");
    await tickUntil(page, page.getByRole("alert").filter({ hasText: /malformed|JSON/i }).first());
    await expect(page.getByTestId("forever-orders-unavailable")).toBeVisible();
    await expect(page.getByText(GTT_EMPTY, { exact: true })).toHaveCount(0);
    await expect(page.getByText(CHILD_CAVEAT, { exact: true })).toBeVisible();
    await captureEvidence(page, info, "desktop-malformed-not-empty");
    await captureNarrow(page, info, "narrow-malformed-not-empty");
    await page.getByRole("button", { name: "Refresh forever orders" }).click();
    await tickUntil(page, page.getByText(GTT_EMPTY, { exact: true }));
    await expect(page.getByTestId("forever-orders-unavailable")).toHaveCount(0);
    await captureEvidence(page, info, "verified-synthetic-empty-control");
    presentationEvidence.assertWrites([]);
    expect(syntheticApi.callCount("GET", foreverPath())).toBe(2);
  });
}

test.describe("production-equivalent frozen GTT refusal (not native availability)", () => {
  test.use({ benignConsoleErrors: [[
    {
      text: "Failed to load resource: the server responded with a status of 409 (Conflict)",
      url: `http://localhost:5173${foreverPath()}`, expectedCalls: 1,
    },
    {
      text: "Failed to load resource: the server responded with a status of 422 (Unprocessable Entity)",
      url: "http://localhost:5173/ft-api/api/v1/orders/place", expectedCalls: 1,
    },
  ], { scope: "test" }] });
  test("409 read cutover and 422 gtt_unsupported stay raw refusals", async ({
    page, syntheticApi, presentationEvidence,
  }, info) => {
    registerDeskReads(syntheticApi);
    registerAccountBooks(syntheticApi);
    registerRead(syntheticApi, foreverPath(), {
      status: 409, json: { status: "error", message: GTT_READ_FROZEN },
    });
    const expectedBody = {
      variety: "gtt", broker: BROKER, account_id: ACCOUNT_A,
      symbol: "SYNTHETIC-EQUITY", exchange: "NSE", action: "BUY", quantity: 10,
      trigger_price: 100, product: "CNC", price: 101, pricetype: "LIMIT", validity: "DAY",
    };
    syntheticApi.register({
      name: "production-equivalent GTT unsupported refusal", method: "POST", path: "/ft-api/api/v1/orders/place",
      expectedCalls: 1,
      handler: (request) => {
        assertRequest(request, "POST", "/ft-api/api/v1/orders/place");
        expect(request.postDataJSON()).toEqual(expectedBody);
        return { status: 422, json: { status: "error", code: "gtt_unsupported", message: GTT_REFUSAL } };
      },
    });
    await mountWidget(page, "foreverorders");
    await tickUntil(page, page.getByRole("alert").filter({ hasText: GTT_READ_FROZEN }));
    await expect(page.getByTestId("forever-orders-unavailable")).toBeVisible();
    await expect(page.getByText(GTT_EMPTY, { exact: true })).toHaveCount(0);
    await page.getByRole("alert").filter({ hasText: GTT_READ_FROZEN }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("alert").filter({ hasText: GTT_READ_FROZEN })).toBeInViewport({ ratio: 1 });
    await captureEvidence(page, info, "desktop-frozen-read-cutover-detail");
    await page.getByRole("textbox", { name: "GTT symbol" }).fill("SYNTHETIC-EQUITY");
    await page.getByRole("textbox", { name: "GTT quantity" }).fill("10");
    await page.getByRole("textbox", { name: "GTT trigger price" }).fill("100");
    await page.getByRole("textbox", { name: "GTT limit price" }).fill("101");
    await page.getByRole("button", { name: "Place GTT", exact: true }).click();
    await tickUntil(page, page.getByRole("alert").filter({ hasText: GTT_REFUSAL }));
    await expect(page.getByText("Forever order requested.", { exact: false })).toHaveCount(0);
    await expect(page.getByText("GTT placement status unknown.", { exact: false })).toHaveCount(0);
    await captureEvidence(page, info, "desktop-frozen-409-422-refusals");
    await captureNarrow(page, info, "narrow-frozen-409-422-refusals");
    presentationEvidence.assertWrites([{ method: "POST", path: "/ft-api/api/v1/orders/place", body: expectedBody }]);
    expect(syntheticApi.callCount("GET", foreverPath())).toBe(1);
  });
});

const SQUARE_OFF_BODY = {
  symbol: "SYNTHETIC-ALPHA", exchange: "NSE", action: "SELL", product: "CNC", orderType: "MARKET",
  quantity: 10, price: 0, triggerPrice: 0, strategy: "FlintPositions", rationale: "",
  order_type: "MARKET", trigger_price: 0, broker: BROKER, account_id: ACCOUNT_A,
};

for (const action of ["square-off", "exit-all"] as const) {
  test(`${action} acknowledgement does not prove an executed close`, async ({
    page, syntheticApi, presentationEvidence,
  }, info) => {
    registerDeskReads(syntheticApi);
    // Two mounted observers invalidate their orders query on an order ACK.
    // One successful initial read is mandatory; StrictMode can also abort one
    // initial GET. Pin the exact mutation-induced delta independently below.
    registerAccountBooks(syntheticApi, {
      positionCalls: 2,
      orderCalls: action === "square-off" ? { minimum: 3, maximum: 4 } : { minimum: 1, maximum: 2 },
    });
    const path = action === "square-off" ? "/ft-api/api/v1/orders/dhan/place" : "/ft-api/api/v1/positions/exit-all";
    const body = action === "square-off" ? SQUARE_OFF_BODY : { confirm: true, broker: BROKER, account_id: ACCOUNT_A };
    syntheticApi.register({
      name: `one synthetic ${action} ACK only`, method: "POST", path, expectedCalls: 1,
      handler: (request) => {
        assertRequest(request, "POST", path);
        expect(request.postDataJSON()).toEqual(body);
        return { json: { status: "success", data: { orderId: "SYNTHETIC-ACK-ONLY", accepted: true } } };
      },
    });
    await mountWidget(page, "positions");
    const surface = positionSurface(page);
    await tickUntil(page, surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA", exact: true }));
    await surface.getByRole("button", {
      name: action === "square-off" ? "Square off SYNTHETIC-ALPHA" : "Exit all positions", exact: true,
    }).click();
    const dialog = page.getByRole("dialog", { name: action === "square-off" ? "Square off position?" : "Exit all positions?" });
    await expect(dialog.getByText(EXECUTION_WARNING, { exact: true })).toBeVisible();
    if (action === "exit-all") await dialog.getByRole("textbox", { name: "Type EXIT (in capitals) to confirm" }).fill("EXIT");
    await captureEvidence(page, info, "desktop-execution-first-confirmation");
    const initialOrderReads = syntheticApi.callCount("GET", nativePath("orders"));
    expect(initialOrderReads).toBeGreaterThanOrEqual(1);
    expect(initialOrderReads).toBeLessThanOrEqual(2);
    await dialog.getByRole("button", {
      name: action === "square-off" ? "Confirm square off SYNTHETIC-ALPHA" : "Confirm exit all positions", exact: true,
    }).click();
    await page.clock.runFor(50);
    await expect(dialog).toHaveCount(0);
    await expect.poll(() => notifications(page)).toContainEqual(expect.objectContaining({
      title: action === "square-off" ? "Square-off submitted" : "Exit-all submitted",
      body: action === "square-off"
        ? "Exit requested: SELL 10 SYNTHETIC-ALPHA at market. Check positions and orders for the outcome."
        : "Exit-all requested. Check positions and orders for the outcome.",
    }));
    await page.getByRole("button", { name: /^Notifications/ }).click();
    // Finish the real notification panel's frame-based entrance. A paused
    // clock can satisfy DOM visibility while the panel is still off-screen.
    await page.clock.runFor(400);
    const submissionCopy = page.getByText(action === "square-off"
      ? "Exit requested: SELL 10 SYNTHETIC-ALPHA at market. Check positions and orders for the outcome."
      : "Exit-all requested. Check positions and orders for the outcome.", { exact: true });
    await expect(submissionCopy).toBeVisible();
    await expect(submissionCopy).toBeInViewport();
    await expect(surface.getByText("SYNTHETIC-ALPHA", { exact: true })).toBeVisible();
    await expect(page.getByText(/Every open position was squared off|Position closed|^CLOSED$|^Filled$/i)).toHaveCount(0);
    await captureEvidence(page, info, "desktop-ack-not-fill");
    // The submitted request leaves the same exposure in the actual query book.
    // A returned synthetic ID/ACK is never used as fill evidence.
    presentationEvidence.assertWrites([{ method: "POST", path, body }]);
    expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(2);
    expect(syntheticApi.callCount("GET", nativePath("orders"))).toBe(initialOrderReads + (action === "square-off" ? 2 : 0));
  });
}

test("a cancel-pending exit keeps risk visible in desktop tables and narrow cards", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi);
  registerAccountBooks(syntheticApi, {
    orders: { json: { status: "success", data: [exitRow()] } }, orderCalls: 1, orderReadPhase: "startup",
  });
  await mountWidget(page, "positions", true);
  const desktop = positionSurface(page);
  await tickUntil(page, desktop.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" }));
  await expect(desktop.getByRole("table").getByText("Exit pending", { exact: true })).toBeVisible();
  await expect(desktop.getByRole("table").getByText(CANCEL_WARNING, { exact: true })).toBeVisible();
  await expect(desktop.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toBeDisabled();
  await captureEvidence(page, info, "desktop-cancel-pending-exit");
  await captureNarrow(page, info, "narrow-cancel-pending-exit");
  const cards = desktop.getByRole("list", { name: "Positions", exact: true });
  await expect(cards).toBeVisible();
  await expect(cards).toContainText("Qty 10");
  await expect(cards).toContainText(CANCEL_WARNING);
  await expect(cards.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toBeDisabled();
  await expect(page.getByText(/Position closed|^CLOSED$|^Filled$/i)).toHaveCount(0);
  presentationEvidence.assertWrites([]);
  // Exactly one completed startup book is mandatory. Development StrictMode
  // may additionally cancel one observed GET, but that is not a second book.
  const startup = await syntheticApi.retireRead(nativePath("orders"));
  expect(startup.completed).toBe(1);
  expect(startup.cancelled).toBeLessThanOrEqual(1);
  expect(startup).toEqual({ calls: 1 + startup.cancelled, completed: 1,
    cancelled: startup.cancelled, pending: 0, failed: 0 });
  expect(syntheticApi.callCount("GET", nativePath("orders"))).toBe(startup.calls);
  expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(1);
  await info.attach("cancel-pending-startup-book", { body: JSON.stringify(startup), contentType: "application/json" });
});

test("a late A GTT listing cannot replace the selected B account book", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi, true);
  registerAccountBooks(syntheticApi);
  registerAccountBooks(syntheticApi, { account: ACCOUNT_B });
  const late = deferredResponse();
  registerRead(syntheticApi, foreverPath(), () => late.promise, 1);
  registerRead(syntheticApi, foreverPath(ACCOUNT_B), {
    json: { status: "success", data: [triggerRow(ACCOUNT_B)] },
  }, 1);
  try {
    await mountWidget(page, "foreverorders");
    await expect.poll(() => syntheticApi.callCount("GET", foreverPath())).toBe(1);
    await selectAccount(page, ACCOUNT_B);
    const table = page.getByRole("table", { name: "Forever orders" });
    await tickUntil(page, table.getByText(`SYNTHETIC-GTT-${ACCOUNT_B}`, { exact: true }));
    await expect(page.getByRole("combobox", { name: "Broker account" })).toContainText(ACCOUNT_B);
    const responseArrived = page.waitForResponse((response) => response.url().endsWith(foreverPath()));
    late.release({ json: { status: "success", data: [triggerRow(ACCOUNT_A, "CANCEL_PENDING")] } });
    await (await responseArrived).body();
    await page.clock.runFor(100);
    await expect(table.getByText(`SYNTHETIC-GTT-${ACCOUNT_A}`, { exact: true })).toHaveCount(0);
    await expect(table.getByText(`SYNTHETIC-GTT-${ACCOUNT_B}`, { exact: true })).toBeVisible();
    await expect(page.getByText(CANCEL_WARNING, { exact: false })).toHaveCount(0);
    expect(syntheticApi.callCount("GET", foreverPath(ACCOUNT_B))).toBe(1);
    await captureEvidence(page, info, "desktop-late-a-selected-b");
    await captureNarrow(page, info, "narrow-late-a-selected-b");
    presentationEvidence.assertWrites([]);
  } finally {
    late.release({ json: { status: "success", data: [triggerRow()] } });
  }
});

test("unavailable broker orders inhibit exits until a verified empty book arrives", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi);
  let recovered = false;
  registerAccountBooks(syntheticApi, {
    orderCalls: 3,
    orders: () => recovered
      ? { json: { status: "success", data: [] } }
      : { json: { status: "error", message: "Synthetic order evidence unavailable." } },
  });
  // Use the terminal's canonical bottom Positions panel once here. Mounting
  // two failed observers introduces an unrelated error-remount read race.
  registerRead(syntheticApi, foreverPath(), { json: { status: "success", data: [] } });
  await mountWidget(page, "foreverorders");
  const surface = positionSurface(page);
  await tickUntil(page, surface.getByTestId("exit-orders-unavailable").filter({ hasText: "Synthetic order evidence unavailable." }));
  await expect(surface.getByTestId("exit-orders-unavailable")).toContainText("Synthetic order evidence unavailable.");
  await expect(surface.getByText("SYNTHETIC-ALPHA", { exact: true })).toBeVisible();
  await expect(surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toHaveCount(0);
  await expect(surface.getByRole("button", { name: "Exit all positions" })).toHaveCount(0);
  await captureEvidence(page, info, "desktop-exits-inhibited-unavailable-orders");
  // A real public book-change notification exercises the existing query hook's
  // refresh contract. No query state, decoder or readiness guard is replaced.
  recovered = true;
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("flinttrade:ordersChanged")));
  await tickUntil(page, surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" }));
  await expect(surface.getByTestId("exit-orders-unavailable")).toHaveCount(0);
  await expect(surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toBeEnabled();
  await expect(surface.getByRole("button", { name: "Exit all positions" })).toBeEnabled();
  expect(syntheticApi.callCount("GET", nativePath("orders"))).toBe(3);
  presentationEvidence.assertWrites([]);
});

test.describe("lost cancellation response", () => {
  const cancelPath = `/ft-api/api/v1/orders/forever/SYNTHETIC-GTT-${ACCOUNT_A}?broker=dhan&account_id=${ACCOUNT_A}`;
  test.use({ benignConsoleErrors: [{
    text: "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
    url: `http://localhost:5173${cancelPath}`, expectedCalls: 1,
  }] });
  test("raw 503 detail remains unknown execution, not a cancelled order", async ({
    page, syntheticApi, presentationEvidence,
  }, info) => {
    registerDeskReads(syntheticApi);
    registerAccountBooks(syntheticApi);
    registerRead(syntheticApi, foreverPath(), { json: { status: "success", data: [triggerRow()] } });
    syntheticApi.register({
      name: "one synthetic lost cancellation response", method: "DELETE", path: cancelPath, expectedCalls: 1,
      handler: (request) => {
        assertRequest(request, "DELETE", cancelPath);
        return { status: 503, json: { status: "error", message: "Synthetic cancel response lost; execution outcome unknown." } };
      },
    });
    await mountWidget(page, "foreverorders");
    const table = page.getByRole("table", { name: "Forever orders" });
    await tickUntil(page, table);
    await table.getByRole("button", { name: "Cancel", exact: true }).click();
    await tickUntil(page, page.getByRole("alert").filter({ hasText: "Cancel status unknown. This order may still fill." }));
    await expect(page.getByRole("alert").filter({ hasText: "Synthetic cancel response lost; execution outcome unknown." })).toBeVisible();
    await expect(table.getByText("ACTIVE", { exact: true })).toBeVisible();
    await expect(page.getByText(CHILD_CAVEAT, { exact: true })).toBeVisible();
    await expect(page.getByText(/Order cancelled successfully|Position closed|^CLOSED$|^Filled$/i)).toHaveCount(0);
    await captureEvidence(page, info, "desktop-cancel-outcome-unknown");
    await captureNarrow(page, info, "narrow-cancel-outcome-unknown");
    presentationEvidence.assertWrites([{ method: "DELETE", path: cancelPath, body: null }]);
    expect(syntheticApi.callCount("GET", foreverPath())).toBe(1);
  });
});

for (const action of ["square-off", "exit-all"] as const) {
  for (const outcome of ["ACK", "unknown"] as const) {
    test.describe(`late ${action} ${outcome}`, () => {
      if (outcome === "unknown") {
        test.use({ benignConsoleErrors: [{
          text: "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
          url: action === "square-off"
            ? "http://localhost:5173/ft-api/api/v1/orders/dhan/place"
            : "http://localhost:5173/ft-api/api/v1/positions/exit-all",
          expectedCalls: 1,
        }] });
      }
      test("A response cannot notify, close a B dialog, refetch B, or place a B exit", async ({
        page, syntheticApi, presentationEvidence,
      }, info) => {
        registerDeskReads(syntheticApi, true);
        // One successful mount book; StrictMode may also cancel one initial
        // GET. Mutation/late-response counts below remain exact, independently
        // of that aborted initial read.
        registerAccountBooks(syntheticApi);
        registerAccountBooks(syntheticApi, { account: ACCOUNT_B, orderCalls: { minimum: 1, maximum: 2 } });
        const path = action === "square-off" ? "/ft-api/api/v1/orders/dhan/place" : "/ft-api/api/v1/positions/exit-all";
        const body = action === "square-off" ? SQUARE_OFF_BODY : { confirm: true, broker: BROKER, account_id: ACCOUNT_A };
        const late = deferredResponse();
        syntheticApi.register({
          name: `deferred A ${action} ${outcome}`, method: "POST", path, expectedCalls: 1,
          handler: (request) => {
            assertRequest(request, "POST", path);
            expect(request.postDataJSON()).toEqual(body);
            return late.promise;
          },
        });
        try {
          await mountWidget(page, "positions");
          const surface = positionSurface(page);
          await tickUntil(page, surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA", exact: true }));
          await surface.getByRole("button", {
            name: action === "square-off" ? "Square off SYNTHETIC-ALPHA" : "Exit all positions", exact: true,
          }).click();
          const dialogName = action === "square-off" ? "Square off position?" : "Exit all positions?";
          const dialogA = page.getByRole("dialog", { name: dialogName, exact: true });
          await expect(dialogA.getByText(EXECUTION_WARNING, { exact: true })).toBeVisible();
          if (action === "exit-all") await dialogA.getByRole("textbox", { name: "Type EXIT (in capitals) to confirm" }).fill("EXIT");
          await dialogA.getByRole("button", {
            name: action === "square-off" ? "Confirm square off SYNTHETIC-ALPHA" : "Confirm exit all positions", exact: true,
          }).click();
          await expect.poll(() => syntheticApi.callCount("POST", path)).toBe(1);
          await selectAccount(page, ACCOUNT_B);
          await tickUntil(page, surface.getByRole("button", { name: "Square off SYNTHETIC-BETA", exact: true }));
          await expect(dialogA).toHaveCount(0);
          await surface.getByRole("button", {
            name: action === "square-off" ? "Square off SYNTHETIC-BETA" : "Exit all positions", exact: true,
          }).click();
          const dialogB = page.getByRole("dialog", { name: dialogName, exact: true });
          await expect(dialogB).toBeVisible();
          if (action === "exit-all") await dialogB.getByRole("textbox", { name: "Type EXIT (in capitals) to confirm" }).fill("EXIT");
          else await expect(dialogB).toContainText("SYNTHETIC-BETA");
          const aPositionReads = syntheticApi.callCount("GET", nativePath("positions"));
          const aOrderReads = syntheticApi.callCount("GET", nativePath("orders"));
          const bPositionReads = syntheticApi.callCount("GET", nativePath("positions", ACCOUNT_B));
          const bOrderReads = syntheticApi.callCount("GET", nativePath("orders", ACCOUNT_B));
          expect(bPositionReads).toBe(1);
          expect(bOrderReads).toBeGreaterThanOrEqual(1);
          const notificationsBefore = await notifications(page);
          const responseArrived = page.waitForResponse((response) => response.url().endsWith(path));
          late.release(outcome === "ACK"
            ? { json: { status: "success", data: { accepted: true, orderId: "SYNTHETIC-A-LATE-ACK" } } }
            : { status: 503, json: { status: "error", message: "Synthetic A response lost after submission; execution outcome unknown." } });
          await (await responseArrived).body();
          await page.clock.runFor(100);
          await expect(dialogB).toBeVisible();
          await expect(dialogB.getByRole("button", {
            name: action === "square-off" ? "Confirm square off SYNTHETIC-BETA" : "Confirm exit all positions", exact: true,
          })).toBeEnabled();
          await expect(dialogB.getByRole("alert")).toHaveCount(0);
          expect(await notifications(page)).toEqual(notificationsBefore);
          expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(aPositionReads);
          expect(syntheticApi.callCount("GET", nativePath("orders"))).toBe(aOrderReads);
          expect(syntheticApi.callCount("GET", nativePath("positions", ACCOUNT_B))).toBe(bPositionReads);
          expect(syntheticApi.callCount("GET", nativePath("orders", ACCOUNT_B))).toBe(bOrderReads);
          await expect(surface.getByText("SYNTHETIC-BETA", { exact: true })).toBeVisible();
          await captureEvidence(page, info, "desktop-retired-a-current-b-dialog");
          presentationEvidence.assertWrites([{ method: "POST", path, body }]);
        } finally {
          late.release({ json: { status: "success", data: { accepted: true } } });
        }
      });
    });
  }
}

