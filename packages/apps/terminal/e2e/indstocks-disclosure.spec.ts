import {
  LIVE_TOKEN, assertRequest, captureEvidence, captureNarrow, deferredResponse, expect, notifications, test, tickUntil,
} from "./order-flow-fixtures";
import {
  ACTIVATION_REFUSAL, GTT_NOTICE, IND_A, IND_B, IND_BODY, IND_WRITE, MARKET_NOTICE,
  acknowledgement, accountSnapshot, assertDisclosureA11y, indPath, mountIndstocksPad, orderPad, registerIndstocksReads, selectIndstocksScope,
} from "./indstocks-disclosure-fixtures";

const refusalAllowance = {
  text: "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
  url: `http://localhost:5173${IND_WRITE}`, expectedCalls: 1,
};

test.describe("held INDstocks activation, not availability", () => {
  test.use({ benignConsoleErrors: [refusalAllowance] });
  test("Live MARKET disclosure precedes existing Place and Close controls and a refused activation stays refused", async ({ page, syntheticApi, presentationEvidence }, info) => {
    registerIndstocksReads(syntheticApi, { openPosition: true });
    syntheticApi.register({ name: "held INDstocks activation", method: "POST", path: IND_WRITE, expectedCalls: 1, handler: (request) => {
      assertRequest(request, "POST", IND_WRITE);
      expect(request.postDataJSON()).toEqual(IND_BODY);
      return { status: 503, json: { status: "error", code: "native_activation_unavailable", message: ACTIVATION_REFUSAL } };
    } });
    await mountIndstocksPad(page);
    const pad = orderPad(page);
    const notice = pad.getByRole("note", { name: "INDstocks execution limitation" });
    await tickUntil(page, pad.getByText("Lot: 1", { exact: true }));
    await tickUntil(page, pad.getByRole("button", { name: "Close", exact: true }));
    await expect.poll(() => accountSnapshot(page)).toMatchObject({ mode: "live", scopeKey: "live:native:indmoney:IND-OFFLINE", readsEnabled: true, writeTarget: { broker: "indmoney", accountId: IND_A } });
    await expect(notice).toHaveText(MARKET_NOTICE);
    const submit = pad.getByRole("button", { name: "Place BUY Order", exact: true });
    for (const control of [submit, pad.getByRole("button", { name: "Close", exact: true })]) {
      expect(await notice.evaluate((element, button) => Boolean(element.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING), await control.elementHandle())).toBe(true);
    }
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await notice.scrollIntoViewIfNeeded();
    await expect(notice).toBeInViewport({ ratio: 1 });
    await assertDisclosureA11y(page, info, "desktop-market-notice", ['[aria-label="INDstocks execution limitation"]']);
    await captureEvidence(page, info, "desktop-market-before-existing-actions");
    await submit.click();
    await tickUntil(page, pad.getByRole("alert").filter({ hasText: ACTIVATION_REFUSAL }));
    await expect(pad.getByRole("status", { name: "INDstocks submission disclosure" })).toHaveCount(0);
    await expect(pad.getByText(/Order placed|Order filled|Position closed/i)).toHaveCount(0);
    await expect(submit).toBeEnabled();
    await expect(notice).toHaveText(MARKET_NOTICE);
    await captureEvidence(page, info, "desktop-activation-refused");
    presentationEvidence.assertWrites([{ method: "POST", path: IND_WRITE, body: IND_BODY }]);
    expect(syntheticApi.callCount("GET", indPath("positions"))).toBeGreaterThanOrEqual(1);
    expect(syntheticApi.callCount("GET", indPath("orders"))).toBeGreaterThanOrEqual(1);
  });
});

test("LIMIT retains its supplied native price without MARKET conversion copy", async ({ page, syntheticApi, presentationEvidence }, info) => {
  registerIndstocksReads(syntheticApi);
  const body = { ...IND_BODY, orderType: "LIMIT", order_type: "LIMIT", price: 73.55 };
  syntheticApi.register({ name: "LIMIT presentation ACK only", method: "POST", path: IND_WRITE, expectedCalls: 1, handler: (request) => {
    assertRequest(request, "POST", IND_WRITE);
    expect(request.postDataJSON()).toEqual(body);
    return { json: {
      status: "success", orderid: "SYNTHETIC-LIMIT-ACK", data: "SYNTHETIC-LIMIT-ACK",
      order_ids: ["SYNTHETIC-LIMIT-ACK"], child_order_id: null,
      execution_effects: { requested_type: "LIMIT", effective_type: "LIMIT", effective_limit_price: 73.55, trailing_active: false, limitations: [] },
      broker_response: { order_id: "SYNTHETIC-LIMIT-ACK", order_status: "INITIATED" },
    } };
  } });
  await mountIndstocksPad(page);
  const pad = orderPad(page);
  await tickUntil(page, pad.getByText("Lot: 1", { exact: true }));
  await pad.getByRole("radio", { name: "LIMIT", exact: true }).click();
  await pad.getByRole("spinbutton", { name: "Price", exact: true }).fill("73.55");
  await expect(pad.getByRole("note", { name: "INDstocks execution limitation" })).toHaveCount(0);
  await pad.getByRole("button", { name: "Place BUY Order", exact: true }).click();
  await tickUntil(page, pad.getByRole("alert").filter({ hasText: "Order requested · ID: SYNTHETIC-LIMIT-ACK" }));
  await expect(pad.getByRole("spinbutton", { name: "Price", exact: true })).toHaveValue("73.55");
  await captureEvidence(page, info, "desktop-limit-price-retained");
  presentationEvidence.assertWrites([{ method: "POST", path: IND_WRITE, body }]);
});

for (const guard of ["disconnected", "read-only", "bare-selector", "missing-selection"] as const) {
  test(`${guard} cannot turn disclosure into native write authority`, async ({ page, syntheticApi, presentationEvidence }, info) => {
    registerIndstocksReads(syntheticApi, { hasSession: guard !== "disconnected", readOnly: guard === "read-only" });
    // IND_WRITE deliberately unregistered: even a swallowed attempted POST is
    // a fatal fail-closed registry error, not merely a zero-count assertion.
    await mountIndstocksPad(page);
    const pad = orderPad(page);
    if (guard === "bare-selector") await selectIndstocksScope(page, IND_A);
    if (guard === "missing-selection") await selectIndstocksScope(page, null);
    await expect.poll(() => accountSnapshot(page)).toMatchObject({ writeTarget: null });
    await info.attach("guard-account-readiness", { body: JSON.stringify(await accountSnapshot(page), null, 2), contentType: "application/json" });
    const submit = pad.getByRole("button", { name: "Place BUY Order", exact: true });
    await submit.click();
    await tickUntil(page, pad.getByRole("alert").filter({ hasText: "Your selected native broker is not available for live writes" }));
    await expect(pad.getByRole("status", { name: "INDstocks submission disclosure" })).toHaveCount(0);
    await captureEvidence(page, info, `desktop-${guard}-pre-post-refusal`);
    presentationEvidence.assertWrites([]);
    expect(syntheticApi.callCount("POST", IND_WRITE)).toBe(0);
  });
}

test("disabled GTT wrapper exposes ignored-trailing refusal by keyboard and wraps in a narrow real panel", async ({ page, syntheticApi, presentationEvidence }, info) => {
  registerIndstocksReads(syntheticApi);
  await mountIndstocksPad(page, { narrowPanel: true });
  const pad = orderPad(page);
  const gtt = pad.getByRole("button", { name: "GTT", exact: true });
  await expect(gtt).toBeDisabled();
  await expect(gtt).toHaveAttribute("title", GTT_NOTICE);
  const wrapper = gtt.locator("..");
  await pad.getByRole("radio", { name: "MARKET", exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(wrapper).toBeFocused();
  const tooltip = page.getByRole("tooltip").filter({ hasText: GTT_NOTICE });
  await tickUntil(page, tooltip);
  await expect(tooltip).toContainText(GTT_NOTICE);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await assertDisclosureA11y(page, info, "desktop-gtt-keyboard-availability", ['[data-tour-target="order-pad"] span:has(> button[aria-label="GTT"])', '[role="tooltip"]']);
  await captureEvidence(page, info, "desktop-keyboard-gtt-unavailable");
  await page.keyboard.press("Escape");
  const notice = pad.getByRole("note", { name: "INDstocks execution limitation" });
  await captureNarrow(page, info, "narrow-indstocks-wrapper", false);
  await notice.scrollIntoViewIfNeeded();
  await expect(notice).toHaveText(MARKET_NOTICE);
  await expect(notice).toBeInViewport({ ratio: 1 });
  expect(await notice.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await notice.evaluate((element) => element.getBoundingClientRect().height > Number.parseFloat(getComputedStyle(element).lineHeight))).toBe(true);
  await assertDisclosureA11y(page, info, "narrow-market-notice", ['[aria-label="INDstocks execution limitation"]']);
  await captureEvidence(page, info, "narrow-wrapped-market-notice");
  await wrapper.hover();
  await tickUntil(page, tooltip);
  await expect(tooltip).toContainText(GTT_NOTICE);
  await expect(tooltip).toBeInViewport();
  await captureEvidence(page, info, "narrow-wrapped-notice-and-gtt-tooltip");
  presentationEvidence.assertWrites([]);
});

for (const mode of ["practice", "explore"] as const) {
  test(`${mode} keeps paper review and transport separate from native conversion`, async ({ page, syntheticApi, presentationEvidence }, info) => {
    registerIndstocksReads(syntheticApi, { mode });
    const { broker: _broker, account_id: _account, ...body } = IND_BODY;
    if (mode === "practice") syntheticApi.register({ name: "Practice paper ACK", method: "POST", path: "/ft-api/api/v1/orders/place", expectedCalls: 1, handler: (request) => {
      expect(request.method()).toBe("POST");
      expect(request.url()).toBe("http://localhost:5173/ft-api/api/v1/orders/place");
      expect(request.headers()["authorization"]).toBe(`Bearer ${LIVE_TOKEN}`);
      expect(request.headers()["content-type"]).toBe("application/json");
      expect(request.headers()["x-flinttrade-mode"]).toBe("practice");
      expect(request.headers()["x-api-key"]).toBeUndefined();
      expect(request.postDataJSON()).toEqual(body);
      return { json: { status: "success", data: { order_id: "SYNTHETIC-PAPER" } } };
    } });
    await mountIndstocksPad(page, { mode });
    const pad = orderPad(page);
    await expect(pad.getByRole("note", { name: "INDstocks execution limitation" })).toHaveCount(0);
    await expect(pad.getByRole("button", { name: "GTT", exact: true })).toHaveAttribute("title", "GTT orders aren't supported right now.");
    await pad.getByRole("button", { name: mode === "practice" ? "Practice Buy" : "Example Buy", exact: true }).click();
    const review = page.getByRole("dialog", { name: mode === "practice" ? "Review Practice order" : "Review Example order" });
    await expect(review).toBeVisible();
    await expect(review).not.toContainText(/INDstocks|converting to LIMIT|trailing protection/i);
    await captureEvidence(page, info, `${mode}-paper-review-not-native-conversion`);
    await review.getByRole("button", { name: mode === "practice" ? "Confirm simulated Practice order" : "Confirm Example order", exact: true }).click();
    await tickUntil(page, pad.getByRole("alert"));
    await expect(pad.getByRole("status", { name: "INDstocks submission disclosure" })).toHaveCount(0);
    presentationEvidence.assertWrites(mode === "practice" ? [{ method: "POST", path: "/ft-api/api/v1/orders/place", body }] : []);
    if (mode === "explore") expect(syntheticApi.callCount("GET", "/ft-api/api/v1/native/accounts")).toBe(0);
  });
}

test("returned native scalar-data/top-level receipt retains requested MARKET, documented LIMIT and unknown price when the next form changes", async ({ page, syntheticApi, presentationEvidence }, info) => {
  registerIndstocksReads(syntheticApi);
  syntheticApi.register({ name: "per-call INDstocks receipt presentation", method: "POST", path: IND_WRITE, expectedCalls: 1, handler: (request) => {
    assertRequest(request, "POST", IND_WRITE);
    expect(request.postDataJSON()).toEqual(IND_BODY);
    return { json: acknowledgement() };
  } });
  await mountIndstocksPad(page);
  const pad = orderPad(page);
  const responseArrived = page.waitForResponse((response) => response.url().endsWith(IND_WRITE));
  await pad.getByRole("button", { name: "Place BUY Order", exact: true }).click();
  const rawResponse = await responseArrived;
  await rawResponse.finished();
  const rawAck: Record<string, unknown> = await rawResponse.json();
  expect(rawAck.data).toBe("SYNTHETIC-IND-ACK");
  expect(rawAck.orderid).toBe("SYNTHETIC-IND-ACK");
  expect(rawAck.order_ids).toEqual(["SYNTHETIC-IND-ACK"]);
  expect(rawAck.child_order_id).toBeNull();
  expect(rawAck.execution_effects).toEqual({ requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: null, trailing_active: false, limitations: ["MARKET_TO_LIMIT"] });
  expect(rawAck.broker_response).toEqual({ order_id: "SYNTHETIC-IND-ACK", order_status: "INITIATED", extra_info: { observations: ["accepted", null] } });
  await info.attach("actual-native-envelope", { body: JSON.stringify(rawAck, null, 2), contentType: "application/json" });
  const receipt = pad.getByRole("status", { name: "INDstocks submission disclosure" });
  await tickUntil(page, receipt);
  await expect(receipt).toContainText("Submission ID: SYNTHETIC-IND-ACK");
  await expect(receipt).toContainText("Requested: MARKET. Documented execution: LIMIT.");
  await expect(receipt).toContainText("Effective limit price: unknown.");
  await expect(receipt).toContainText("Trailing protection: inactive. Submission acknowledgement is not a fill.");
  await expect(receipt).not.toContainText(/₹|filled|closed|protection is active/i);
  // Centre the checkpoint using the real scrolling container. Nearest-edge
  // scrolling can leave a fractional border pixel clipped in Chromium.
  await receipt.evaluate((element) => element.scrollIntoView({ block: "center", inline: "nearest" }));
  await expect(receipt).toBeInViewport({ ratio: 1 });
  await assertDisclosureA11y(page, info, "desktop-per-call-disclosure", ['[aria-label="INDstocks submission disclosure"]']);
  await captureEvidence(page, info, "desktop-market-ack-documented-limit-unknown-price");
  await pad.getByRole("radio", { name: "LIMIT", exact: true }).click();
  await pad.getByRole("spinbutton", { name: "Price", exact: true }).fill("73.55");
  await expect(pad.getByRole("note", { name: "INDstocks execution limitation" })).toHaveCount(0);
  await expect(receipt).toContainText("Requested: MARKET. Documented execution: LIMIT.");
  await expect(receipt).toContainText("Effective limit price: unknown.");
  await captureEvidence(page, info, "desktop-next-limit-ticket-keeps-old-market-receipt");
  // The price input's focus scrolls the receipt below the fold. Capture its
  // actual displayed state too, with the edited LIMIT summary above it.
  await receipt.evaluate((element) => element.scrollIntoView({ block: "center", inline: "nearest" }));
  await expect(receipt).toBeVisible();
  await expect(receipt).toBeInViewport({ ratio: 1 });
  await expect(pad.getByText("73.55", { exact: true })).toBeVisible();
  await captureEvidence(page, info, "desktop-edited-limit-summary-original-market-receipt");
  await selectIndstocksScope(page, `native:indmoney:${IND_B}`);
  await expect(receipt).toHaveCount(0);
  presentationEvidence.assertWrites([{ method: "POST", path: IND_WRITE, body: IND_BODY }]);
});

test("legacy scalar receipt keeps its ID and requested-only vocabulary", async ({ page, syntheticApi, presentationEvidence }, info) => {
  registerIndstocksReads(syntheticApi);
  syntheticApi.register({ name: "legacy scalar presentation ACK", method: "POST", path: IND_WRITE, expectedCalls: 1, handler: (request) => {
    assertRequest(request, "POST", IND_WRITE);
    expect(request.postDataJSON()).toEqual(IND_BODY);
    return { json: { status: "success", orderid: "SYNTHETIC-IND-SCALAR", data: "SYNTHETIC-IND-SCALAR" } };
  } });
  await mountIndstocksPad(page);
  const pad = orderPad(page);
  await pad.getByRole("button", { name: "Place BUY Order", exact: true }).click();
  const toast = pad.getByRole("alert");
  await tickUntil(page, toast);
  await expect(toast).toContainText("Order requested · ID: SYNTHETIC-IND-SCALAR");
  await expect(toast).not.toContainText(/filled|closed|placed/i);
  await expect(pad.getByRole("status", { name: "INDstocks submission disclosure" })).toHaveCount(0);
  await captureEvidence(page, info, "desktop-scalar-ack-not-fill");
  presentationEvidence.assertWrites([{ method: "POST", path: IND_WRITE, body: IND_BODY }]);
});

for (const nextScope of ["account-B", "Practice"] as const) {
  test(`delayed A acknowledgement cannot relabel or invalidate ${nextScope}`, async ({ page, syntheticApi, presentationEvidence }, info) => {
    registerIndstocksReads(syntheticApi, { accountSwitch: true });
    const late = deferredResponse();
    syntheticApi.register({ name: "deferred A INDstocks receipt", method: "POST", path: IND_WRITE, expectedCalls: 1, handler: (request) => {
      assertRequest(request, "POST", IND_WRITE);
      expect(request.postDataJSON()).toEqual(IND_BODY);
      return late.promise;
    } });
    try {
      await mountIndstocksPad(page);
      const pad = orderPad(page);
      await pad.getByRole("button", { name: "Place BUY Order", exact: true }).click();
      await expect.poll(() => syntheticApi.callCount("POST", IND_WRITE)).toBe(1);
      await selectIndstocksScope(page, `native:indmoney:${IND_B}`, nextScope === "Practice" ? "practice" : undefined);
      const ordersPath = nextScope === "Practice" ? "/ft-api/v1/sandbox/orders" : indPath("orders", IND_B);
      const positionsPath = nextScope === "Practice" ? "/ft-api/v1/sandbox/positions" : indPath("positions", IND_B);
      await expect.poll(() => syntheticApi.callCount("GET", ordersPath)).toBeGreaterThanOrEqual(1);
      await expect.poll(() => syntheticApi.callCount("GET", positionsPath)).toBeGreaterThanOrEqual(1);
      await page.clock.runFor(100);
      const paths = [indPath("orders"), indPath("positions"), ordersPath, positionsPath];
      const beforeReads = paths.map((path) => syntheticApi.callCount("GET", path));
      const beforeNotifications = await notifications(page);
      const beforeScope = await accountSnapshot(page);
      expect(beforeScope).toMatchObject({ activeAccountId: `native:indmoney:${IND_B}`, scopeKey: nextScope === "Practice" ? "practice:sandbox:default" : "live:native:indmoney:IND-OFFLINE-B", readsEnabled: true });
      await info.attach("before-late-ack-scope", { body: JSON.stringify({ scope: beforeScope, paths, reads: beforeReads, notifications: beforeNotifications }, null, 2), contentType: "application/json" });
      const responseArrived = page.waitForResponse((response) => response.url().endsWith(IND_WRITE));
      late.release({ json: acknowledgement("SYNTHETIC-LATE-A") });
      const response = await responseArrived;
      await response.finished();
      expect(await response.json()).toEqual(acknowledgement("SYNTHETIC-LATE-A"));
      await tickUntil(page, pad.getByRole("button", { name: nextScope === "Practice" ? "Practice Buy" : "Place BUY Order", exact: true }));
      await page.clock.runFor(100);
      await expect(pad.getByRole("button", { name: nextScope === "Practice" ? "Practice Buy" : "Place BUY Order", exact: true })).toBeEnabled();
      await expect(pad.getByRole("status", { name: "INDstocks submission disclosure" })).toHaveCount(0);
      await expect(pad.getByText("SYNTHETIC-LATE-A", { exact: false })).toHaveCount(0);
      expect(paths.map((path) => syntheticApi.callCount("GET", path))).toEqual(beforeReads);
      expect(await notifications(page)).toEqual([...beforeNotifications, expect.objectContaining({
        accountScopeKey: "live:native:indmoney:IND-OFFLINE", skipAccountRefresh: true,
        title: "Order requested: BUY 1 RELIANCE", body: "Order requested · ID: SYNTHETIC-LATE-A. Submission acknowledgement is not a fill. Check broker positions and orders.",
      })]);
      expect(await accountSnapshot(page)).toEqual(beforeScope);
      await info.attach("after-late-ack-scope", { body: JSON.stringify({ scope: await accountSnapshot(page), paths, reads: paths.map((path) => syntheticApi.callCount("GET", path)), notifications: await notifications(page) }, null, 2), contentType: "application/json" });
      await expect(page.getByRole("button", { name: `Active account: INDMONEY · ${IND_B}. Click to switch account.`, exact: true })).toBeVisible();
      await captureEvidence(page, info, `desktop-late-A-retired-current-${nextScope}`);
      presentationEvidence.assertWrites([{ method: "POST", path: IND_WRITE, body: IND_BODY }]);
    } finally {
      late.release({ json: acknowledgement("SYNTHETIC-LATE-A") });
    }
  });
}

test("rendered gateway notices separate connection and Live selection from market readiness and outstanding broker orders", async ({ page, syntheticApi, presentationEvidence }, info) => {
  registerIndstocksReads(syntheticApi, { accountSwitch: true, marketScopeVisits: 3 });
  await mountIndstocksPad(page);
  await page.getByRole("button", { name: /^Notifications/ }).click();
  await page.clock.runFor(400);
  const restored = page.getByText("Gateway connection restored. Check market-data and broker readiness before trading.", { exact: true });
  await expect(restored).toBeVisible();
  // The feed intentionally suppresses first-mount mode notices. Exercise an
  // actual public mode transition rather than expecting an invented startup event.
  await selectIndstocksScope(page, `native:indmoney:${IND_A}`, "practice");
  await selectIndstocksScope(page, `native:indmoney:${IND_A}`, "live");
  await expect.poll(() => syntheticApi.callCount("GET", `${indPath("expiry")}?symbol=GOLD&exchange=MCX`)).toBe(3);
  await expect.poll(() => syntheticApi.callCount("GET", `${indPath("quotes")}?symbol=NIFTY&exchange=NSE_INDEX`)).toBe(3);
  await expect(page.getByText("Live mode is real-money capable. Broker readiness and safety checks still apply.", { exact: true })).toBeVisible();
  await expect(page.getByText(/live market data and routing are available|orders are now routed/i)).toHaveCount(0);
  await captureEvidence(page, info, "desktop-connection-not-market-readiness");
  await page.evaluate(async () => {
    // Fixed module adapter, not an interpolated executable string. Use the
    // public connection transition action; never replace write readiness.
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const connection = await importModule("/src/stores/connectionStore.ts") as { useConnectionStore: { getState: () => { setStatus: (status: "disconnected") => void } } };
    connection.useConnectionStore.getState().setStatus("disconnected");
  });
  await page.clock.runFor(50);
  const outstanding = page.getByText("Gateway unavailable. Broker orders may still be active; reconnect and reconcile positions and orders.", { exact: true });
  await expect(outstanding).toBeVisible();
  await expect(page.getByText(/routing is paused|all orders are paused/i)).toHaveCount(0);
  await captureEvidence(page, info, "desktop-disconnect-not-exchange-cancellation");
  presentationEvidence.assertWrites([]);
});
