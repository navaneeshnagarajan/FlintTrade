import { LIVE_TOKEN, assertRequest, captureEvidence, deferredResponse, expect, notifications, test, tickUntil } from "./order-flow-fixtures";
import { accountSnapshot, selectIndstocksScope } from "./indstocks-disclosure-fixtures";
import { ERROR_A, ERROR_B, ERROR_BODY, ERROR_SCOPE, ERROR_WRITE, assertPainted, errorPad, errorPath, errorRaw, mountErrorPad, registerErrorReads } from "./operator-error-fixtures";
import { UNICODE_ERROR_CASES, UNICODE_ERROR_MARKS, CAPTURED_ORIGIN_CASES, assertCapturedTextPainted, measureCapturedTextPainted, observeCapturedOriginReads, awaitCapturedOriginStartup, registerCapturedOriginReads, selectCapturedOrigin } from "./operator-error-fixtures";

for (const control of ["fractional fit", "horizontal glyph crop", "vertical glyph crop"] as const) test(`Native title geometry control / ${control}`, async ({ page }, info) => {
  // Standalone geometry seam only: never alter a production heading to pass.
  await page.setContent('<div style="position:absolute;left:100.25px;top:100.25px;border:1px solid;padding:2.25px;overflow:hidden;width:max-content"><span style="display:block;width:max-content;overflow:hidden;white-space:nowrap;font:13px/24px monospace;letter-spacing:-0.01px">Order outcome unknown: BUY INFY</span></div>');
  const title = page.locator("span");
  const before = await title.evaluate(node => {
    const range = document.createRange(); range.selectNodeContents(node);
    const b = node.getBoundingClientRect(); const r = range.getBoundingClientRect();
    return { right: b.right, rangeRight: r.right, width: b.width, clientWidth: node.clientWidth };
  });
  expect(before.rangeRight).toBe(before.right);
  expect(before.width).not.toBe(before.clientWidth);
  if (control === "horizontal glyph crop") await title.evaluate(node => { (node as HTMLElement).style.width = `${node.getBoundingClientRect().width - 0.125}px`; });
  if (control === "vertical glyph crop") await title.evaluate(node => { (node as HTMLElement).style.lineHeight = "12px"; });
  const measured = await measureCapturedTextPainted(title);
  await info.attach("native-title-control", { body: JSON.stringify({ control, before, measured }, null, 2), contentType: "application/json" });
  await expect(title).toBeInViewport({ ratio: 1 }); expect(measured.geometry.painted).toBe(true);
  expect(measured.literal.boxes.every(box => box.painted)).toBe(true);
  expect(measured.literal.inside).toBe(control === "fractional fit");
});

test("Native title geometry control / physical scrollbar viewport", async ({ page }, info) => {
  await page.setContent('<div style="position:absolute;left:100.25px;top:100.25px;border:1px solid;padding:2.25px;overflow:scroll;scrollbar-gutter:stable;width:max-content;height:40.375px"><span style="display:block;width:max-content;overflow:hidden;white-space:nowrap;font:13px/24px monospace;letter-spacing:-0.01px">Order outcome unknown: BUY INFY</span></div>');
  const title = page.locator("span");
  const width = await title.evaluate(node => node.getBoundingClientRect().width);
  await page.locator("div").evaluate((node, width) => { (node as HTMLElement).style.width = `${width}px`; }, width);
  const cropped = await measureCapturedTextPainted(title);
  expect(cropped.literal.clips.find(clip => clip.tag === "DIV")?.scrollbarWidth).toBeGreaterThan(0);
  expect(cropped.geometry.painted).toBe(true); await expect(title).toBeInViewport({ ratio: 1 });
  expect(cropped.literal.inside).toBe(false);
  await page.locator("div").evaluate((node, width) => { (node as HTMLElement).style.width = `${width + 32}px`; }, width);
  const complete = await measureCapturedTextPainted(title);
  expect(complete.literal.clips.find(clip => clip.tag === "DIV")?.scrollbarWidth).toBeGreaterThan(0);
  expect(complete.geometry.painted).toBe(true); await expect(title).toBeInViewport({ ratio: 1 });
  expect(complete.literal.inside).toBe(true);
  await info.attach("native-title-scrollbar-control", { body: JSON.stringify({ cropped, complete }, null, 2), contentType: "application/json" });
});

const unknownCopy = "Order outcome unknown. An order may still execute. Check broker positions and orders. Do not retry automatically.";
const refusedCopy = "Order refused before dispatch. No order was sent. No automatic retry.";
const fixtures: Array<{ name: string; status: number; raw?: unknown; body?: string; refused?: boolean; native?: boolean }> = [
  { name: "literal native reason is an observation, not a completed fill", status: 500, raw: errorRaw(), native: true },
  { name: "matching completed pre-dispatch refusal retains bounded native reason and code", status: 400, raw: { ...errorRaw("refused_before_dispatch"), message: "Unsupported protection intent", broker_message: "Protection is unavailable", broker_code: "UNSUPPORTED" }, refused: true, native: true },
  { name: "missing body on failed response remains unknown", status: 500, body: "upstream connection closed" },
  { name: "unstructured optimistic 5xx cannot become Not placed or Retry", status: 500, raw: { status: "error", message: "Not placed. Try again.", code: "gtt_unsupported" } },
  { name: "contradictory retry-safe true and unsupported code remain unknown", status: 400, raw: { ...errorRaw("refused_before_dispatch"), retry_safe: true, code: "gtt_unsupported", message: "Not placed" } },
  { name: "mismatched affected account cannot retarget origin", status: 400, raw: { ...errorRaw("refused_before_dispatch"), affected_item: { ...errorRaw().affected_item, account_id: ERROR_B } } },
  { name: "hostile oversized fields and raw response remain absent", status: 500, raw: { ...errorRaw(), broker_code: "SECRET".repeat(20), broker_message: "SECRET".repeat(100), raw_response: { token: "RAW_SECRET" }, exception: "EXCEPTION_SECRET" } },
  { name: "native 64 and 256 field limits remain literal in a narrow panel", status: 500, raw: { ...errorRaw(), broker_code: "C".repeat(64), broker_message: "R".repeat(256) }, native: true },
];
for (const fixture of fixtures) test.describe(fixture.name, () => {
  const label = fixture.status === 500 ? "500 (Internal Server Error)" : "400 (Bad Request)";
  test.use({ benignConsoleErrors: [{ text: `Failed to load resource: the server responded with a status of ${label}`, url: `http://localhost:5173${ERROR_WRITE}`, expectedCalls: 1 }] });
  test("real pad, persistent central notification, literal body and exactly one request", async ({ page, syntheticApi, presentationEvidence }, info) => {
    registerErrorReads(syntheticApi);
    syntheticApi.register({ name: fixture.name, method: "POST", path: ERROR_WRITE, expectedCalls: 1, handler: (request) => {
      assertRequest(request, "POST", ERROR_WRITE); expect(request.postDataJSON()).toEqual(ERROR_BODY);
      return fixture.body !== undefined ? { status: fixture.status, contentType: "text/plain", body: fixture.body } : { status: fixture.status, json: fixture.raw };
    } });
    await mountErrorPad(page, "live", fixture.name.includes("narrow"));
    await expect.poll(() => accountSnapshot(page)).toMatchObject({ scopeKey: ERROR_SCOPE, readsEnabled: true, writeTarget: { broker: "kotakneo", accountId: ERROR_A } });
    const paths = [errorPath("orders"), errorPath("positions")];
    const reads = paths.map((path) => syntheticApi.callCount("GET", path));
    const arrived = page.waitForResponse((response) => response.url().endsWith(ERROR_WRITE));
    await errorPad(page).getByRole("button", { name: "Place BUY Order", exact: true }).click();
    const response = await arrived; await response.finished();
    if (fixture.body === undefined) expect(await response.json()).toEqual(fixture.raw); else expect(await response.text()).toBe(fixture.body);
    const alert = errorPad(page).getByRole("alert"); await tickUntil(page, alert);
    const copy = fixture.refused ? refusedCopy : unknownCopy; await expect(alert).toContainText(copy);
    await expect(alert).toContainText("Origin: kotakneo / KOTAK-OFFLINE · BUY INFY (NSE / MIS).");
    await expect(errorPad(page).getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);
    await expect(alert).not.toContainText(/Order filled|Position closed|Try again|SECRET|EXCEPTION_SECRET/);
    if (!fixture.refused) await expect(alert).not.toContainText(/Not placed|No order was sent/);
    if (fixture.native) {
      const raw = fixture.raw as { broker_message: string; broker_code: string };
      await expect(alert).toContainText(`Broker reason (observation): ${raw.broker_message}.`); await expect(alert).toContainText(`Broker code: ${raw.broker_code}.`);
    } else await expect(alert).not.toContainText(/Broker reason|Broker code/);
    await assertPainted(alert, info, "pad-error"); await captureEvidence(page, info, "normal-pad-error-visible");
    const events = await notifications(page); expect(events).toEqual([expect.objectContaining({ accountScopeKey: ERROR_SCOPE, skipAccountRefresh: true, title: fixture.refused ? "Order refused: BUY INFY" : "Order outcome unknown: BUY INFY", body: await alert.innerText() })]);
    await page.getByRole("button", { name: /^Notifications —/ }).click(); await page.clock.runFor(700);
    const centre = page.getByRole("dialog", { name: "Notification Centre" }); await expect(centre).toBeVisible();
    const article = centre.getByRole("article").filter({ hasText: copy }); await expect(article).toHaveCount(1); await expect(article).toContainText(await alert.innerText());
    await assertPainted(article, info, "central-error"); await captureEvidence(page, info, "normal-central-error-visible");
    await expect(centre.getByText("Back to terminal", { exact: true })).toHaveCount(0);
    expect(paths.map((path) => syntheticApi.callCount("GET", path))).toEqual(reads);
    presentationEvidence.assertWrites([{ method: "POST", path: ERROR_WRITE, body: ERROR_BODY }]);
  });
});

for (const next of ["account-B", "Practice"] as const) for (const outcome of ["unknown_after_dispatch", "refused_before_dispatch"] as const) test.describe(`late ${outcome} to ${next}`, () => {
  test.use({ benignConsoleErrors: [{ text: "Failed to load resource: the server responded with a status of 500 (Internal Server Error)", url: `http://localhost:5173${ERROR_WRITE}`, expectedCalls: 1 }] });
  test("original account notice cannot mutate B/paper books, receipt, dialog or authority", async ({ page, syntheticApi, presentationEvidence }, info) => {
    registerErrorReads(syntheticApi, "live", true); const late = deferredResponse(); const raw = errorRaw(outcome);
    syntheticApi.register({ name: "deferred A error", method: "POST", path: ERROR_WRITE, expectedCalls: 1, handler: (request) => { assertRequest(request, "POST", ERROR_WRITE); expect(request.postDataJSON()).toEqual(ERROR_BODY); return late.promise; } });
    try {
      await mountErrorPad(page); await errorPad(page).getByRole("button", { name: "Place BUY Order", exact: true }).click();
      await expect.poll(() => syntheticApi.callCount("POST", ERROR_WRITE)).toBe(1);
      await selectIndstocksScope(page, `native:kotakneo:${ERROR_B}`, next === "Practice" ? "practice" : undefined);
      const targetPaths = next === "Practice" ? ["/ft-api/v1/sandbox/orders", "/ft-api/v1/sandbox/positions"] : [errorPath("orders", ERROR_B), errorPath("positions", ERROR_B)];
      for (const path of targetPaths) await expect.poll(() => syntheticApi.callCount("GET", path)).toBeGreaterThanOrEqual(1);
      const dialog = page.getByRole("dialog", { name: "Square off position?" });
      if (next === "account-B") {
        const squareOff = page.getByRole("tabpanel", { name: "Positions", exact: true }).first().getByRole("button", { name: "Square off INFY", exact: true }); await tickUntil(page, squareOff); await squareOff.click(); await expect(dialog).toBeVisible();
      }
      await page.clock.runFor(100);
      const beforeScope = await accountSnapshot(page); const beforeEvents = await notifications(page);
      const paths = [...new Set([errorPath("orders"), errorPath("positions"), errorPath("orders", ERROR_B), errorPath("positions", ERROR_B), ...targetPaths])];
      const reads = paths.map((path) => ({ path, count: syntheticApi.callCount("GET", path) }));
      await info.attach("before-late-origin", { body: JSON.stringify({ scope: beforeScope, events: beforeEvents, reads }, null, 2), contentType: "application/json" });
      const arrived = page.waitForResponse((response) => response.url().endsWith(ERROR_WRITE)); late.release({ status: 500, json: raw }); const response = await arrived; await response.finished(); expect(await response.json()).toEqual(raw); await page.clock.runFor(100);
      await expect.poll(() => notifications(page)).toEqual([...beforeEvents, expect.objectContaining({ accountScopeKey: ERROR_SCOPE, skipAccountRefresh: true, title: outcome === "unknown_after_dispatch" ? "Order outcome unknown: BUY INFY" : "Order refused: BUY INFY", body: expect.stringContaining("Origin: kotakneo / KOTAK-OFFLINE · BUY INFY") })]);
      expect(await accountSnapshot(page)).toEqual(beforeScope); for (const read of reads) expect(syntheticApi.callCount("GET", read.path)).toBe(read.count);
      await expect(errorPad(page).getByRole("alert", { includeHidden: true })).toHaveCount(0);
      if (next === "account-B") { await expect(dialog).toBeVisible(); await expect(dialog.getByRole("button", { name: "Confirm square off INFY", exact: true })).toBeEnabled(); }
      else await expect(errorPad(page).getByRole("button", { name: "Practice Buy", exact: true })).toBeEnabled();
      presentationEvidence.assertWrites([{ method: "POST", path: ERROR_WRITE, body: ERROR_BODY }]); await captureEvidence(page, info, `late-${outcome}-${next}-unchanged`);
    } finally { late.release({ status: 500, json: raw }); }
  });
});

test("operator-error repair leaves the real Practice review and sandbox positive path intact", async ({ page, syntheticApi, presentationEvidence }, info) => {
  registerErrorReads(syntheticApi, "practice"); const { broker: _broker, account_id: _account, ...body } = ERROR_BODY;
  syntheticApi.register({ name: "positive paper order", method: "POST", path: "/ft-api/api/v1/orders/place", expectedCalls: 1, handler: (request) => {
    expect(request.method()).toBe("POST"); expect(request.url()).toBe("http://localhost:5173/ft-api/api/v1/orders/place"); expect(request.headers()["authorization"]).toBe(`Bearer ${LIVE_TOKEN}`); expect(request.headers()["x-flinttrade-mode"]).toBe("practice"); expect(request.headers()["content-type"]).toBe("application/json"); expect(request.headers()["x-api-key"]).toBeUndefined(); expect(request.postDataJSON()).toEqual(body);
    return { json: { status: "success", data: { order_id: "SYNTHETIC-PAPER" } } };
  } });
  await mountErrorPad(page, "practice"); await errorPad(page).getByRole("button", { name: "Practice Buy", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Review Practice order" }); await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm simulated Practice order", exact: true }).click(); await tickUntil(page, errorPad(page).getByRole("alert"));
  await expect(errorPad(page).getByRole("alert")).not.toContainText(/Order outcome unknown|Broker reason/); await captureEvidence(page, info, "practice-positive-not-native");
  presentationEvidence.assertWrites([{ method: "POST", path: "/ft-api/api/v1/orders/place", body }]); expect(syntheticApi.callCount("POST", ERROR_WRITE)).toBe(0);
});

for (const viewport of [
  { name: "compact 1280x720", width: 1280, height: 720 },
  { name: "wide 1600x900", width: 1600, height: 900 },
]) for (const fixture of UNICODE_ERROR_CASES) test.describe(`Unicode error ${fixture.name} / ${viewport.name}`, () => {
  const label = fixture.status === 500 ? "500 (Internal Server Error)" : "400 (Bad Request)";
  test.use({ viewport: { width: viewport.width, height: viewport.height }, benignConsoleErrors: [{ text: `Failed to load resource: the server responded with a status of ${label}`, url: `http://localhost:5173${ERROR_WRITE}`, expectedCalls: 1 }] });
  test("literal sanitised warning is painted and persisted without changing authority or books", async ({ page, syntheticApi, presentationEvidence }, info) => {
    registerErrorReads(syntheticApi);
    syntheticApi.register({ name: fixture.name, method: "POST", path: ERROR_WRITE, expectedCalls: 1, handler: (request) => {
      assertRequest(request, "POST", ERROR_WRITE); expect(request.postDataJSON()).toEqual(ERROR_BODY);
      return { status: fixture.status, json: fixture.raw };
    } });
    await mountErrorPad(page, "live", true);
    await expect.poll(() => accountSnapshot(page)).toMatchObject({ scopeKey: ERROR_SCOPE, readsEnabled: true, writeTarget: { broker: "kotakneo", accountId: ERROR_A } });
    await page.clock.runFor(100);
    const beforeScope = await accountSnapshot(page);
    const beforeStored = JSON.parse(await page.evaluate(() => localStorage.getItem("flinttrade:notifications")) ?? "[]") as unknown[];
    expect(Array.isArray(beforeStored)).toBe(true);
    const paths = [errorPath("orders"), errorPath("positions"), errorPath("orders", ERROR_B), errorPath("positions", ERROR_B), "/ft-api/v1/sandbox/orders", "/ft-api/v1/sandbox/positions"];
    const reads = paths.map((path) => ({ path, count: syntheticApi.callCount("GET", path) }));
    await info.attach("unicode-before-submit", { body: JSON.stringify({ scope: beforeScope, reads, viewport }, null, 2), contentType: "application/json" });
    const arrived = page.waitForResponse((response) => response.url().endsWith(ERROR_WRITE));
    await errorPad(page).getByRole("button", { name: "Place BUY Order", exact: true }).click();
    const response = await arrived; await response.finished(); expect(response.status()).toBe(fixture.status); expect(await response.json()).toEqual(fixture.raw);
    const alert = errorPad(page).getByRole("alert"); await tickUntil(page, alert);
    await expect(alert).toHaveText(fixture.expected); await expect(alert).toContainText("Broker code: 1021.");
    await expect(alert).not.toContainText(/Order filled|Position closed|Order placed|Try again|Position flat|ACK/);
    await expect(errorPad(page).getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);
    if (!fixture.refused) await expect(alert).not.toContainText(/Not placed|No order was sent/);
    for (const { mark } of UNICODE_ERROR_MARKS) expect(await alert.innerText()).not.toContain(mark);
    await assertPainted(alert, info, "unicode-pad-error"); await captureEvidence(page, info, "unicode-pad-error-visible");
    const title = fixture.refused ? "Order refused: BUY INFY" : "Order outcome unknown: BUY INFY";
    expect(await notifications(page)).toEqual([expect.objectContaining({ accountScopeKey: ERROR_SCOPE, skipAccountRefresh: true, title, body: fixture.expected })]);
    await page.getByRole("button", { name: /^Notifications —/ }).click(); await page.clock.runFor(700);
    const centre = page.getByRole("dialog", { name: "Notification Centre" }); await expect(centre).toBeVisible();
    const article = centre.getByRole("article").filter({ hasText: fixture.expected }); await expect(article).toHaveCount(1);
    await expect(article).toContainText(fixture.expected); await expect(article).toContainText("Broker code: 1021.");
    await expect(centre.getByText("Back to terminal", { exact: true })).toHaveCount(0);
    await assertPainted(article, info, "unicode-central-error"); await captureEvidence(page, info, "unicode-central-error-visible");
    const stored = await page.evaluate(() => localStorage.getItem("flinttrade:notifications"));
    expect(stored).not.toBeNull();
    expect(JSON.parse(stored!) as unknown).toEqual([expect.objectContaining({ category: "order", title, body: fixture.expected }), ...beforeStored]);
    for (const { mark } of UNICODE_ERROR_MARKS) expect(stored).not.toContain(mark);
    await info.attach("unicode-persisted-notification", { body: stored!, contentType: "application/json" });
    expect(await accountSnapshot(page)).toEqual(beforeScope);
    for (const read of reads) expect(syntheticApi.callCount("GET", read.path)).toBe(read.count);
    presentationEvidence.assertWrites([{ method: "POST", path: ERROR_WRITE, body: ERROR_BODY }]);
  });
});

for (const viewport of [
  { name: "compact 1280x720", width: 1280, height: 720 },
  { name: "wide 1600x900", width: 1600, height: 900 },
]) for (const fixture of CAPTURED_ORIGIN_CASES) test.describe(`Captured origin ${fixture.name} / ${viewport.name}`, () => {
  const status = fixture.status ?? 500;
  const statusLabel = ({ 500: "500 (Internal Server Error)", 401: "401 (Unauthorized)", 403: "403 (Forbidden)", 503: "503 (Service Unavailable)" } as Record<number, string>)[status];
  test.use({ viewport: { width: viewport.width, height: viewport.height }, benignConsoleErrors: [{ text: `Failed to load resource: the server responded with a status of ${statusLabel}`, url: `http://localhost:5173${ERROR_WRITE}`, expectedCalls: 1 }] });
  test("literal selected request survives while the complete safe title or generic fallback is painted and persisted", async ({ page, syntheticApi, presentationEvidence }, info) => {
    const { symbol } = fixture;
    registerCapturedOriginReads(syntheticApi, symbol);
    const body = { ...ERROR_BODY, symbol };
    const raw = fixture.raw ?? { ...errorRaw(), affected_item: { ...errorRaw().affected_item, symbol } };
    syntheticApi.register({ name: "literal captured instrument error", method: "POST", path: ERROR_WRITE, expectedCalls: 1, handler: (request) => {
      assertRequest(request, "POST", ERROR_WRITE); expect(request.postDataJSON()).toEqual(body);
      return { status, json: raw };
    } });
    const observedReads = observeCapturedOriginReads(page); const { getRequests } = observedReads;
    await mountErrorPad(page, "live", true); await selectCapturedOrigin(page, symbol);
    await expect.poll(() => accountSnapshot(page)).toMatchObject({ scopeKey: ERROR_SCOPE, readsEnabled: true, writeTarget: { broker: "kotakneo", accountId: ERROR_A } });
    const metadataPath = `${errorPath("search")}?query=${encodeURIComponent(symbol)}&exchange=NSE`;
    await expect.poll(() => syntheticApi.callCount("GET", metadataPath)).toBeGreaterThanOrEqual(1);
    await awaitCapturedOriginStartup(page, observedReads, symbol, info);
    const beforeScope = await accountSnapshot(page);
    const beforeStored = JSON.parse(await page.evaluate(() => localStorage.getItem("flinttrade:notifications")) ?? "[]") as unknown[];
    expect(Array.isArray(beforeStored)).toBe(true);
    const beforeGets = [...getRequests];
    const paths = [errorPath("orders"), errorPath("positions"), errorPath("funds"), errorPath("orders", ERROR_B), errorPath("positions", ERROR_B), errorPath("funds", ERROR_B), "/ft-api/v1/sandbox/orders", "/ft-api/v1/sandbox/positions", "/ft-api/v1/sandbox/funds"];
    const reads = paths.map((path) => ({ path, count: syntheticApi.callCount("GET", path) }));
    const title = fixture.title ?? (fixture.safe ? `Order outcome unknown: BUY ${symbol}` : "Order outcome unknown");
    const expected = fixture.expected ?? (fixture.safe ? unknownCopy + ` Origin: kotakneo / KOTAK-OFFLINE · BUY ${symbol} (NSE / MIS). Broker reason (observation): Order is completed. Broker code: 1021.` : unknownCopy);
    await info.attach("captured-origin-before-submit", { body: JSON.stringify({ symbol, body, scope: beforeScope, beforeStored, reads, getRequests: beforeGets, viewport }, null, 2), contentType: "application/json" });
    const arrived = page.waitForResponse((response) => response.url().endsWith(ERROR_WRITE));
    await errorPad(page).getByRole("button", { name: "Place BUY Order", exact: true }).click();
    const response = await arrived; await response.finished(); expect(response.status()).toBe(status); expect(await response.json()).toEqual(raw);
    const alert = errorPad(page).getByRole("alert"); await tickUntil(page, alert);
    await expect(alert).toHaveText(expected);
    await expect(alert).not.toContainText(/Order filled|Position closed|Order placed|Not placed|Try again|Position flat|ACK/);
    if (status === 500) await expect(alert).not.toContainText("No order was sent");
    await expect(errorPad(page).getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);
    await expect(errorPad(page).getByRole("textbox", { name: "Symbol", exact: true })).toHaveValue(symbol);
    if (!fixture.safe) await expect(alert).not.toContainText(/Origin:|Broker reason|Broker code|INFY|BUY/);
    await assertPainted(alert, info, "captured-pad-box");
    await assertCapturedTextPainted(alert.locator("span").first(), info, "captured-pad-heading", fixture.expected ?? "Order outcome unknown.");
    await assertCapturedTextPainted(alert.locator("span").first(), info, "captured-pad-body", expected);
    await captureEvidence(page, info, "captured-pad-visible");
    expect(await notifications(page)).toEqual([expect.objectContaining({ category: "order", accountScopeKey: ERROR_SCOPE, skipAccountRefresh: true, title, body: expected })]);
    await page.getByRole("button", { name: /^Notifications —/ }).click(); await page.clock.runFor(700);
    const centre = page.getByRole("dialog", { name: "Notification Centre" }); await expect(centre).toBeVisible();
    const article = centre.getByRole("article").filter({ hasText: expected }); await expect(article).toHaveCount(1);
    const heading = article.getByText(title, { exact: true }); const paragraph = article.locator("p");
    await expect(heading).toHaveText(title); await expect(paragraph).toHaveText(expected);
    await expect(centre.getByText("Back to terminal", { exact: true })).toHaveCount(0);
    await assertPainted(article, info, "captured-central-box");
    await assertCapturedTextPainted(heading, info, "captured-central-heading", title);
    await assertCapturedTextPainted(paragraph, info, "captured-central-body", expected);
    await captureEvidence(page, info, "captured-central-visible");
    const stored = await page.evaluate(() => localStorage.getItem("flinttrade:notifications"));
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored!) as unknown[];
    expect(parsed).toEqual([expect.objectContaining({ category: "order", title, body: expected }), ...beforeStored]);
    expect(parsed[0]).not.toHaveProperty("action");
    const persistedNotice = parsed[0] as { title: string; body: string };
    expect(persistedNotice.title + persistedNotice.body).not.toMatch(/[\u0000-\u001f\u007f-\u009f\p{Bidi_Control}]/u);
    if (!fixture.safe) {
      expect(JSON.stringify(parsed[0])).not.toContain(symbol);
      await expect(article).not.toContainText(/INFY|BUY|Origin:|Broker reason|Broker code/);
    }
    await info.attach("captured-origin-persisted-notification", { body: JSON.stringify({ symbol, stored: parsed, events: await notifications(page) }, null, 2), contentType: "application/json" });
    expect(await accountSnapshot(page)).toEqual(beforeScope);
    // The registered health timer may tick while native paint is measured;
    // it is not a mutation-triggered account read. Keep every other GET exact.
    expect(getRequests.filter((path) => path !== "/ft-api/api/v1/ping")).toEqual(beforeGets.filter((path) => path !== "/ft-api/api/v1/ping"));
    for (const read of reads) expect(syntheticApi.callCount("GET", read.path)).toBe(read.count);
    presentationEvidence.assertWrites([{ method: "POST", path: ERROR_WRITE, body }]);
  });
});
