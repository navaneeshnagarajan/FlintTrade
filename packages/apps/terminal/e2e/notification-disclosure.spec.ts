import { assertRequest, captureEvidence, deferredResponse, expect, notifications, test, tickUntil } from "./order-flow-fixtures";
import { IND_A, IND_B, IND_BODY, IND_WRITE, accountSnapshot, acknowledgement, indPath, mountIndstocksPad, orderPad, registerIndstocksReads, selectIndstocksScope } from "./indstocks-disclosure-fixtures";
import { assertCapturedTextPainted, assertPainted } from "./operator-error-fixtures";
import type { SyntheticHandlerRegistration } from "./fixture-registry";

for (const viewport of [{ width: 1280, height: 720 }, { width: 1600, height: 900 }]) test.describe(`R177 acknowledgement attribution / ${viewport.width}`, () => {
  test.use({ viewport });
  test("late A acknowledgement remains painted and accessible in current B with persisted disclosure", async ({ page, syntheticApi, presentationEvidence }, info) => {
    const registrations: SyntheticHandlerRegistration[] = [];
    const recording = new Proxy(syntheticApi, { get(target, key) {
      if (key === "register") return (registration: SyntheticHandlerRegistration) => {
        registrations.push(registration); target.register(registration);
      };
      const value: unknown = Reflect.get(target, key);
      return typeof value === "function" ? value.bind(target) : value;
    } });
    registerIndstocksReads(recording, { accountSwitch: true });
    const late = deferredResponse();
    const raw = acknowledgement("SYNTHETIC-R177-LATE-A");
    syntheticApi.register({ name: "R177 exact late A ACK", method: "POST", path: IND_WRITE, expectedCalls: 1, handler: request => {
      assertRequest(request, "POST", IND_WRITE); expect(request.postDataJSON()).toEqual(IND_BODY); return late.promise;
    } });
    try {
      await mountIndstocksPad(page);
      await orderPad(page).getByRole("button", { name: "Place BUY Order", exact: true }).click();
      await expect.poll(() => syntheticApi.callCount("POST", IND_WRITE)).toBe(1);
      await selectIndstocksScope(page, `native:indmoney:${IND_B}`);
      for (const path of [indPath("orders", IND_B), indPath("positions", IND_B)]) await expect.poll(() => syntheticApi.callCount("GET", path)).toBeGreaterThanOrEqual(1);
      await page.clock.runFor(100);
      const paths = [indPath("orders"), indPath("positions"), indPath("orders", IND_B), indPath("positions", IND_B)];
      const reads = paths.map(path => syntheticApi.callCount("GET", path));
      const scope = await accountSnapshot(page);
      const before = await notifications(page);
      const arrived = page.waitForResponse(response => response.url().endsWith(IND_WRITE));
      late.release({ json: raw }); const response = await arrived; await response.finished(); expect(await response.json()).toEqual(raw);
      await tickUntil(page, orderPad(page).getByRole("button", { name: "Place BUY Order", exact: true }));
      await page.clock.runFor(100);
      expect(await notifications(page)).toEqual([...before, expect.objectContaining({ accountScopeKey: `live:native:indmoney:${IND_A}`, skipAccountRefresh: true, originDisclosure: { version: 1, kind: "captured", account: `live:native:indmoney:${IND_A}` } })]);
      await page.getByRole("button", { name: /^Notifications/ }).click(); await page.clock.runFor(700);
      const article = page.getByRole("dialog", { name: "Notification Centre" }).getByRole("article").filter({ hasText: "SYNTHETIC-R177-LATE-A" });
      const origin = `Origin: live:native:indmoney:${IND_A}`;
      await expect(article).toHaveAccessibleName(new RegExp(origin)); await expect(article).not.toContainText(IND_B);
      await assertPainted(article, info, "r177-late-ack-box");
      const originParagraph = article.getByText(origin, { exact: true });
      await expect(originParagraph).toHaveText(origin);
      // React emits the label and captured value as two text nodes. Measure
      // every literal range in this exact paragraph, not an impossible
      // single-text-node substring; preserve all clipping/hit assertions.
      await assertCapturedTextPainted(originParagraph, info, "r177-late-ack-origin");
      await captureEvidence(page, info, "r177-late-ack-visible");
      const stored = JSON.parse(await page.evaluate(() => localStorage.getItem("flinttrade:notifications")) ?? "[]") as Array<{ body: string }>;
      expect(stored.find(item => item.body.includes("SYNTHETIC-R177-LATE-A"))).toMatchObject({ accountScopeKey: `live:native:indmoney:${IND_A}`, originDisclosure: { version: 1, kind: "captured", account: `live:native:indmoney:${IND_A}` } });
      await info.attach("r177-persisted-late-ack", { body: JSON.stringify({ stored, scope, reads }), contentType: "application/json" });
      expect(await accountSnapshot(page)).toEqual(scope); expect(paths.map(path => syntheticApi.callCount("GET", path))).toEqual(reads);
      presentationEvidence.assertWrites([{ method: "POST", path: IND_WRITE, body: IND_BODY }]);
      // A new document has a distinct startup read phase. Retire and validate
      // every first-phase GET before registering the same bounded startup
      // contract. Account selection is not persisted by the existing store:
      // reload hydrates A, then select B again through its public action.
      const retired = [];
      for (const registration of registrations) {
        if (registration.method !== "GET") continue;
        retired.push({ path: registration.path, counts: await syntheticApi.retireRead(registration.path) });
      }
      for (const registration of registrations) {
        if (registration.method === "GET") {
          syntheticApi.register({ ...registration, name: `reload: ${registration.name}` });
        }
      }
      await info.attach("r177-before-reload-read-phases", { body: JSON.stringify(retired), contentType: "application/json" });
      await page.reload();
      await tickUntil(page, orderPad(page).getByRole("button", { name: "Place BUY Order", exact: true }));
      await selectIndstocksScope(page, `native:indmoney:${IND_B}`);
      await tickUntil(page, page.getByRole("button", { name: /^Notifications/ }));
      await page.getByRole("button", { name: /^Notifications/ }).click(); await page.clock.runFor(700);
      const restored = page.getByRole("dialog", { name: "Notification Centre" }).getByRole("article").filter({ hasText: "SYNTHETIC-R177-LATE-A" });
      await expect(restored).toHaveAccessibleName(new RegExp(origin)); await expect(restored).not.toContainText(IND_B);
      await expect(restored.getByText(origin, { exact: true })).toHaveText(origin);
      await assertCapturedTextPainted(restored.getByText(origin, { exact: true }), info, "r177-reloaded-ack-origin");
      await captureEvidence(page, info, "r177-reloaded-ack-visible");
      expect(await accountSnapshot(page)).toMatchObject({ activeAccountId: `native:indmoney:${IND_B}`, scopeKey: `live:native:indmoney:${IND_B}` });
      const reloaded = JSON.parse(await page.evaluate(() => localStorage.getItem("flinttrade:notifications")) ?? "[]") as Array<{ body: string }>;
      expect(reloaded.find(item => item.body.includes("SYNTHETIC-R177-LATE-A"))).toEqual(stored.find(item => item.body.includes("SYNTHETIC-R177-LATE-A")));
      presentationEvidence.assertWrites([{ method: "POST", path: IND_WRITE, body: IND_BODY }]);
    } finally { late.release({ json: raw }); }
  });
});
