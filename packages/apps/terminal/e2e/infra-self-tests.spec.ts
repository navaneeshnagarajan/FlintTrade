import { createServer } from "node:http";

import { expect, test as baseTest, type Page, type Request } from "@playwright/test";

import {
  createSyntheticFixtureRegistry,
  expect as journeyExpect,
  test as journeyTest,
  type BenignConsoleError,
  type HttpMethod,
  type SyntheticFixtureRegistry,
} from "./fixture-registry";

const FRONTEND_ORIGIN = "https://synthetic.flinttrade.invalid";

async function createRegistry(
  page: Page,
  name: string,
  benignConsoleErrors: readonly BenignConsoleError[] = [],
  frontendOrigin = FRONTEND_ORIGIN,
): Promise<SyntheticFixtureRegistry> {
  return createSyntheticFixtureRegistry(page, {
    name,
    frontendOrigin,
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

const FRONTEND_RESOURCE_TYPES = [
  "document",
  "font",
  "image",
  "manifest",
  "script",
  "stylesheet",
] as const;

type FrontendResourceType = (typeof FRONTEND_RESOURCE_TYPES)[number];

interface StaticFrontendServer {
  origin: string;
  hitCount(path: string): number;
  close(): Promise<void>;
}

function escapeHtmlAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function startStaticFrontendServer(
  manifestTargetPath?: string,
): Promise<StaticFrontendServer> {
  const hits = new Map<string, number>();
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    hits.set(url.pathname, (hits.get(url.pathname) ?? 0) + 1);
    if (url.pathname === "/manifest-probe.html") {
      if (!manifestTargetPath) {
        response.writeHead(404, { "content-type": "text/plain" });
        response.end("manifest target is not configured");
        return;
      }
      response.writeHead(200, { "content-type": "text/html" });
      response.end(
        `<link rel="manifest" href="${escapeHtmlAttribute(manifestTargetPath)}">`,
      );
      return;
    }

    const extension = url.pathname.split(".").at(-1);
    const contentType =
      extension === "css"
        ? "text/css"
        : extension === "js"
          ? "text/javascript"
          : extension === "svg"
            ? "image/svg+xml"
            : extension === "webmanifest"
              ? "application/manifest+json"
              : "text/html";
    const body =
      extension === "svg"
        ? '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" />'
        : extension === "webmanifest"
          ? '{"name":"FlintTrade","short_name":"FlintTrade","start_url":"/"}'
          : extension === "js"
            ? "void 0;"
            : extension === "css"
              ? ":root {}"
              : "<!doctype html><title>frontend resource</title>";
    response.writeHead(200, { "content-type": contentType });
    response.end(body);
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("static frontend test server did not bind a TCP port");
  }

  return {
    origin: `http://127.0.0.1:${address.port}`,
    hitCount: (path: string) => hits.get(path) ?? 0,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  };
}

async function requestFrontendResource(
  page: Page,
  resourceType: FrontendResourceType,
  frontendOrigin: string,
  path: string,
): Promise<Request> {
  const requestUrl = `${frontendOrigin}${path}`;
  const requestStarted = page.waitForRequest((request) => request.url() === requestUrl);

  if (resourceType === "manifest") {
    await page.goto(`${frontendOrigin}/manifest-probe.html`);
    const devtools = await page.context().newCDPSession(page);
    try {
      await devtools.send("Page.getAppManifest");
    } finally {
      await devtools.detach();
    }
  } else {
    await page.evaluate(
      ({ type, url }) => {
        if (type === "font") {
          const preload = document.createElement("link");
          preload.rel = "preload";
          preload.as = "font";
          preload.href = url;
          document.head.append(preload);
          return;
        }

        const element = document.createElement(
          type === "document" ? "iframe" : type === "image" ? "img" : "link",
        );
        if (element instanceof HTMLIFrameElement || element instanceof HTMLImageElement) {
          element.src = url;
        } else if (type === "stylesheet") {
          element.rel = "stylesheet";
          element.href = url;
        } else {
          const script = document.createElement("script");
          script.src = url;
          document.body.append(script);
          return;
        }
        document.body.append(element);
      },
      { type: resourceType, url: requestUrl },
    );
  }

  const request = await requestStarted;
  expect(request.resourceType()).toBe(resourceType);
  return request;
}

const API_RESOURCE_BOUNDARIES = [
  { label: "canonical /api", pathStem: "/api/unregistered" },
  { label: "canonical /ft-api", pathStem: "/ft-api/unregistered" },
  { label: "raw /api lookalike", pathStem: "/apiary/unregistered" },
  { label: "raw /ft-api lookalike", pathStem: "/ft-apiary/unregistered" },
  { label: "encoded /api separator", pathStem: "/api%2Funregistered" },
  { label: "encoded /ft-api separator", pathStem: "/ft-api%2Funregistered" },
] as const;

baseTest.describe("fail-closed synthetic fixture registry", () => {
  baseTest("manifest probe uses only its escaped closure-bound target", async ({ page }) => {
    const manifestTarget = '/manifest.webmanifest?probe=&"<>';
    const reflectedTarget = '"><script data-injected="true"></script><link href="';
    const server = await startStaticFrontendServer(manifestTarget);
    try {
      await page.goto(
        `${server.origin}/manifest-probe.html?target=${encodeURIComponent(reflectedTarget)}`,
      );

      await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", manifestTarget);
      await expect(page.locator('script[data-injected="true"]')).toHaveCount(0);
    } finally {
      await server.close();
    }
  });

  for (const boundary of API_RESOURCE_BOUNDARIES) {
    for (const resourceType of FRONTEND_RESOURCE_TYPES) {
      baseTest(`records and aborts an unregistered ${boundary.label} ${resourceType} request`, async ({
        page,
      }) => {
        const extension =
          resourceType === "manifest"
            ? ".webmanifest"
            : resourceType === "stylesheet"
              ? ".css"
              : resourceType === "script"
                ? ".js"
                : resourceType === "image"
                  ? ".svg"
                  : ".html";
        const path = `${boundary.pathStem}-${resourceType}${extension}`;
        const server = await startStaticFrontendServer(
          resourceType === "manifest" ? path : undefined,
        );
        try {
          const registry = await createRegistry(
            page,
            `unregistered ${boundary.label} ${resourceType} request`,
            [],
            server.origin,
          );

          const request = await requestFrontendResource(page, resourceType, server.origin, path);

          expect(await request.response()).toBeNull();
          expect(server.hitCount(path)).toBe(0);
          await expect(registry.dispose()).rejects.toThrow(
            new RegExp(`unexpected request.*GET ${path.replace(".", "\\.")}`, "is"),
          );
        } finally {
          await server.close();
        }
      });
    }
  }

  baseTest("allows a same-origin static frontend image to load", async ({ page }) => {
    const server = await startStaticFrontendServer();
    try {
      const registry = await createRegistry(page, "valid frontend image", [], server.origin);
      const imageUrl = `${server.origin}/assets/logo.svg`;
      const response = page.waitForResponse((candidate) => candidate.url() === imageUrl);

      await page.setContent(`<img src="${imageUrl}" alt="FlintTrade">`);

      expect((await response).ok()).toBe(true);
      expect(server.hitCount("/assets/logo.svg")).toBe(1);
      await expect(registry.dispose()).resolves.toBeUndefined();
    } finally {
      await server.close();
    }
  });

  baseTest("counts one registered /ft-api image request exactly", async ({ page }) => {
    const server = await startStaticFrontendServer();
    try {
      const registry = await createRegistry(page, "registered API image", [], server.origin);
      const path = "/ft-api/registered-image.svg";
      registry.register({
        name: "registered API image",
        method: "GET",
        path,
        handler: () => ({
          contentType: "image/svg+xml",
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" />',
        }),
      });

      const request = await requestFrontendResource(page, "image", server.origin, path);

      expect((await request.response())?.ok()).toBe(true);
      expect(registry.callCount("GET", path)).toBe(1);
      expect(server.hitCount(path)).toBe(0);
      await expect(registry.dispose()).resolves.toBeUndefined();
    } finally {
      await server.close();
    }
  });

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

  baseTest("dispose waits for an in-flight handler failure", async ({ page }) => {
    const registry = await createRegistry(page, "in-flight handler failure");
    let markHandlerEntered: (() => void) | undefined;
    const handlerEntered = new Promise<void>((resolve) => {
      markHandlerEntered = resolve;
    });
    let releaseHandler: (() => void) | undefined;
    const handlerGate = new Promise<void>((resolve) => {
      releaseHandler = resolve;
    });
    registry.register({
      name: "slow failing handler",
      method: "GET",
      path: "/api/slow-failure",
      handler: async () => {
        markHandlerEntered?.();
        await handlerGate;
        throw new Error("late handler evidence");
      },
    });

    const request = fetchJson(page, "GET", "/api/slow-failure");
    await handlerEntered;
    const disposal = registry.dispose();
    releaseHandler?.();

    await expect(request).rejects.toThrow();
    await expect(disposal).rejects.toThrow(/handler error.*late handler evidence/is);
  });

  baseTest("dispose aborts and records a second request while an owned handler drains", async ({
    page,
  }) => {
    const registry = await createSyntheticFixtureRegistry(page, {
      name: "request during automatic teardown",
      frontendOrigin: FRONTEND_ORIGIN,
      closePageOnDispose: true,
    });
    let markHandlerEntered: (() => void) | undefined;
    const handlerEntered = new Promise<void>((resolve) => {
      markHandlerEntered = resolve;
    });
    let markHandlerCompleted: (() => void) | undefined;
    const handlerCompleted = new Promise<void>((resolve) => {
      markHandlerCompleted = resolve;
    });
    let releaseHandler: (() => void) | undefined;
    const handlerGate = new Promise<void>((resolve) => {
      releaseHandler = resolve;
    });
    registry.register({
      name: "slow successful handler",
      method: "GET",
      path: "/api/slow-success",
      handler: async () => {
        markHandlerEntered?.();
        await handlerGate;
        markHandlerCompleted?.();
        return { json: { drained: true } };
      },
    });

    const firstRequestOutcome = fetchJson(page, "GET", "/api/slow-success").then(
      (value) => ({ status: "resolved" as const, value }),
      (error: unknown) => ({
        status: "rejected" as const,
        message: error instanceof Error ? error.message : String(error),
      }),
    );
    await handlerEntered;
    const disposal = registry.dispose();
    let disposalSettled = false;
    void disposal.then(
      () => {
        disposalSettled = true;
      },
      () => {
        disposalSettled = true;
      },
    );
    const secondRequest = fetchJson(page, "GET", "/api/slow-success");

    await expect(secondRequest).rejects.toThrow();
    await Promise.resolve();
    expect(disposalSettled).toBe(false);
    expect(page.isClosed()).toBe(false);
    releaseHandler?.();
    await handlerCompleted;
    await expect(disposal).rejects.toThrow(
      /request during teardown.*GET \/api\/slow-success/is,
    );
    const firstRequest = await firstRequestOutcome;
    if (firstRequest.status === "resolved") {
      expect(firstRequest.value).toEqual({ drained: true });
    } else {
      expect(firstRequest.message).toMatch(/Target page, context or browser has been closed/i);
    }
    expect(page.isClosed()).toBe(true);
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

  baseTest("accepts both inclusive edges of a bounded handler call range", async ({ page }) => {
    const minimumRegistry = await createRegistry(page, "bounded minimum");
    minimumRegistry.register({
      name: "minimum poll",
      method: "GET",
      path: "/api/minimum-poll",
      expectedCalls: { minimum: 2, maximum: 3 },
      handler: () => ({ json: { ok: true } }),
    });

    await expect(fetchJson(page, "GET", "/api/minimum-poll")).resolves.toEqual({ ok: true });
    await expect(fetchJson(page, "GET", "/api/minimum-poll")).resolves.toEqual({ ok: true });
    await expect(minimumRegistry.dispose()).resolves.toBeUndefined();

    const maximumRegistry = await createRegistry(page, "bounded maximum");
    maximumRegistry.register({
      name: "maximum poll",
      method: "GET",
      path: "/api/maximum-poll",
      expectedCalls: { minimum: 2, maximum: 3 },
      handler: () => ({ json: { ok: true } }),
    });

    for (let call = 0; call < 3; call += 1) {
      await expect(fetchJson(page, "GET", "/api/maximum-poll")).resolves.toEqual({ ok: true });
    }
    await expect(maximumRegistry.dispose()).resolves.toBeUndefined();
  });

  baseTest("rejects bounded handler underuse", async ({ page }) => {
    const registry = await createRegistry(page, "bounded underuse");
    registry.register({
      name: "required poll range",
      method: "GET",
      path: "/api/required-poll",
      expectedCalls: { minimum: 2, maximum: 3 },
      handler: () => ({ json: { ok: true } }),
    });

    await expect(fetchJson(page, "GET", "/api/required-poll")).resolves.toEqual({ ok: true });
    await expect(registry.dispose()).rejects.toThrow(
      /unused handler.*required poll range.*expected 2-3.*observed 1/is,
    );
  });

  baseTest("rejects bounded handler overuse without invoking it past the maximum", async ({
    page,
  }) => {
    const registry = await createRegistry(page, "bounded overuse");
    let invocations = 0;
    registry.register({
      name: "bounded poll",
      method: "GET",
      path: "/api/bounded-poll",
      expectedCalls: { minimum: 2, maximum: 3 },
      handler: () => {
        invocations += 1;
        return { json: { invocation: invocations } };
      },
    });

    for (let call = 1; call <= 3; call += 1) {
      await expect(fetchJson(page, "GET", "/api/bounded-poll")).resolves.toEqual({ invocation: call });
    }
    await expectFetchToFail(page, "GET", "/api/bounded-poll");
    expect(invocations).toBe(3);
    await expect(registry.dispose()).rejects.toThrow(
      /handler overuse.*bounded poll.*expected 2-3.*observed 4/is,
    );
  });

  baseTest("rejects invalid bounded handler call ranges", async ({ page }) => {
    const registry = await createRegistry(page, "invalid bounded calls");

    for (const [name, expectedCalls] of [
      ["zero minimum", { minimum: 0, maximum: 1 }],
      ["fractional maximum", { minimum: 1, maximum: 1.5 }],
      ["inverted range", { minimum: 3, maximum: 2 }],
    ] as const) {
      expect(() => {
        registry.register({
          name,
          method: "GET",
          path: `/api/${name.replace(" ", "-")}`,
          expectedCalls,
          handler: () => ({ json: { unreachable: true } }),
        });
      }).toThrow(/expectedCalls range requires positive integer minimum\/maximum with minimum <= maximum/i);
    }

    await expect(registry.dispose()).resolves.toBeUndefined();
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
      { text: "known benign browser message", url: "" },
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
      { text: "known benign browser message", url: "" },
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

  baseTest("does not allow matching console text from a different URL", async ({ page }) => {
    const registry = await createRegistry(page, "source-scoped benign console allowlist", [
      { text: "source-sensitive browser message", url: `${FRONTEND_ORIGIN}/expected.js` },
    ]);
    const consoleError = page.waitForEvent(
      "console",
      (message) => message.type() === "error" && message.text() === "source-sensitive browser message",
    );

    await page.evaluate(() => console.error("source-sensitive browser message"));
    await consoleError;

    await expect(registry.dispose()).rejects.toThrow(
      /console error.*source-sensitive browser message.*<no source URL>/is,
    );
  });

  baseTest("rejects an unused console error allowance", async ({ page }) => {
    const registry = await createRegistry(page, "unused benign console allowance", [
      { text: "required browser message", url: "" },
    ]);

    await expect(registry.dispose()).rejects.toThrow(
      /unused console error allowance.*required browser message.*expected 1.*observed 0/is,
    );
  });

  baseTest("rejects console error allowance overuse", async ({ page }) => {
    const registry = await createRegistry(page, "overused benign console allowance", [
      { text: "single browser message", url: "", expectedCalls: 1 },
    ]);

    await page.evaluate(() => console.error("single browser message"));
    await page.evaluate(() => console.error("single browser message"));

    await expect(registry.dispose()).rejects.toThrow(
      /console error allowance overuse.*single browser message.*expected 1.*observed 2/is,
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
