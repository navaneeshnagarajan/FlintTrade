import fs from "node:fs/promises";
import type { Locator, TestInfo } from "@playwright/test";
import {
  CANCEL_WARNING, captureEvidence, exitRow, expect, foreverPath, mountWidget, nativePath,
  positionRow, registerAccountBooks, registerDeskReads, registerRead, test, tickUntil,
} from "./order-flow-fixtures";
import type { SyntheticPhasedFixtureRegistry } from "./fixture-registry";

async function retireStartupOrders(registry: SyntheticPhasedFixtureRegistry, info: TestInfo) {
  const counts = await registry.retireRead(nativePath("orders"));
  // Startup has exactly one completed book. The separate, bounded cancelled
  // StrictMode GET is optional, never a second required fulfilled read.
  expect(counts.completed).toBe(1);
  expect(counts.pending).toBe(0);
  expect(counts.failed).toBe(0);
  expect(counts.cancelled).toBe(counts.calls - 1);
  expect(counts.cancelled).toBeLessThanOrEqual(1);
  const path = info.outputPath("startup-book-phase.json");
  await fs.writeFile(path, JSON.stringify(counts, null, 2));
  await info.attach("startup-book-phase", { path, contentType: "application/json" });
  return counts;
}

async function captureGeometry(target: Locator, info: TestInfo, label: string) {
  const geometry = await target.evaluate((element) => {
    const box = (node: Element) => {
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        tag: node.tagName, id: node.id, className: node.getAttribute("class"),
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height, bottom: rect.bottom },
        clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, scrollTop: node.scrollTop,
        display: style.display, overflowX: style.overflowX, overflowY: style.overflowY,
        flex: style.flex, minHeight: style.minHeight,
      };
    };
    const ancestors = [];
    for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) ancestors.push(box(ancestor));
    return { viewport: { width: innerWidth, height: innerHeight }, target: box(element), ancestors };
  });
  const path = info.outputPath(`${label}-geometry.json`);
  await fs.writeFile(path, JSON.stringify(geometry, null, 2));
  await info.attach(`${label}-geometry`, { path, contentType: "application/json" });
}

async function expectPainted(target: Locator): Promise<void> {
  // Intersection catches overflow clipping; hit-testing also catches a sticky
  // warning or another layer painted over the apparently intersecting text.
  await expect(target).toBeInViewport({ ratio: 1 });
  expect(await target.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const painted = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    return painted !== null && element.contains(painted);
  })).toBe(true);
}

const unavailableOrders = [
  { name: "unavailable", json: { status: "error", message: "Synthetic order evidence unavailable." }, detail: "Synthetic order evidence unavailable." },
  { name: "missing data", json: { status: "success" }, detail: "unavailable or malformed" },
  { name: "null", json: { status: "success", data: null }, detail: "unavailable or malformed" },
  { name: "object", json: { status: "success", data: {} }, detail: "unavailable or malformed" },
  { name: "mixed row", json: { status: "success", data: [exitRow(), null] }, detail: "unavailable or malformed" },
];

for (const fixture of unavailableOrders) {
  test(`1280x720 canonical Positions keeps ${fixture.name} risk copy and retained quantity readable`, async ({
    page, syntheticApi, presentationEvidence,
  }, info) => {
    registerDeskReads(syntheticApi);
    let recovered = false;
    registerAccountBooks(syntheticApi, {
      orderCalls: 1, orderReadPhase: "startup",
      orders: () => recovered
        ? { json: { status: "success", data: [] } }
        : { json: fixture.json },
    });
    registerRead(syntheticApi, foreverPath(), { json: { status: "success", data: [] } });
    await page.setViewportSize({ width: 1280, height: 720 });
    // Only the canonical bottom book hosts Positions, never the saved top widget.
    await mountWidget(page, "foreverorders");
    const surface = page.locator("#trade-bottom-panel-positions");
    await expect(surface).toHaveAttribute("role", "tabpanel");
    const warning = surface.getByTestId("exit-orders-unavailable");
    await tickUntil(page, warning);
    await expect(warning).toContainText("Broker orders are unavailable. Reconcile them before another exit.");
    await expect(warning).toContainText(fixture.detail);
    const retained = surface.getByText("SYNTHETIC-ALPHA", { exact: true });
    const row = surface.getByRole("row").filter({ hasText: "SYNTHETIC-ALPHA" });
    const quantity = row.getByRole("cell", { name: "10", exact: true });
    await expect(quantity).toHaveText("10");
    await expect(surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toHaveCount(0);
    await expect(surface.getByRole("button", { name: "Exit all positions" })).toHaveCount(0);
    await captureGeometry(retained, info, "before-scroll");
    await captureEvidence(page, info, "compact-warning-and-row-before-scroll");
    await retained.scrollIntoViewIfNeeded();
    await captureGeometry(retained, info, "after-scroll");
    await captureGeometry(quantity, info, "quantity-after-scroll");
    await captureGeometry(warning, info, "warning-after-scroll");
    await captureEvidence(page, info, "compact-warning-and-row-after-scroll");
    // Soft checks keep the exact recovery/no-write contract exercised in the red run.
    await expect.soft(retained).toBeInViewport({ ratio: 1 });
    await expect.soft(quantity).toBeInViewport({ ratio: 1 });
    await expect.soft(warning).toBeInViewport({ ratio: 1 });
    await expectPainted(retained);
    await expectPainted(quantity);
    await expectPainted(warning);
    const initialReads = syntheticApi.callCount("GET", nativePath("orders"));
    const startup = await retireStartupOrders(syntheticApi, info);
    expect(initialReads).toBe(startup.calls);
    registerRead(syntheticApi, nativePath("orders"), () => {
      expect(recovered).toBe(true);
      return { json: { status: "success", data: [] } };
    }, 1, "required");
    recovered = true;
    await page.evaluate(() => window.dispatchEvent(new CustomEvent("flinttrade:ordersChanged")));
    await tickUntil(page, surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" }));
    await expect(warning).toHaveCount(0);
    await expect(surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toBeEnabled();
    await expect(surface.getByRole("button", { name: "Exit all positions" })).toBeEnabled();
    await expect(quantity).toHaveText("10");
    await retained.scrollIntoViewIfNeeded();
    await expectPainted(retained);
    await expectPainted(quantity);
    expect(syntheticApi.callCount("GET", nativePath("orders"))).toBe(initialReads + 1);
    const recoveredReads = await syntheticApi.retireRead(nativePath("orders"));
    expect(recoveredReads).toEqual({ ...startup, calls: initialReads + 1, completed: startup.completed + 1 });
    const phasePath = info.outputPath("recovery-book-phase.json");
    await fs.writeFile(phasePath, JSON.stringify({ startup, recovered: recoveredReads }, null, 2));
    await info.attach("recovery-book-phase", { path: phasePath, contentType: "application/json" });
    expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(1);
    presentationEvidence.assertWrites([]);
  });
}

test("canonical warning and row survive 1024x768 resize and return to 1280x720", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi);
  registerAccountBooks(syntheticApi, {
    orderCalls: 1, orderReadPhase: "startup", orders: { json: { status: "success", data: null } },
  });
  registerRead(syntheticApi, foreverPath(), { json: { status: "success", data: [] } });
  await page.setViewportSize({ width: 1280, height: 720 });
  await mountWidget(page, "foreverorders");
  const surface = page.locator("#trade-bottom-panel-positions");
  await tickUntil(page, surface.getByTestId("exit-orders-unavailable"));
  const retained = surface.getByText("SYNTHETIC-ALPHA", { exact: true });
  const quantity = surface.getByRole("row").filter({ hasText: "SYNTHETIC-ALPHA" })
    .getByRole("cell", { name: "10", exact: true });
  for (const viewport of [{ width: 1024, height: 768 }, { width: 1280, height: 720 }]) {
    await page.setViewportSize(viewport);
    await page.clock.runFor(50);
    await retained.scrollIntoViewIfNeeded();
    // A resize can leave the symbol visible while the taller quantity cell is
    // still cropped. Scroll the actual row's quantity too, not another book.
    await quantity.scrollIntoViewIfNeeded();
    // Use the book's normal keyboard scroll endpoint after resizing. Chromium
    // can round scrollIntoViewIfNeeded half a pixel short of a whole table cell.
    await surface.getByRole("region", { name: "Positions book", exact: true }).press("End");
    await page.clock.runFor(200);
    await captureGeometry(quantity, info, `${viewport.width}x${viewport.height}-quantity`);
    await expectPainted(retained);
    await expectPainted(quantity);
    await expectPainted(surface.getByTestId("exit-orders-unavailable"));
    await expect(surface.getByRole("button", { name: "Exit all positions" })).toHaveCount(0);
    await captureGeometry(retained, info, `${viewport.width}x${viewport.height}`);
    await captureEvidence(page, info, `canonical-${viewport.width}x${viewport.height}`);
  }
  expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(1);
  await retireStartupOrders(syntheticApi, info);
  presentationEvidence.assertWrites([]);
});

test("keyboard reaches the last canonical row while keeping the warning readable", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi);
  const rows = [positionRow(), ...Array.from({ length: 11 }, (_, index) => ({
    ...positionRow(), symbol: `SYNTHETIC-ROW-${index + 2}`,
  }))];
  registerAccountBooks(syntheticApi, {
    positions: { json: { status: "success", data: rows } },
    orderCalls: 1, orderReadPhase: "startup", orders: { json: { status: "success", data: null } },
  });
  registerRead(syntheticApi, foreverPath(), { json: { status: "success", data: [] } });
  await page.setViewportSize({ width: 1280, height: 720 });
  await mountWidget(page, "foreverorders");
  const surface = page.locator("#trade-bottom-panel-positions");
  const warning = surface.getByTestId("exit-orders-unavailable");
  await tickUntil(page, warning);
  const book = surface.getByRole("region", { name: "Positions book", exact: true });
  await expect(book).toHaveAttribute("tabindex", "0");
  await book.focus();
  await expect(book).toBeFocused();
  await book.press("End");
  await page.clock.runFor(200);
  const last = surface.getByText("SYNTHETIC-ROW-12", { exact: true });
  await captureGeometry(last, info, "last-row-keyboard");
  await expectPainted(last);
  await expectPainted(surface.getByRole("row").filter({ hasText: "SYNTHETIC-ROW-12" })
    .getByRole("cell", { name: "10", exact: true }));
  await expectPainted(warning);
  await expect(surface.getByRole("button", { name: "Exit all positions" })).toHaveCount(0);
  await captureGeometry(last, info, "last-row-keyboard");
  await captureEvidence(page, info, "keyboard-last-row-warning");
  await book.press("Home");
  await page.clock.runFor(200);
  await expectPainted(surface.getByText("P&L: +₹120", { exact: true }));
  await expectPainted(surface.getByRole("status", { name: "Positions last updated 05:30:00", exact: true }));
  expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(1);
  await retireStartupOrders(syntheticApi, info);
  presentationEvidence.assertWrites([]);
});

test("normal narrow workspace cards preserve pending risk, quantity, P&L and update time", async ({
  page, syntheticApi, presentationEvidence,
}, info) => {
  registerDeskReads(syntheticApi);
  registerAccountBooks(syntheticApi, {
    orders: { json: { status: "success", data: [exitRow()] } }, orderCalls: 1, orderReadPhase: "startup",
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await mountWidget(page, "positions", true);
  const narrow = page.getByRole("tabpanel", { name: "Narrow Positions", exact: true });
  const cards = narrow.getByRole("list", { name: "Positions", exact: true });
  await tickUntil(page, cards);
  const book = narrow.getByRole("region", { name: "Positions book", exact: true });
  expect((await book.boundingBox())?.width).toBeLessThanOrEqual(480);
  await expect(cards).toContainText("Qty 10 · LTP 101.00");
  await expect(cards).toContainText(CANCEL_WARNING);
  await expectPainted(cards.getByText("SYNTHETIC-ALPHA", { exact: true }));
  await expectPainted(cards.getByText("+₹10", { exact: true }));
  await expectPainted(cards.getByText("+1.00%", { exact: true }));
  await expect(narrow.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toBeDisabled();
  await expect(narrow.getByRole("status", { name: "Positions last updated 05:30:00", exact: true })).toBeVisible();
  await captureEvidence(page, info, "normal-narrow-card");
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.clock.runFor(50);
  await expect(cards).toBeVisible();
  await expect(cards).toContainText("Qty 10");
  await expect(narrow.getByRole("button", { name: "Square off SYNTHETIC-ALPHA" })).toBeDisabled();
  await captureEvidence(page, info, "normal-narrow-card-resize");
  expect(syntheticApi.callCount("GET", nativePath("positions"))).toBe(1);
  await retireStartupOrders(syntheticApi, info);
  presentationEvidence.assertWrites([]);
});
