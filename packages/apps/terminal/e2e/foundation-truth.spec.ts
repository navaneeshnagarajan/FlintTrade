import { LIVE_TOKEN, captureEvidence, captureNarrow, notifications, registerRead } from "./order-flow-fixtures";
import {
  ACCOUNT_A, ACCOUNT_B, DISCOVERY, aggregateBooks, book, browserNetwork, choose, counts, deliverOfflineEvent, discovery,
  expect, fills, finishRetries, finishTradeRetries, funds, hold, journal, literalPaint, mount, nativePath, ok, position, pump,
  mountUnavailableRisk, queryObservations, recoveryReads, riskReads, SAFETY, safety, session, sessionBooks, snapshot, test,
} from "./foundation-truth-fixtures";

// All input amounts/identities are synthetic HTTP payloads, not rendered state.
// The auto fixture preserves exact network bodies, assertions caught by product
// fetch, client errors, screenshots and a zero-write ledger on every journey.
test.afterEach(async ({ presentationEvidence, foundationWrites }) => { presentationEvidence.assertWrites(foundationWrites); });

test("A1 current B defers resources independently and cannot paint A or an invented zero", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1);
  aggregateBooks(syntheticApi);
  const bFunds = hold(); const bPositions = hold();
  book(syntheticApi, "funds", bFunds.handler, ACCOUNT_B);
  book(syntheticApi, "positions", bPositions.handler, ACCOUNT_B);
  try {
    await mount(page, "aggregate");
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
    await expect(page.getByTestId("welcome-card")).toContainText("+₹75");
    await choose(page, ACCOUNT_B);
    await Promise.all([bFunds.started, bPositions.started]);
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "loading");
    await expect(page.getByTestId("welcome-card")).not.toContainText("₹75");
    await expect(page.getByTestId("welcome-card")).not.toContainText("₹0");
    await expect(page.getByTestId("welcome-card")).toContainText(/Loading|unavailable/i);
    await captureEvidence(page, info, "b-deferred-desktop");
    bFunds.release(funds(2300));
    await pump(page, async () => (await snapshot(page))["fundsStatus"] === "ready");
    expect(await snapshot(page)).toMatchObject({ availableMargin: 2300, fundsStatus: "ready", positionsStatus: "loading" });
    await expect(page.getByTestId("welcome-card")).not.toContainText("₹75");
    bPositions.release(ok([position("SYNTHETIC-BETA", -25)]));
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
    await expect(page.getByTestId("positions-card")).toContainText("SYNTHETIC-BETA");
    await expect(page.getByTestId("welcome-card")).toContainText("-₹25");
    expect(await snapshot(page)).toMatchObject({ availableMargin: 2300, totalPnl: -25 });
    await captureNarrow(page, info, "b-ready-compact");
  } finally { bFunds.release(funds(2300)); bPositions.release(ok([position("SYNTHETIC-BETA", -25)])); }
});

for (const late of ["success", "error"] as const) {
  test(`A2 retired A ${late} cannot contaminate completed B`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1);
    const aFunds = hold(); const aPositions = hold();
    book(syntheticApi, "funds", aFunds.handler); book(syntheticApi, "positions", aPositions.handler);
    book(syntheticApi, "funds", funds(2300), ACCOUNT_B); book(syntheticApi, "positions", ok([]), ACCOUNT_B);
    try {
      await mount(page, "aggregate");
      await pump(page, async () => syntheticApi.callCount("GET", nativePath("positions")) === 1);
      await Promise.all([aFunds.started, aPositions.started]);
      await choose(page, ACCOUNT_B);
      await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready" && (await snapshot(page))["fundsStatus"] === "ready");
      const baseline = await snapshot(page); const notices = await notifications(page);
      const paths = [DISCOVERY, ...[ACCOUNT_A, ACCOUNT_B].flatMap((account) => [nativePath("funds", account), nativePath("positions", account)])];
      const baselineCounts = counts(syntheticApi, paths);
      const response = late === "success" ? ok([position("SYNTHETIC-RETIRED", 9999)]) : { json: { status: "error", message: "Synthetic retired read failed" } };
      aFunds.release(late === "success" ? funds(9900) : response); aPositions.release(response);
      await expect.poll(() => syntheticApi.readCounts(nativePath("funds")).pending).toBe(0);
      await expect.poll(() => syntheticApi.readCounts(nativePath("positions")).pending).toBe(0);
      expect(syntheticApi.readCounts(nativePath("funds"))).toMatchObject({ calls: 1, cancelled: 1, completed: 0 });
      expect(syntheticApi.readCounts(nativePath("positions"))).toMatchObject({ calls: 1, cancelled: 1, completed: 0 });
      // Confirmed cancellation plus handler release; no current-generation write.
      await page.clock.runFor(200);
      expect(await snapshot(page)).toEqual(baseline);
      expect(await notifications(page)).toEqual(notices);
      expect(counts(syntheticApi, paths)).toEqual(baselineCounts);
      await info.attach("retirement-baseline", { body: JSON.stringify({ baseline, after: await snapshot(page), baselineCounts, afterCounts: counts(syntheticApi, paths), notices, afterNotices: await notifications(page), retiredFunds: syntheticApi.readCounts(nativePath("funds")), retiredPositions: syntheticApi.readCounts(nativePath("positions")) }, null, 2), contentType: "application/json" });
      await expect(page.getByTestId("welcome-card")).toContainText("₹0");
      await expect(page.getByTestId("positions-card")).not.toContainText("SYNTHETIC-RETIRED");
      await captureEvidence(page, info, `retired-a-${late}`);
    } finally { aFunds.release(funds(9900)); aPositions.release(ok([])); }
  });
}

test("A3 disconnected B retires foreign aggregates and Explore makes no reads", async ({ page, syntheticApi }) => {
  discovery(syntheticApi, 1, true); aggregateBooks(syntheticApi);
  await mount(page, "aggregate");
  await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
  await choose(page, ACCOUNT_B);
  await pump(page, async () => (await snapshot(page))["positionsStatus"] === "unavailable");
  await expect(page.getByTestId("welcome-card")).not.toContainText("₹75");
  await expect(page.getByTestId("welcome-card")).not.toContainText("₹0");
  await expect(page.getByTestId("positions-card")).toContainText(/Connect a broker/i);
  const baseline = counts(syntheticApi, [DISCOVERY, nativePath("funds"), nativePath("positions")]);
  await page.getByRole("button", { name: "Select Explore", exact: true }).click();
  await page.clock.runFor(100);
  await expect(page.getByTestId("mode-honesty-bar")).toHaveAttribute("data-mode", "explore");
  expect(counts(syntheticApi, Object.keys(baseline))).toEqual(baseline);
});

test("A4 real zero funds and genuinely empty positions are available zero", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi, 0, 0);
  await mount(page, "aggregate");
  await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready" && (await snapshot(page))["fundsStatus"] === "ready");
  expect(await snapshot(page)).toMatchObject({ totalPnl: 0, availableMargin: 0, positionCount: 0 });
  await expect(page.getByTestId("welcome-card")).toContainText("₹0");
  await expect(page.getByTestId("positions-card")).toContainText("No open positions");
  await captureEvidence(page, info, "genuine-zero-desktop");
});

test("A4 malformed positions are not zero while valid funds remain available", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1);
  book(syntheticApi, "funds", funds(0));
  book(syntheticApi, "positions", ok(null));
  await mount(page, "aggregate");
  // Positions deliberately disables retry; unavailable is a completed error.
  await pump(page, async () => (await snapshot(page))["positionsStatus"] === "unavailable");
  expect(await snapshot(page)).toMatchObject({ fundsStatus: "ready", availableMargin: 0 });
  await expect(page.getByTestId("welcome-card")).not.toContainText("₹0");
  await expect(page.getByTestId("positions-card")).toContainText("Positions unavailable");
  await captureEvidence(page, info, "malformed-unavailable");
});

for (const mode of ["live", "practice"] as const) {
  for (const content of ["empty", "open-only"] as const) {
    test(`S1 ${mode} ${content} never becomes sample closed trips`, async ({ page, syntheticApi }, info) => {
      discovery(syntheticApi, 1);
      sessionBooks(syntheticApi, content === "empty" ? [] : fills("SYNTHETIC-OPEN").slice(0, 1), [], mode);
      await mount(page, "session", mode);
      await pump(page, () => session(page).getByRole("table", { name: "Today's trade log" }).isVisible());
      await expect(session(page)).toContainText("No round trips closed yet today.");
      await expect(session(page).getByRole("table", { name: "Today's trade log" }).locator("tbody tr")).toHaveCount(0);
      await expect(session(page)).not.toContainText(/RELIANCE|BANKNIFTY|SAMPLE|SYNTHETIC-OPEN/);
      await expect(session(page).locator("section[aria-labelledby=ss-orders]")).toHaveText(/Orders\s*Placed\s*0\s*Filled\s*0\s*Rejected\s*0\s*Pending\s*0/);
      await expect(session(page)).not.toContainText(/Loading orders|Orders unavailable/);
      await captureEvidence(page, info, `${mode}-${content}`);
    });
  }
}

test("S2 valid closed trades survive independently unavailable orders", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi); journal(syntheticApi);
  book(syntheticApi, "trades", ok(fills()));
  book(syntheticApi, "orders", { json: { status: "error", message: "Synthetic order book unavailable" } });
  await mount(page, "session");
  await pump(page, () => session(page).getByText(/Orders unavailable/i).isVisible());
  await expect(session(page).getByRole("table")).toContainText("SYNTHETIC-CLOSED");
  await expect(session(page)).toContainText("+₹300");
  await expect(session(page).locator("section[aria-labelledby=ss-orders]")).not.toContainText(/0 (placed|filled|pending)/i);
  await captureEvidence(page, info, "independent-order-error");
});

test("S3 Practice closed trips retain Practice provenance instead of Live", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); sessionBooks(syntheticApi, fills(), [], "practice");
  await mount(page, "session", "practice");
  await pump(page, () => session(page).getByRole("table").getByText("SYNTHETIC-CLOSED").isVisible());
  await expect(session(page)).toContainText("+₹300");
  await expect(session(page).getByText("Live", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("mode-honesty-bar")).toHaveAttribute("data-mode", "practice");
  await captureNarrow(page, info, "practice-provenance-compact");
});

test("S3 S4 restored Live trips and explicit Explore cannot reuse cached real trades", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); sessionBooks(syntheticApi, fills("SYNTHETIC-RESTORED", true));
  await mount(page, "session");
  await pump(page, () => session(page).getByRole("table").getByText("SYNTHETIC-RESTORED").isVisible());
  await expect(session(page).getByRole("table")).toContainText("Restored");
  const paths = [DISCOVERY, nativePath("funds"), nativePath("positions"), nativePath("orders"), nativePath("trades")];
  const baseline = counts(syntheticApi, paths);
  await captureEvidence(page, info, "live-restored");
  await page.getByRole("button", { name: "Select Explore", exact: true }).click();
  await page.clock.runFor(100);
  await expect(page.getByTestId("mode-honesty-bar")).toContainText(/simulat|example/i);
  await expect(session(page)).not.toContainText("SYNTHETIC-RESTORED");
  await expect(session(page).getByText("Live", { exact: true })).toHaveCount(0);
  await expect(session(page).getByRole("table").locator("tbody tr")).toHaveCount(7);
  expect(counts(syntheticApi, paths)).toEqual(baseline);
  await captureNarrow(page, info, "explore-cached-real-separation");
  const lastRow = session(page).getByRole("table").locator("tbody tr").last();
  await lastRow.scrollIntoViewIfNeeded();
  await expect(lastRow).toBeInViewport({ ratio: 1 });
  const geometry = await lastRow.evaluate((row) => {
    const cells = [...row.querySelectorAll("td")].map((cell) => {
      const box = cell.getBoundingClientRect();
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
      return { text: cell.textContent, top: box.top, bottom: box.bottom, left: box.left, right: box.right,
        fullyInViewport: box.top >= 0 && box.bottom <= innerHeight && box.left >= 0 && box.right <= innerWidth,
        centrePainted: hit !== null && cell.contains(hit) };
    });
    const ancestors = [];
    for (let element = row.parentElement; element; element = element.parentElement) {
      const css = getComputedStyle(element);
      ancestors.push({ tag: element.tagName, clientHeight: element.clientHeight, scrollHeight: element.scrollHeight,
        scrollTop: element.scrollTop, overflowY: css.overflowY, minHeight: css.minHeight, flex: css.flex });
    }
    return { cells, ancestors };
  });
  expect(geometry.cells.every((cell) => cell.fullyInViewport && cell.centrePainted)).toBe(true);
  await info.attach("explore-last-row-geometry", { body: JSON.stringify(geometry, null, 2), contentType: "application/json" });
  await captureEvidence(page, info, "explore-last-row-compact");
});

for (const outcome of ["empty", "malformed"] as const) {
  test(`S2 deferred trades resolve ${outcome} independently of a genuine empty order book`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1); aggregateBooks(syntheticApi); journal(syntheticApi);
    const trades = hold(); const orders = hold();
    book(syntheticApi, "trades", trades.handler, ACCOUNT_A, outcome === "empty" ? 1 : 3);
    book(syntheticApi, "orders", orders.handler);
    try {
      await mount(page, "session");
      await pump(page, async () => syntheticApi.callCount("GET", nativePath("trades")) === 2 && syntheticApi.callCount("GET", nativePath("orders")) === 2);
      await Promise.all([trades.started, orders.started]);
      await expect(session(page)).toContainText(/Loading trades/i);
      await expect(session(page)).toContainText(/Loading orders/i);
      await expect(session(page)).not.toContainText("+₹0");
      await expect(session(page).getByRole("table")).toHaveCount(0);
      await captureEvidence(page, info, "session-both-loading");
      orders.release(ok([]));
      await pump(page, () => session(page).getByText("Placed", { exact: true }).isVisible());
      await expect(session(page)).toContainText(/Loading trades/i);
      await expect(session(page).locator("section[aria-labelledby=ss-orders]")).toHaveText(/Orders\s*Placed\s*0\s*Filled\s*0\s*Rejected\s*0\s*Pending\s*0/);
      trades.release(ok(outcome === "empty" ? [] : null));
      if (outcome === "malformed") {
        // Tradebook retains the production two-retry policy.
        await finishTradeRetries(page);
        await pump(page, () => session(page).getByText(/Trades unavailable/i).isVisible());
        await expect(session(page)).not.toContainText("+₹0");
      } else {
        await pump(page, () => session(page).getByText("No round trips closed yet today.").isVisible());
        await expect(session(page)).toContainText("+₹0");
      }
      await captureEvidence(page, info, `session-deferred-${outcome}`);
    } finally { trades.release(ok([])); orders.release(ok([])); }
  });
}

test("S3 retired Session A fills cannot enter B after exact account selection", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi); journal(syntheticApi);
  const aTrades = hold();
  // Two held startup reads are intentionally retired, not certified completed.
  // The exact cancellation assertion below owns this negative-only allowance.
  registerRead(syntheticApi, nativePath("trades"), aTrades.handler, 2);
  book(syntheticApi, "orders", ok([]));
  book(syntheticApi, "funds", funds(0), ACCOUNT_B); book(syntheticApi, "positions", ok([]), ACCOUNT_B);
  book(syntheticApi, "trades", ok([]), ACCOUNT_B); book(syntheticApi, "orders", ok([]), ACCOUNT_B);
  try {
    await mount(page, "session");
    await pump(page, async () => syntheticApi.callCount("GET", nativePath("trades")) === 2 && syntheticApi.readCounts(nativePath("orders")).completed === 1);
    await aTrades.started;
    await choose(page, ACCOUNT_B);
    await pump(page, () => session(page).getByText("No round trips closed yet today.").isVisible());
    const paths = [DISCOVERY, ...[ACCOUNT_A, ACCOUNT_B].flatMap((account) => [nativePath("trades", account), nativePath("orders", account)])];
    const baseline = counts(syntheticApi, paths);
    const notices = await notifications(page);
    aTrades.release(ok(fills("SYNTHETIC-RETIRED-TRIP")));
    await expect.poll(() => syntheticApi.readCounts(nativePath("trades")).cancelled).toBe(2);
    await page.clock.runFor(200);
    await expect(session(page)).not.toContainText("SYNTHETIC-RETIRED-TRIP");
    await expect(session(page)).toContainText("No round trips closed yet today.");
    expect(counts(syntheticApi, paths)).toEqual(baseline);
    expect(await notifications(page)).toEqual(notices);
    await info.attach("retired-session-baseline", { body: JSON.stringify({ baseline, after: counts(syntheticApi, paths), retired: syntheticApi.readCounts(nativePath("trades")), notices, afterNotices: await notifications(page) }, null, 2), contentType: "application/json" });
    await captureNarrow(page, info, "session-retired-a-compact");
  } finally { aTrades.release(ok([])); }
});

test("A4 null native funds must not publish verified available zero", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1);
  book(syntheticApi, "funds", ok(null));
  book(syntheticApi, "positions", ok([position("SYNTHETIC-VALID-POSITION", 75)]));
  await mount(page, "aggregate");
  await pump(page, async () => syntheticApi.readCounts(nativePath("funds")).completed === 1 && (await snapshot(page))["positionsStatus"] === "ready");
  await page.clock.runFor(50);
  await info.attach("null-funds-observation", { body: JSON.stringify({ aggregate: await snapshot(page), queries: await queryObservations(page) }, null, 2), contentType: "application/json" });
  await captureEvidence(page, info, "null-funds-not-zero");
  // The first malformed body may still be retrying; neither loading nor error
  // can authorise a ready balance. Do not advance a recurring/retry window.
  expect((await snapshot(page))["fundsStatus"]).not.toBe("ready");
  expect((await snapshot(page))["positionsStatus"]).toBe("ready");
});

for (const resource of ["positions", "orders", "trades"] as const) {
  test(`A4 S2 Practice nested null ${resource} is not a verified empty book`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1);
    const view = resource === "positions" ? "aggregate" : "session";
    const payloads: Record<string, unknown> = {
      funds: { funds: { available_balance: 0, used_margin: 0, current_balance: 0 } },
      positions: { positions: resource === "positions" ? null : [] },
      orders: { orders: resource === "orders" ? null : [] },
      trades: { trades: resource === "trades" ? null : [] },
    };
    for (const kind of view === "aggregate" ? ["funds", "positions"] : ["funds", "positions", "orders", "trades"]) {
      registerRead(syntheticApi, `/ft-api/v1/sandbox/${kind}`, ok(payloads[kind]), 1, "startup");
    }
    if (view === "session") journal(syntheticApi, "practice");
    await mount(page, view, "practice", resource === "trades" ? async () => {
      // The real Log observes trades before the real Session tab mounts. With
      // null now rejected, Session retries that failed/pending Log observation.
      // Preserve each exact phase, rather than widening one startup allowance.
      const path = "/ft-api/v1/sandbox/trades";
      await pump(page, async () => syntheticApi.readCounts(path).completed === 1 && syntheticApi.readCounts(path).pending === 0);
      await syntheticApi.retireRead(path);
      registerRead(syntheticApi, path, ok(payloads["trades"]), 1, "startup");
    } : undefined);
    await pump(page, async () => syntheticApi.readCounts(`/ft-api/v1/sandbox/${resource}`).completed === (resource === "trades" ? 2 : 1));
    await page.clock.runFor(100);
    await info.attach(`null-${resource}-observation`, { body: JSON.stringify({ aggregate: await snapshot(page), queries: await queryObservations(page) }, null, 2), contentType: "application/json" });
    await captureEvidence(page, info, `practice-null-${resource}`);
    if (resource === "positions") {
      expect.soft((await snapshot(page))["positionsStatus"]).not.toBe("ready");
      await expect(page.getByTestId("welcome-card")).not.toContainText("₹0");
    } else if (resource === "orders") {
      await expect(session(page).locator("section[aria-labelledby=ss-orders]")).toContainText(/unavailable|loading/i);
    } else {
      await expect(session(page).locator("section[aria-labelledby=ss-equity]")).toContainText(/unavailable|loading/i);
      await expect(session(page)).not.toContainText("+₹0");
    }
  });
}

test.describe("S2 synthetic native refusal presentation (not native endpoint qualification)", () => {
  test.use({ benignConsoleErrors: [[{ text: "Failed to load resource: the server responded with a status of 409 (Conflict)", url: `http://localhost:5173${nativePath("trades")}`, expectedCalls: 3 }], { scope: "test" }] });
  test("frozen native trade read is unavailable rather than sample or zero", async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1); aggregateBooks(syntheticApi); journal(syntheticApi);
    book(syntheticApi, "trades", { status: 409, json: { status: "error", message: "Native broker HTTP reads are unavailable until the read cutover" } }, ACCOUNT_A, 3);
    book(syntheticApi, "orders", ok([]));
    await mount(page, "session"); await finishTradeRetries(page);
    await pump(page, () => session(page).getByText(/Trades unavailable/i).isVisible());
    await expect(session(page).getByRole("table")).toHaveCount(0);
    await expect(session(page)).not.toContainText("+₹0");
    await expect(session(page).locator("section[aria-labelledby=ss-orders]")).toHaveText(/Orders\s*Placed\s*0\s*Filled\s*0\s*Rejected\s*0\s*Pending\s*0/);
    await captureEvidence(page, info, "synthetic-frozen-read");
  });
});

// Applicability split: the strip and TerminalRoute are wired owners;
// DailyWelcome is dormant. Its assertions continue in the next case, not in
// an artificial all-three overlay. Historical combined native-paint REDs stand.
test("A5 wired-risk strip and TerminalRoute retire A risk on deferred B", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi, 1200, -3000, 100);
  riskReads(syntheticApi);
  const bFunds = hold(); const bPositions = hold();
  book(syntheticApi, "funds", bFunds.handler, ACCOUNT_B);
  book(syntheticApi, "positions", bPositions.handler, ACCOUNT_B);
  book(syntheticApi, "orders", ok([]), ACCOUNT_B);
  try {
    await mount(page, "wired-risk");
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
    // The lazy book owner can mount after the aggregate mirror is ready.
    // Complete its mandatory A read before switching scope; keep exact counts.
    await pump(page, async () => syntheticApi.readCounts(nativePath("orders")).completed === 1);
    await expect(page.getByRole("status", { name: "Daily loss alert: ₹3000; kill switch status: inactive" })).toBeVisible();
    await expect(page.getByTestId("incident-strip")).toHaveAttribute("data-banner-kind", "live_risk");
    await captureEvidence(page, info, "wired-risk-a-claims");
    await choose(page, ACCOUNT_B);
    await Promise.all([bFunds.started, bPositions.started]);
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "loading");
    for (const kind of ["funds", "positions"]) expect(syntheticApi.readCounts(nativePath(kind, ACCOUNT_B))).toMatchObject({ calls: 1, pending: 1, completed: 0 });
    await expect(page.getByRole("status", { name: "Kill switch status: inactive", exact: true })).toBeVisible();
    // Retire A's risk, not unrelated protective incidents (e.g. default Laya down).
    await expect(page.locator('[data-banner-kind="live_risk"]')).toHaveCount(0);
    await expect(page.getByRole("status", { name: "Kill switch status: inactive", exact: true })).not.toContainText(/3000|₹0/);
    await expect(page.getByRole("button", { name: /^Activate emergency kill switch/ })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Risk & Safety" })).toBeEnabled();
    await captureNarrow(page, info, "wired-risk-b-deferred-compact");
    const riskPaint = await Promise.all([
      literalPaint(page.getByTestId("incident-strip").locator("p").first()),
      literalPaint(page.getByRole("status", { name: "Kill switch status: inactive", exact: true })),
    ]);
    await info.attach("geometry.json", { body: JSON.stringify(riskPaint, null, 2), contentType: "application/json" });
    // All co-mounted safety text must paint simultaneously at exactly 800×844.
    expect.soft(riskPaint.every((surface) => surface.glyphs.length > 0 && surface.glyphs.every((glyph) => glyph.inViewport && glyph.painted))).toBe(true);
    await expect(page.getByTestId("incident-strip")).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("status", { name: "Kill switch status: inactive", exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("button", { name: /^Activate emergency kill switch/ })).toBeInViewport({ ratio: 1 });
    bFunds.release(funds(0)); bPositions.release(ok([]));
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready" && (await snapshot(page))["fundsStatus"] === "ready");
    expect(await snapshot(page)).toMatchObject({ scopeKey: `live:native:dhan:${ACCOUNT_B}`, positionCount: 0, totalPnl: 0, availableMargin: 0 });
    await expect(page.getByRole("status", { name: "Kill switch status: inactive", exact: true })).not.toContainText("3000");
    await expect(page.getByTestId("incident-strip")).toBeVisible();
    await expect(page.getByRole("button", { name: /^Activate emergency kill switch/ })).toBeEnabled();
    await captureEvidence(page, info, "wired-risk-b-genuine-empty");
  } finally { bFunds.release(funds(0)); bPositions.release(ok([])); }
});

test("A5 dormant-recovery DailyWelcome retires A count on deferred B", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi, 1200, -3000, 100); recoveryReads(syntheticApi);
  const bFunds = hold(); const bPositions = hold();
  book(syntheticApi, "funds", bFunds.handler, ACCOUNT_B);
  book(syntheticApi, "positions", bPositions.handler, ACCOUNT_B);
  try {
    await mount(page, "dormant-recovery");
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
    // Holiday acquisition owns a second discovery, not another startup read.
    await syntheticApi.retireRead(DISCOVERY);
    discovery(syntheticApi, 1, false, false, "required");
    await page.getByRole("button", { name: "Open recovery notice" }).click();
    const recovery = page.getByRole("alert").filter({ hasText: "Session recovered" });
    await pump(page, () => recovery.isVisible());
    await expect(recovery).toContainText("You have 1 open position.");
    await pump(page, async () => syntheticApi.readCounts(`${nativePath("holidays")}?year=2026`).completed === 1);
    await captureEvidence(page, info, "dormant-recovery-a-count");
    await choose(page, ACCOUNT_B);
    await Promise.all([bFunds.started, bPositions.started]);
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "loading");
    for (const kind of ["funds", "positions"]) expect(syntheticApi.readCounts(nativePath(kind, ACCOUNT_B))).toMatchObject({ calls: 1, pending: 1, completed: 0 });
    await expect(recovery).toContainText("Current-account positions are loading.");
    await expect(recovery).not.toContainText("You have 1 open position.");
    await expect(recovery.locator("p.text-sm")).toHaveText("Previous session ended unexpectedly. Current-account positions are loading. Review positions before trading.");
    const review = recovery.getByRole("button", { name: "Review positions now", exact: true });
    await expect(review).toBeEnabled();
    await captureNarrow(page, info, "dormant-recovery-b-deferred-compact");
    const recoveryPaint = await Promise.all([literalPaint(recovery.locator("p.text-sm")), literalPaint(review)]);
    await info.attach("dormant-recovery-compact-literal-paint", { body: JSON.stringify(recoveryPaint, null, 2), contentType: "application/json" });
    expect.soft(recoveryPaint.every((surface) => surface.glyphs.length > 0 && surface.glyphs.every((glyph) => glyph.inViewport && glyph.painted))).toBe(true);
    await expect(recovery).toBeInViewport({ ratio: 1 });
    await expect(review).toBeInViewport({ ratio: 1 });
    bFunds.release(funds(0)); bPositions.release(ok([]));
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready" && (await snapshot(page))["fundsStatus"] === "ready");
    expect(await snapshot(page)).toMatchObject({ scopeKey: `live:native:dhan:${ACCOUNT_B}`, positionCount: 0, totalPnl: 0, availableMargin: 0 });
    await expect(recovery).toHaveCount(0);
    await captureEvidence(page, info, "dormant-recovery-b-genuine-empty");
  } finally { bFunds.release(funds(0)); bPositions.release(ok([])); }
});

for (const condition of ["unavailable", "stale"] as const) {
  test(`A5 dormant-recovery ${condition} copy and review action remain readable`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1); recoveryReads(syntheticApi);
    book(syntheticApi, "funds", funds(1200));
    book(syntheticApi, "positions", condition === "unavailable" ? ok(null) : ok([position("SYNTHETIC-ALPHA", -3000, 100)]));
    await mount(page, "dormant-recovery");
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === (condition === "unavailable" ? "unavailable" : "ready"));
    await syntheticApi.retireRead(DISCOVERY);
    discovery(syntheticApi, 1, false, false, "required");
    await page.getByRole("button", { name: "Open recovery notice" }).click();
    const recovery = page.getByRole("alert").filter({ hasText: "Session recovered" });
    await pump(page, () => recovery.isVisible());
    await pump(page, async () => syntheticApi.readCounts(`${nativePath("holidays")}?year=2026`).completed === 1);
    const baseline = counts(syntheticApi, [DISCOVERY, nativePath("funds"), nativePath("positions"), `${nativePath("holidays")}?year=2026`]);
    if (condition === "stale") {
      await page.getByRole("button", { name: "Mark account books stale" }).click();
      await pump(page, async () => (await snapshot(page))["positionsStatus"] === "stale");
    }
    await expect(recovery.locator("p.text-sm")).toHaveText(condition === "unavailable"
      ? "Previous session ended unexpectedly. Current-account positions are unavailable. Review positions before trading."
      : "Previous session ended unexpectedly. Last known open positions: 1. Positions are stale; review the current account.");
    await expect(recovery).not.toContainText(/You have 1 open position|You have 0 open positions/);
    const review = recovery.getByRole("button", { name: "Review positions now", exact: true });
    await expect(review).toBeEnabled();
    await captureEvidence(page, info, `dormant-recovery-${condition}-desktop`);
    await captureNarrow(page, info, `dormant-recovery-${condition}-compact`);
    const recoveryPaint = await Promise.all([literalPaint(recovery.locator("p.text-sm")), literalPaint(review)]);
    await info.attach(`dormant-recovery-${condition}-literal-paint`, { body: JSON.stringify(recoveryPaint, null, 2), contentType: "application/json" });
    expect.soft(recoveryPaint.every((surface) => surface.glyphs.length > 0 && surface.glyphs.every((glyph) => glyph.inViewport && glyph.painted))).toBe(true);
    await expect(recovery).toBeInViewport({ ratio: 1 });
    await expect(review).toBeInViewport({ ratio: 1 });
    await review.click();
    await expect(page).toHaveURL("http://localhost:5173/trade");
    await expect(recovery).toHaveCount(0);
    expect(counts(syntheticApi, Object.keys(baseline))).toEqual(baseline);
  });
}

for (const independent of ["active", "daily-loss-halted"] as const) {
  test(`A5 independent ${independent} safety survives unavailable aggregates`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1);
    riskReads(syntheticApi, safety(independent === "active", independent === "daily-loss-halted"));
    await mountUnavailableRisk(page, syntheticApi);
    await expect(page.getByTestId("incident-strip")).toHaveAttribute("data-banner-kind", "live_risk");
    const control = page.getByRole("button", { name: independent === "active" ? "Retry emergency broker actions" : /^Activate emergency kill switch/ });
    await expect(control).toBeEnabled();
    if (independent === "active") await expect(page.getByRole("status", { name: "Kill switch status: active" })).toContainText("broker flattening is incomplete");
    await captureNarrow(page, info, `risk-independent-${independent}`);
  });
}

test("A5 loading and unavailable safety remain visible without aggregate truth", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); book(syntheticApi, "orders", ok([]));
  const held = hold(); registerRead(syntheticApi, SAFETY, held.handler, 3, "required");
  const refused = { json: { status: "error", message: "Synthetic safety state unavailable" } };
  try {
    await mountUnavailableRisk(page, syntheticApi); await held.started;
    await expect(page.getByRole("status", { name: "Kill switch status: loading" })).toContainText("Checking kill-switch state...");
    await expect(page.getByRole("button", { name: /^Activate emergency kill switch/ })).toBeDisabled();
    await captureEvidence(page, info, "risk-safety-loading");
    held.release(refused); await finishRetries(page, "safetyConfig");
    await pump(page, () => page.getByRole("alert", { name: "Kill switch status: unavailable" }).isVisible());
    await expect(page.getByRole("alert", { name: "Kill switch status: unavailable" })).toContainText("Authoritative kill-switch state is unavailable");
    await expect(page.getByRole("button", { name: "Risk & Safety" })).toBeEnabled();
    await captureEvidence(page, info, "risk-safety-unavailable");
  } finally { held.release(refused); }
});

test.describe("A5 isolated synthetic protective interaction", () => {
  const path = "/ft-api/api/v1/safety/kill-switch";
  const reason = "Manual kill switch — trader initiated from terminal";
  test.use({ foundationWrites: [[{ method: "POST", path, body: { reason } }], { scope: "test" }] });
  test("existing emergency control submits exact protective request with unavailable positions", async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1); riskReads(syntheticApi);
    syntheticApi.register({ name: "sole synthetic process-wide protective action", method: "POST", path, expectedCalls: 1,
      handler: (request) => {
        // This process-wide protection API has no broker selector/mode header.
        expect(request.url()).toBe(`http://localhost:5173${path}`);
        expect(request.method()).toBe("POST");
        expect(request.headers()["authorization"]).toBe(`Bearer ${LIVE_TOKEN}`);
        expect(request.headers()["x-api-key"]).toBeUndefined();
        expect(request.headers()["x-flinttrade-mode"]).toBeUndefined();
        expect(request.headers()["content-type"]).toBe("application/json");
        expect(request.postDataJSON()).toEqual({ reason });
        return ok({ message: "Synthetic routing halted", reason, is_active: true,
          emergency_actions: { policy: "synthetic-no-broker", complete: false, target_count: 0, completed_target_count: 0, summary: "No real broker action", targets: [], outcomes: [] } });
      } });
    await mountUnavailableRisk(page, syntheticApi);
    await syntheticApi.retireRead(SAFETY);
    registerRead(syntheticApi, SAFETY, safety(true), 1, "required");
    await expect(page.getByRole("button", { name: /^Activate emergency kill switch/ })).toBeEnabled();
    await page.getByRole("button", { name: /^Activate emergency kill switch/ }).click();
    await pump(page, () => page.getByRole("button", { name: "Retry emergency broker actions" }).isVisible());
    await expect(page.getByRole("button", { name: "Retry emergency broker actions" })).toBeEnabled();
    await pump(page, async () => syntheticApi.readCounts(SAFETY).completed === 2);
    await expect(page.getByRole("status", { name: "Kill switch status: active" })).toContainText("broker flattening is incomplete");
    await expect(page.getByTestId("incident-strip")).toHaveAttribute("data-banner-kind", "live_risk");
    const notices = await notifications(page);
    expect(notices).toEqual([expect.objectContaining({ title: "Kill switch ACTIVATED", body: expect.stringContaining("did not complete") })]);
    await captureEvidence(page, info, "synthetic-protection-incomplete-not-flat");
  });
});

test("A3 same-page Live Practice Live keeps exact aggregate scopes", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi);
  const paperFunds = hold(); const paperPositions = hold();
  registerRead(syntheticApi, "/ft-api/v1/sandbox/funds", paperFunds.handler, 1, "required");
  registerRead(syntheticApi, "/ft-api/v1/sandbox/positions", paperPositions.handler, 1, "required");
  try {
    await mount(page, "aggregate"); await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
    await page.getByRole("button", { name: "Select Practice", exact: true }).click();
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "loading");
    await Promise.all([paperFunds.started, paperPositions.started]);
    await expect(page.getByTestId("welcome-card")).not.toContainText("₹75");
    paperFunds.release(ok({ funds: { available_balance: 300, used_margin: 0, current_balance: 300 } }));
    paperPositions.release(ok({ positions: [position("SYNTHETIC-PAPER", -45)] }));
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
    await expect(page.getByTestId("welcome-card")).toContainText("-₹45");
    await captureEvidence(page, info, "cycle-practice");
    await page.getByRole("button", { name: "Select Live", exact: true }).click();
    await pump(page, async () => (await snapshot(page))["scopeKey"] === `live:native:dhan:${ACCOUNT_A}`);
    await expect(page.getByTestId("welcome-card")).toContainText("+₹75");
    await expect(page.getByTestId("positions-card")).not.toContainText("SYNTHETIC-PAPER");
    expect(syntheticApi.readCounts(nativePath("positions"))).toMatchObject({ completed: 1, pending: 0, failed: 0 });
    await captureEvidence(page, info, "cycle-live-return");
  } finally { paperFunds.release(ok({ funds: {} })); paperPositions.release(ok({ positions: [] })); }
});

test("A3 sessionEnabled false retires mirror without displaying zero", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi);
  await mount(page, "aggregate"); await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
  const baseline = counts(syntheticApi, [DISCOVERY, nativePath("funds"), nativePath("positions")]);
  await page.getByRole("button", { name: "Disable aggregate session" }).click();
  await pump(page, async () => (await snapshot(page))["scopeKey"] === null);
  expect(await snapshot(page)).toMatchObject({ fundsStatus: "unavailable", positionsStatus: "unavailable" });
  await expect(page.getByTestId("welcome-card")).toContainText("Positions unavailable");
  await expect(page.getByTestId("welcome-card")).not.toContainText(/₹75|₹0/);
  expect(counts(syntheticApi, Object.keys(baseline))).toEqual(baseline);
  await captureEvidence(page, info, "aggregate-session-disabled");
});

for (const retirement of ["Lock", "Log out"] as const) {
  test(`A3 S3 ${retirement} auth retires cached truth and deferred account reads`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1); sessionBooks(syntheticApi, fills("SYNTHETIC-AUTH-OLD"));
    const held = hold();
    const paths = ["funds", "positions", "trades", "orders"].map((kind) => nativePath(kind));
    try {
      await mount(page, "session");
      await pump(page, () => session(page).getByRole("table").getByText("SYNTHETIC-AUTH-OLD").isVisible());
      await pump(page, async () => paths.every((path) => syntheticApi.readCounts(path).completed === 1));
      const previous = Object.fromEntries(await Promise.all(paths.map(async (path) => [path, await syntheticApi.retireRead(path)])));
      for (const path of paths) registerRead(syntheticApi, path, held.handler, 1);
      await page.getByRole("button", { name: "Refresh account books" }).click();
      await pump(page, async () => paths.every((path) => syntheticApi.readCounts(path).pending === 1)); await held.started;
      await page.getByRole("button", { name: `${retirement} synthetic session` }).click();
      await pump(page, () => page.getByText("Awaiting synthetic authentication").isVisible());
      const baseline = await snapshot(page); const notices = await notifications(page);
      expect(baseline).toMatchObject({ scopeKey: null, positionsStatus: "unavailable", fundsStatus: "unavailable" });
      held.release({ json: { status: "error", message: "Synthetic retired authentication read" } });
      await expect.poll(() => paths.every((path) => syntheticApi.readCounts(path).pending === 0)).toBe(true);
      for (const path of paths) expect(syntheticApi.readCounts(path).cancelled).toBe(previous[path].cancelled + 1);
      await page.clock.runFor(200);
      expect(await snapshot(page)).toEqual(baseline); expect(await notifications(page)).toEqual(notices);
      expect((await queryObservations(page)).filter((query) => query.data !== undefined)).toEqual([]);
      await expect(page.getByRole("table")).toHaveCount(0);
      await expect(page.locator("body")).not.toContainText("SYNTHETIC-AUTH-OLD");
      await captureEvidence(page, info, `auth-${retirement.replace(" ", "-")}-retired`);
    } finally { held.release(ok([])); }
  });
}

for (const view of ["aggregate", "session"] as const) {
  test(`A4 S3 ${view} same-scope failed refresh retains labelled stale data`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1);
    if (view === "session") sessionBooks(syntheticApi, fills("SYNTHETIC-STALE")); else aggregateBooks(syntheticApi);
    await mount(page, view);
    const kinds = view === "session" ? ["funds", "positions", "trades", "orders"] : ["funds", "positions"];
    await pump(page, async () => kinds.every((kind) => syntheticApi.readCounts(nativePath(kind)).completed === 1));
    for (const kind of kinds) {
      await syntheticApi.retireRead(nativePath(kind));
      const fails = view === "aggregate" || kind === "trades" || kind === "orders";
      registerRead(syntheticApi, nativePath(kind), fails ? { json: { status: "error", message: "Synthetic refresh unavailable" } } : kind === "funds" ? funds(1200) : ok([position("SYNTHETIC-ALPHA", 75)]), fails && (kind === "trades" || kind === "funds") ? 3 : 1, "required");
    }
    await page.getByRole("button", { name: "Refresh account books" }).click();
    await finishRetries(page, view === "session" ? "tradebook" : "funds");
    if (view === "aggregate") {
      expect(await snapshot(page)).toMatchObject({ fundsStatus: "stale", positionsStatus: "stale", availableMargin: 1200, totalPnl: 75 });
      await expect(page.getByTestId("welcome-card")).toContainText("Positions stale — last known P&L");
      await expect(page.getByTestId("welcome-card")).toContainText("+₹75");
    } else {
      await expect(session(page)).toContainText("Trades stale — showing the last available fills.");
      await expect(session(page)).toContainText("Orders stale — showing the last available order book.");
      await expect(session(page).getByRole("table")).toContainText("SYNTHETIC-STALE");
    }
    await captureEvidence(page, info, `${view}-failed-refresh-stale`);
  });

  test(`A4 S2 ${view} browser offline pauses refresh and foreign B is unavailable`, async ({ page, context, syntheticApi }, info) => {
    discovery(syntheticApi, 1);
    if (view === "session") sessionBooks(syntheticApi, fills("SYNTHETIC-OFFLINE")); else aggregateBooks(syntheticApi);
    await mount(page, view);
    const keys = view === "session" ? ["funds", "positions", "tradebook", "orders"] : ["funds", "positions"];
    await pump(page, async () => {
      const queries = await queryObservations(page);
      return keys.every((key) => queries.some((query) => query.queryKey[0] === key && query.status === "success" && query.fetchStatus === "idle"));
    });
    await info.attach("network-before-offline-command", { body: JSON.stringify(await browserNetwork(page)), contentType: "application/json" });
    await context.setOffline(true);
    await page.clock.runFor(50);
    await info.attach("offline-before-refresh", { body: JSON.stringify(await browserNetwork(page)), contentType: "application/json" });
    await deliverOfflineEvent(page);
    await expect.poll(() => browserNetwork(page)).toEqual({ navigatorOnline: false, queryOnline: false });
    await page.getByRole("button", { name: "Refresh account books" }).click();
    await pump(page, async () => {
      const queries = await queryObservations(page);
      return keys.every((key) => queries.some((query) => query.queryKey[0] === key && query.fetchStatus === "paused"));
    });
    if (view === "aggregate") {
      await expect(page.getByTestId("welcome-card")).toContainText("Positions stale");
      await expect(page.getByTestId("welcome-card")).toContainText("+₹75");
    } else {
      await expect(session(page)).toContainText("Trades stale");
      await expect(session(page)).toContainText("Orders stale");
      await expect(session(page).getByRole("table")).toContainText("SYNTHETIC-OFFLINE");
    }
    await captureEvidence(page, info, `${view}-offline-retained-stale`);
    await choose(page, ACCOUNT_B);
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "unavailable");
    if (view === "aggregate") {
      await expect(page.getByTestId("welcome-card")).not.toContainText(/₹75|₹0/);
    } else {
      await expect(session(page)).toContainText("Trades unavailable.");
      await expect(session(page)).toContainText("Orders unavailable.");
      await expect(session(page)).not.toContainText(/SYNTHETIC-OFFLINE|₹0/);
      await expect(session(page).getByRole("table")).toHaveCount(0);
    }
    await captureEvidence(page, info, `${view}-offline-foreign-unavailable`);
  });
}

for (const initial of [true, false]) {
  test(`S2 ${initial ? "initial disabled" : "disconnected B"} Session never manufactures empty success`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, 1, true, initial);
    if (initial) journal(syntheticApi); else sessionBooks(syntheticApi, fills("SYNTHETIC-DISCONNECT"));
    await mount(page, "session");
    if (!initial) {
      await pump(page, () => session(page).getByRole("table").getByText("SYNTHETIC-DISCONNECT").isVisible());
      await choose(page, ACCOUNT_B);
    }
    await expect(session(page)).toContainText("Trades unavailable.");
    await expect(session(page)).toContainText("Orders unavailable.");
    await expect(session(page)).not.toContainText(/SYNTHETIC-DISCONNECT|₹0|RELIANCE|BANKNIFTY/);
    await expect(session(page).getByRole("table")).toHaveCount(0);
    await captureEvidence(page, info, initial ? "session-disabled-initial" : "session-disconnected-b");
  });
}

test("S2 unsupported trade response remains unavailable with independent empty orders", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi); journal(syntheticApi);
  book(syntheticApi, "trades", { json: { status: "error", code: "UNSUPPORTED_CAPABILITY", message: "Synthetic broker does not support trades" } }, ACCOUNT_A, 3);
  book(syntheticApi, "orders", ok([]));
  await mount(page, "session"); await finishTradeRetries(page);
  await pump(page, () => session(page).getByText("Trades unavailable.").isVisible());
  await expect(session(page)).toContainText("Trades unavailable.");
  await expect(session(page)).not.toContainText("+₹0");
  await expect(session(page).locator("section[aria-labelledby=ss-orders]")).toHaveText(/Orders\s*Placed\s*0\s*Filled\s*0\s*Rejected\s*0\s*Pending\s*0/);
  await captureEvidence(page, info, "session-unsupported-trades");
});

test("S3 retired Session A rejection cannot disturb B completed trips", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi); journal(syntheticApi);
  const held = hold(); registerRead(syntheticApi, nativePath("trades"), held.handler, 2); book(syntheticApi, "orders", ok([]));
  book(syntheticApi, "funds", funds(0), ACCOUNT_B); book(syntheticApi, "positions", ok([]), ACCOUNT_B);
  book(syntheticApi, "orders", ok([]), ACCOUNT_B); book(syntheticApi, "trades", ok(fills("SYNTHETIC-B-KEPT")), ACCOUNT_B);
  try {
    await mount(page, "session");
    await pump(page, async () => syntheticApi.callCount("GET", nativePath("trades")) === 2); await held.started;
    await choose(page, ACCOUNT_B);
    await pump(page, () => session(page).getByRole("table").getByText("SYNTHETIC-B-KEPT").isVisible());
    const paths = [DISCOVERY, ...[ACCOUNT_A, ACCOUNT_B].flatMap((account) => ["funds", "positions", "orders", "trades"].map((kind) => nativePath(kind, account)))];
    const baseline = counts(syntheticApi, paths); const notices = await notifications(page);
    held.release({ json: { status: "error", message: "Synthetic retired Session A failure" } });
    await expect.poll(() => syntheticApi.readCounts(nativePath("trades")).cancelled).toBe(2);
    await page.clock.runFor(200);
    await expect(session(page).getByRole("table")).toContainText("SYNTHETIC-B-KEPT");
    await expect(session(page)).not.toContainText("Trades unavailable");
    expect(counts(syntheticApi, paths)).toEqual(baseline); expect(await notifications(page)).toEqual(notices);
    await captureEvidence(page, info, "session-retired-a-rejection");
  } finally { held.release(ok([])); }
});

test("A3 returning to cached A labels retained values stale while exact refresh is held", async ({ page, syntheticApi }, info) => {
  discovery(syntheticApi, 1); aggregateBooks(syntheticApi);
  book(syntheticApi, "funds", funds(2300), ACCOUNT_B); book(syntheticApi, "positions", ok([position("SYNTHETIC-BETA", -25)]), ACCOUNT_B);
  const aFunds = hold(); const aPositions = hold();
  try {
    await mount(page, "aggregate"); await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
    await choose(page, ACCOUNT_B); await pump(page, async () => (await snapshot(page))["totalPnl"] === -25);
    await syntheticApi.retireRead(nativePath("funds")); await syntheticApi.retireRead(nativePath("positions"));
    registerRead(syntheticApi, nativePath("funds"), aFunds.handler, 1, "required");
    registerRead(syntheticApi, nativePath("positions"), aPositions.handler, 1, "required");
    await page.getByRole("button", { name: "Mark account books stale" }).click();
    await choose(page, ACCOUNT_A); await Promise.all([aFunds.started, aPositions.started]);
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "stale");
    await expect(page.getByTestId("welcome-card")).toContainText("+₹75");
    await expect(page.getByTestId("welcome-card")).toContainText("Positions stale");
    await expect(page.getByTestId("positions-card")).not.toContainText("SYNTHETIC-BETA");
    await captureEvidence(page, info, "cached-a-return-stale");
    aFunds.release(funds(0)); aPositions.release(ok([]));
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "ready");
    await expect(page.getByTestId("welcome-card")).toContainText("₹0");
  } finally { aFunds.release(funds(0)); aPositions.release(ok([])); }
});

for (const empty of [true, false]) {
  test(`A4 idle ${empty ? "empty" : "nonempty"} aggregate goes stale immediately on browser offline event`, async ({ page, context, syntheticApi }, info) => {
    discovery(syntheticApi, 1); aggregateBooks(syntheticApi, empty ? 0 : 1200, empty ? 0 : 75);
    await mount(page, "aggregate");
    await pump(page, async () => (await snapshot(page))["fundsStatus"] === "ready" && (await snapshot(page))["positionsStatus"] === "ready");
    await context.setOffline(true); await deliverOfflineEvent(page);
    await captureEvidence(page, info, `idle-offline-${empty ? "empty" : "nonempty"}`);
    // Keep this RED if offline presentation still uses fresh-but-now-offline
    // evidence. No refresh/invalidator is allowed to manufacture the stale state.
    expect.soft(await snapshot(page)).toMatchObject({ fundsStatus: "stale", positionsStatus: "stale" });
    await expect(page.getByTestId("welcome-card")).toContainText("Positions stale");
  });
}

for (const condition of ["aged", "invalidated"] as const) {
  test(`S3 ${condition} idle Session cache is visibly stale without a failed fetch`, async ({ page, syntheticApi }, info) => {
    discovery(syntheticApi, condition === "aged" ? 2 : 1); sessionBooks(syntheticApi, fills("SYNTHETIC-IDLE"));
    await mount(page, "session");
    await pump(page, () => session(page).getByRole("table").getByText("SYNTHETIC-IDLE").isVisible());
    if (condition === "aged") {
      // Existing trades staleTime=15s, refetch=30s; one separately declared
      // discovery poll at 10s. No account-book recurring poll is crossed.
      await page.clock.runFor(15001);
    } else {
      await page.getByRole("button", { name: "Mark account books stale" }).click();
      await page.clock.runFor(100);
    }
    await info.attach("idle-cache-observation", { body: JSON.stringify(await queryObservations(page), null, 2), contentType: "application/json" });
    await captureEvidence(page, info, `session-idle-${condition}`);
    await expect(session(page)).toContainText("Trades stale — showing the last available fills.");
    await expect(session(page)).toContainText("Orders stale — showing the last available order book.");
    await expect(session(page).getByRole("table")).toContainText("SYNTHETIC-IDLE");
  });
}
