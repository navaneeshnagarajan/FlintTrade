import { expect, test as baseTest, type Page } from "@playwright/test";

import {
  createSyntheticFixtureRegistry,
  expect as journeyExpect,
  test as journeyTest,
  type HttpMethod,
  type SyntheticFixtureRegistry,
} from "./fixture-registry";

const FRONTEND_ORIGIN = "https://synthetic.flinttrade.invalid";

async function createRegistry(
  page: Page,
  name: string,
  benignConsoleErrors: readonly string[] = [],
): Promise<SyntheticFixtureRegistry> {
  return createSyntheticFixtureRegistry(page, {
    name,
    frontendOrigin: FRONTEND_ORIGIN,
    benignConsoleErrors,
  });
}

async function fetchJson(page: Page, method: HttpMethod, path: string): Promise<unknown> {
  return page.evaluate(
    async ({ requestMethod, requestUrl }) => {
      const response = await fetch(requestUrl, {
        method: requestMethod,
        body: requestMethod === "GET" || requestMethod === "HEAD" ? undefined : "{}",
      });
      return response.json();
    },
    { requestMethod: method, requestUrl: `${FRONTEND_ORIGIN}${path}` },
  );
}

async function expectFetchToFail(page: Page, method: HttpMethod, path: string): Promise<void> {
  await expect(fetchJson(page, method, path)).rejects.toThrow();
}

baseTest.describe("fail-closed synthetic fixture registry", () => {
  baseTest("serves one exact named method-and-path handler", async ({ page }) => {
    const registry = await createRegistry(page, "exact handler");
    registry.register({
      name: "terminal status",
      method: "GET",
      path: "/api/status",
      handler: () => ({ json: { status: "ok", version: "e039" } }),
    });

    await expect(fetchJson(page, "GET", "/api/status")).resolves.toEqual({
      status: "ok",
      version: "e039",
    });
    expect(registry.callCount("GET", "/api/status")).toBe(1);
    await expect(registry.dispose()).resolves.toBeUndefined();
  });

  baseTest("assertSatisfied checks usage without disposing the registry", async ({ page }) => {
    const registry = await createRegistry(page, "explicit assertion");
    registry.register({
      name: "asserted status",
      method: "GET",
      path: "/api/asserted",
      handler: () => ({ json: { ok: true } }),
    });

    expect(() => registry.assertSatisfied()).toThrow(
      /unused handler.*asserted status.*expected 1.*observed 0/is,
    );
    await expect(fetchJson(page, "GET", "/api/asserted")).resolves.toEqual({ ok: true });
    expect(() => registry.assertSatisfied()).not.toThrow();
    await expect(registry.dispose()).resolves.toBeUndefined();
  });

  baseTest("dispose rejects an unused expected handler", async ({ page }) => {
    const registry = await createRegistry(page, "unused handler");
    registry.register({
      name: "must be called",
      method: "GET",
      path: "/api/required",
      handler: () => ({ json: { ok: true } }),
    });

    await expect(registry.dispose()).rejects.toThrow(
      /unused handler.*must be called.*GET \/api\/required.*expected 1.*observed 0/is,
    );
  });

  baseTest("records method mismatch evidence", async ({ page }) => {
    const registry = await createRegistry(page, "method mismatch");
    registry.register({
      name: "read status",
      method: "GET",
      path: "/api/status",
      handler: () => ({ json: { ok: true } }),
    });

    await expectFetchToFail(page, "POST", "/api/status");
    await expect(registry.dispose()).rejects.toThrow(
      /method mismatch.*POST \/api\/status.*read status.*GET/is,
    );
  });

  baseTest("records path mismatch evidence", async ({ page }) => {
    const registry = await createRegistry(page, "path mismatch");
    registry.register({
      name: "read status",
      method: "GET",
      path: "/api/status",
      handler: () => ({ json: { ok: true } }),
    });

    await expectFetchToFail(page, "GET", "/api/other");
    await expect(registry.dispose()).rejects.toThrow(
      /path mismatch.*GET \/api\/other.*read status.*\/api\/status/is,
    );
  });

  baseTest("records an unexpected request when no handler is related", async ({ page }) => {
    const registry = await createRegistry(page, "unexpected request");

    await expectFetchToFail(page, "DELETE", "/api/unexpected");
    await expect(registry.dispose()).rejects.toThrow(
      /unexpected request.*DELETE \/api\/unexpected/is,
    );
  });

  baseTest("rejects duplicate exact handlers at registration", async ({ page }) => {
    const registry = await createRegistry(page, "duplicate handler");
    registry.register({
      name: "first status handler",
      method: "GET",
      path: "/api/status",
      handler: () => ({ json: { source: "first" } }),
    });

    expect(() => {
      registry.register({
        name: "second status handler",
        method: "GET",
        path: "/api/status",
        handler: () => ({ json: { source: "second" } }),
      });
    }).toThrow(/duplicate handler.*GET \/api\/status.*first status handler.*second status handler/is);

    await expect(fetchJson(page, "GET", "/api/status")).resolves.toEqual({ source: "first" });
    await expect(registry.dispose()).resolves.toBeUndefined();
  });

  baseTest("records handler overuse and does not invoke it again", async ({ page }) => {
    const registry = await createRegistry(page, "handler overuse");
    let invocations = 0;
    registry.register({
      name: "single-use status",
      method: "GET",
      path: "/api/status",
      expectedCalls: 1,
      handler: () => {
        invocations += 1;
        return { json: { invocation: invocations } };
      },
    });

    await expect(fetchJson(page, "GET", "/api/status")).resolves.toEqual({ invocation: 1 });
    await expectFetchToFail(page, "GET", "/api/status");
    expect(invocations).toBe(1);
    await expect(registry.dispose()).rejects.toThrow(
      /handler overuse.*single-use status.*GET \/api\/status.*expected 1.*observed 2/is,
    );
  });

  baseTest("dispose clears state so a fresh registry can reuse the same exact handler", async ({ page }) => {
    const first = await createRegistry(page, "first isolated registry");
    first.register({
      name: "first isolated handler",
      method: "GET",
      path: "/api/isolated",
      handler: () => ({ json: { registry: "first" } }),
    });
    await expect(fetchJson(page, "GET", "/api/isolated")).resolves.toEqual({ registry: "first" });
    await first.dispose();
    expect(() => first.callCount("GET", "/api/isolated")).toThrow(/disposed/i);

    const second = await createRegistry(page, "second isolated registry");
    expect(second.callCount("GET", "/api/isolated")).toBe(0);
    second.register({
      name: "second isolated handler",
      method: "GET",
      path: "/api/isolated",
      handler: () => ({ json: { registry: "second" } }),
    });
    await expect(fetchJson(page, "GET", "/api/isolated")).resolves.toEqual({ registry: "second" });
    await expect(second.dispose()).resolves.toBeUndefined();
  });

  baseTest("captures an asynchronous pageerror from a data-page script", async ({ page }) => {
    const registry = await createRegistry(page, "pageerror capture");
    const pageError = page.waitForEvent("pageerror");
    const html = `<script>setTimeout(() => { throw new Error("async pageerror evidence"); }, 0);<\/script>`;

    await page.goto(`data:text/html,${encodeURIComponent(html)}`);
    await pageError;

    await expect(registry.dispose()).rejects.toThrow(/pageerror.*async pageerror evidence/is);
  });

  baseTest("captures an unhandled rejection from a data-page script", async ({ page }) => {
    const registry = await createRegistry(page, "unhandled rejection capture");
    const rejectionSignal = page.waitForEvent("console", (message) =>
      message.text().includes("async rejection evidence"),
    );
    const html = `<script>setTimeout(() => { Promise.reject(new Error("async rejection evidence")); }, 0);<\/script>`;

    await page.goto(`data:text/html,${encodeURIComponent(html)}`);
    await rejectionSignal;

    await expect(registry.dispose()).rejects.toThrow(
      /unhandled rejection.*async rejection evidence/is,
    );
  });

  baseTest("rejects a non-allowlisted console error", async ({ page }) => {
    const registry = await createRegistry(page, "console error capture");
    const consoleError = page.waitForEvent(
      "console",
      (message) => message.type() === "error" && message.text() === "real console failure",
    );

    await page.evaluate(() => console.error("real console failure"));
    await consoleError;

    await expect(registry.dispose()).rejects.toThrow(/console error.*real console failure/is);
  });

  baseTest("allows only an exact explicitly benign console error", async ({ page }) => {
    const registry = await createRegistry(page, "benign console allowlist", [
      "known benign browser message",
    ]);
    const benignConsoleError = page.waitForEvent(
      "console",
      (message) => message.type() === "error" && message.text() === "known benign browser message",
    );

    await page.evaluate(() => console.error("known benign browser message"));
    await benignConsoleError;

    await expect(registry.dispose()).resolves.toBeUndefined();
  });

  baseTest("does not treat an allowlist substring as benign", async ({ page }) => {
    const registry = await createRegistry(page, "strict benign console allowlist", [
      "known benign browser message",
    ]);
    const consoleError = page.waitForEvent("console", (message) =>
      message.text().includes("unexpected suffix"),
    );

    await page.evaluate(() => console.error("known benign browser message - unexpected suffix"));
    await consoleError;

    await expect(registry.dispose()).rejects.toThrow(
      /console error.*known benign browser message - unexpected suffix/is,
    );
  });
});

journeyTest("the shared journey fixture disposes automatically after exact expected usage", async ({
  page,
  syntheticApi,
}) => {
  syntheticApi.register({
    name: "automatic fixture handler",
    method: "GET",
    path: "/api/automatic",
    handler: () => ({ json: { guarded: true } }),
  });

  await journeyExpect(fetchJson(page, "GET", "/api/automatic")).resolves.toEqual({ guarded: true });
  // No explicit dispose: the auto fixture must assert and clean up after this body.
});

journeyTest("the auto fixture fails teardown for an unused expected handler", async ({
  syntheticApi,
}) => {
  journeyTest.fail(true, "An unused handler must make automatic teardown fail");
  syntheticApi.register({
    name: "deliberately unused automatic handler",
    method: "GET",
    path: "/api/must-be-used",
    handler: () => ({ json: { unreachable: true } }),
  });
});

journeyTest("the client-error guard is automatic even when syntheticApi is not requested", async ({
  page,
}) => {
  journeyTest.fail(true, "A non-allowlisted console error must make automatic teardown fail");
  const consoleError = page.waitForEvent(
    "console",
    (message) => message.type() === "error" && message.text() === "automatic guard evidence",
  );

  await page.evaluate(() => console.error("automatic guard evidence"));
  await consoleError;
});
