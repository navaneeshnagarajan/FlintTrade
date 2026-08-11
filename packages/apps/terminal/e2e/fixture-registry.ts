import {
  expect,
  test as baseTest,
  type ConsoleMessage,
  type Page,
  type Request,
  type Route,
} from "@playwright/test";

export { expect };

export type HttpMethod = "GET" | "POST" | "PUT" | "DELETE" | "PATCH" | "HEAD" | "OPTIONS";

export interface SyntheticResponse {
  status?: number;
  headers?: Record<string, string>;
  contentType?: string;
  body?: string;
  json?: unknown;
}

export interface SyntheticHandlerRegistration {
  name: string;
  method: HttpMethod;
  path: string;
  expectedCalls?: number;
  handler: (request: Request) => SyntheticResponse | Promise<SyntheticResponse>;
}

export interface SyntheticFixtureRegistryOptions {
  name: string;
  frontendOrigin?: string;
  benignConsoleErrors?: readonly BenignConsoleError[];
  closePageOnDispose?: boolean;
}

export interface BenignConsoleError {
  text: string;
  url: string;
  expectedCalls?: number;
}

export interface SyntheticFixtureRegistry {
  readonly name: string;
  register(registration: SyntheticHandlerRegistration): void;
  callCount(method: HttpMethod, path: string): number;
  assertSatisfied(): void;
  dispose(): Promise<void>;
}

interface RegisteredHandler extends SyntheticHandlerRegistration {
  expectedCalls: number;
  calls: number;
}

interface RegisteredBenignConsoleError extends BenignConsoleError {
  expectedCalls: number;
  calls: number;
}

interface CapturedFailure {
  kind:
    | "console error"
    | "handler error"
    | "handler overuse"
    | "method mismatch"
    | "page crash"
    | "pageerror"
    | "path mismatch"
    | "request during teardown"
    | "unexpected request"
    | "unhandled rejection";
  evidence: string;
}

const DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173";
const ROUTE_PATTERN = "**/*";
const UNHANDLED_REJECTION_PREFIX = "[flinttrade-e2e unhandled rejection] ";
const API_PATH_PREFIXES = ["/api", "/ft-api"] as const;

function isApiPath(pathname: string): boolean {
  return API_PATH_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function isFrontendResourceType(resourceType: string): boolean {
  return (
    resourceType === "document" ||
    resourceType === "font" ||
    resourceType === "image" ||
    resourceType === "manifest" ||
    resourceType === "script" ||
    resourceType === "stylesheet"
  );
}

function methodAndPath(method: string, path: string): string {
  return `${method} ${path}`;
}

function requestPath(request: Request): string {
  const url = new URL(request.url());
  return `${url.pathname}${url.search}`;
}

function installUnhandledRejectionCapture(prefix: string): void {
  const captureWindow = window as Window & {
    __flinttradeE2EUnhandledRejectionListener?: (event: PromiseRejectionEvent) => void;
  };
  const previousListener = captureWindow.__flinttradeE2EUnhandledRejectionListener;
  if (previousListener) {
    window.removeEventListener("unhandledrejection", previousListener);
  }

  const listener = (event: PromiseRejectionEvent): void => {
    event.preventDefault();
    const reason: unknown = event.reason;
    const message = reason instanceof Error ? reason.message : String(reason);
    console.error(`${prefix}${message}`);
  };
  captureWindow.__flinttradeE2EUnhandledRejectionListener = listener;
  window.addEventListener("unhandledrejection", listener);
}

function removeUnhandledRejectionCapture(): void {
  const captureWindow = window as Window & {
    __flinttradeE2EUnhandledRejectionListener?: (event: PromiseRejectionEvent) => void;
  };
  const listener = captureWindow.__flinttradeE2EUnhandledRejectionListener;
  if (listener) {
    window.removeEventListener("unhandledrejection", listener);
    delete captureWindow.__flinttradeE2EUnhandledRejectionListener;
  }
}

class FailClosedSyntheticFixtureRegistry implements SyntheticFixtureRegistry {
  readonly name: string;

  private readonly page: Page;
  private readonly frontendOrigin: string;
  private readonly benignConsoleErrors: RegisteredBenignConsoleError[];
  private readonly closePageOnDispose: boolean;
  private readonly handlers = new Map<string, RegisteredHandler>();
  private readonly failures: CapturedFailure[] = [];
  private readonly inFlightRouteHandlers = new Set<Promise<void>>();
  private disposalPromise: Promise<void> | undefined;
  private disposing = false;
  private disposed = false;

  private readonly routeHandler = (route: Route, request: Request): Promise<void> => {
    const operation = this.handleRoute(route, request);
    this.inFlightRouteHandlers.add(operation);
    void operation.then(
      () => this.inFlightRouteHandlers.delete(operation),
      () => this.inFlightRouteHandlers.delete(operation),
    );
    return operation;
  };

  private async handleRoute(route: Route, request: Request): Promise<void> {
    const url = new URL(request.url());
    if (!isApiPath(url.pathname) && this.isFrontendResource(request)) {
      await route.continue();
      return;
    }

    const method = request.method().toUpperCase();
    const path = requestPath(request);
    const key = methodAndPath(method, path);
    if (this.disposing) {
      this.failures.push({
        kind: "request during teardown",
        evidence: `request during teardown: received ${key}; aborted by the installed boundary`,
      });
      await this.abortRoute(route);
      return;
    }

    const registered = this.handlers.get(key);

    if (!registered) {
      this.captureRequestMismatch(method, path);
      await this.abortRoute(route);
      return;
    }

    registered.calls += 1;
    if (registered.calls > registered.expectedCalls) {
      this.failures.push({
        kind: "handler overuse",
        evidence:
          `handler overuse: "${registered.name}" ${key}; ` +
          `expected ${registered.expectedCalls} call(s), observed ${registered.calls}`,
      });
      await this.abortRoute(route);
      return;
    }

    try {
      const response = await registered.handler(request);
      await this.fulfil(route, response, registered);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      this.failures.push({
        kind: "handler error",
        evidence: `handler error: "${registered.name}" ${key}: ${message}`,
      });
      await this.abortRoute(route);
    }
  }

  private readonly pageErrorHandler = (error: Error): void => {
    this.failures.push({ kind: "pageerror", evidence: `pageerror: ${error.message}` });
  };

  private readonly pageCrashHandler = (): void => {
    this.failures.push({ kind: "page crash", evidence: "page crash: renderer crashed" });
  };

  private readonly consoleHandler = (message: ConsoleMessage): void => {
    if (message.type() !== "error") {
      return;
    }

    const text = message.text();
    if (text.startsWith(UNHANDLED_REJECTION_PREFIX)) {
      this.failures.push({
        kind: "unhandled rejection",
        evidence: `unhandled rejection: ${text.slice(UNHANDLED_REJECTION_PREFIX.length)}`,
      });
      return;
    }

    const url = message.location().url;
    const allowance = this.benignConsoleErrors.find(
      (candidate) => candidate.text === text && candidate.url === url,
    );
    if (allowance) {
      allowance.calls += 1;
      if (allowance.calls > allowance.expectedCalls) {
        this.failures.push({
          kind: "console error",
          evidence:
            `console error allowance overuse: ${text} at ${url || "<no source URL>"}; ` +
            `expected ${allowance.expectedCalls} occurrence(s), observed ${allowance.calls}`,
        });
      }
      return;
    }

    this.failures.push({
      kind: "console error",
      evidence: `console error: ${text} at ${url || "<no source URL>"}`,
    });
  };

  constructor(page: Page, options: SyntheticFixtureRegistryOptions) {
    const trimmedName = options.name.trim();
    if (!trimmedName) {
      throw new Error("A synthetic fixture registry requires a non-empty name");
    }

    this.page = page;
    this.name = trimmedName;
    this.frontendOrigin = new URL(options.frontendOrigin ?? DEFAULT_FRONTEND_ORIGIN).origin;
    this.closePageOnDispose = options.closePageOnDispose ?? false;
    this.benignConsoleErrors = (options.benignConsoleErrors ?? []).map((allowance) => {
      const expectedCalls = allowance.expectedCalls ?? 1;
      if (!allowance.text || !Number.isInteger(expectedCalls) || expectedCalls < 1) {
        throw new Error(
          `[fail-closed registry "${this.name}"] benign console errors require non-empty text ` +
            "and a positive integer expectedCalls",
        );
      }
      return { ...allowance, expectedCalls, calls: 0 };
    });
  }

  async install(): Promise<void> {
    await this.page.route(ROUTE_PATTERN, this.routeHandler);
    this.page.on("pageerror", this.pageErrorHandler);
    this.page.on("crash", this.pageCrashHandler);
    this.page.on("console", this.consoleHandler);
    await this.page.addInitScript(installUnhandledRejectionCapture, UNHANDLED_REJECTION_PREFIX);
    if (!this.page.isClosed()) {
      await this.page.evaluate(installUnhandledRejectionCapture, UNHANDLED_REJECTION_PREFIX);
    }
  }

  register(registration: SyntheticHandlerRegistration): void {
    this.assertActive();
    const name = registration.name.trim();
    if (!name) {
      throw new Error(`[fail-closed registry "${this.name}"] handler name must not be empty`);
    }
    if (!registration.path.startsWith("/") || registration.path.startsWith("//") || registration.path.includes("#")) {
      throw new Error(
        `[fail-closed registry "${this.name}"] handler "${name}" requires an exact root-relative path`,
      );
    }

    const expectedCalls = registration.expectedCalls ?? 1;
    if (!Number.isInteger(expectedCalls) || expectedCalls < 1) {
      throw new Error(
        `[fail-closed registry "${this.name}"] handler "${name}" expectedCalls must be a positive integer`,
      );
    }

    const key = methodAndPath(registration.method, registration.path);
    const duplicate = this.handlers.get(key);
    if (duplicate) {
      throw new Error(
        `[fail-closed registry "${this.name}"] duplicate handler for ${key}: ` +
          `"${duplicate.name}" is already registered; rejected "${name}"`,
      );
    }
    const duplicateName = [...this.handlers.values()].find((candidate) => candidate.name === name);
    if (duplicateName) {
      throw new Error(
        `[fail-closed registry "${this.name}"] duplicate handler name "${name}" for ` +
          `${methodAndPath(duplicateName.method, duplicateName.path)} and ${key}`,
      );
    }

    this.handlers.set(key, { ...registration, name, expectedCalls, calls: 0 });
  }

  callCount(method: HttpMethod, path: string): number {
    this.assertActive();
    return this.handlers.get(methodAndPath(method, path))?.calls ?? 0;
  }

  assertSatisfied(): void {
    this.assertActive();
    const error = this.buildAssertionError();
    if (error) {
      throw error;
    }
  }

  dispose(): Promise<void> {
    this.disposalPromise ??= this.disposeOnce();
    return this.disposalPromise;
  }

  private async disposeOnce(): Promise<void> {
    this.disposing = true;

    // Keep the boundary installed while owned handlers drain. Requests that
    // arrive in this interval are still intercepted, recorded, and aborted.
    await this.waitForInFlightRouteHandlers();

    if (!this.page.isClosed()) {
      if (this.closePageOnDispose) {
        // The automatic journey fixture owns its managed page. Close it while
        // the route remains installed so nothing can escape to Vite's proxy.
        await this.page.close({ runBeforeUnload: false });
      } else {
        // Explicit registries remain reusable on the same page after disposal.
        await this.page.unroute(ROUTE_PATTERN, this.routeHandler);
      }
    }
    await this.waitForInFlightRouteHandlers();

    const assertionError = this.buildAssertionError();
    this.disposed = true;

    this.page.off("pageerror", this.pageErrorHandler);
    this.page.off("crash", this.pageCrashHandler);
    this.page.off("console", this.consoleHandler);
    if (!this.page.isClosed()) {
      await this.page.evaluate(removeUnhandledRejectionCapture).catch(() => undefined);
    }
    this.handlers.clear();
    this.failures.length = 0;

    if (assertionError) {
      throw assertionError;
    }
  }

  private async waitForInFlightRouteHandlers(): Promise<void> {
    while (this.inFlightRouteHandlers.size > 0) {
      await Promise.allSettled([...this.inFlightRouteHandlers]);
    }
  }

  private async abortRoute(route: Route): Promise<void> {
    try {
      await route.abort("failed");
    } catch (error: unknown) {
      if (!this.page.isClosed()) {
        throw error;
      }
    }
  }

  private assertActive(): void {
    if (this.disposed || this.disposing) {
      throw new Error(`[fail-closed registry "${this.name}"] registry is disposed`);
    }
  }

  private buildAssertionError(): Error | undefined {
    const evidence = this.failures.map((failure) => failure.evidence);
    for (const handler of this.handlers.values()) {
      if (handler.calls !== handler.expectedCalls) {
        evidence.push(
          `unused handler or usage mismatch: "${handler.name}" ` +
            `${methodAndPath(handler.method, handler.path)}; ` +
            `expected ${handler.expectedCalls} call(s), observed ${handler.calls}`,
        );
      }
    }
    for (const allowance of this.benignConsoleErrors) {
      if (allowance.calls !== allowance.expectedCalls) {
        evidence.push(
          `unused console error allowance or usage mismatch: ${allowance.text} at ` +
            `${allowance.url || "<no source URL>"}; expected ${allowance.expectedCalls} ` +
            `occurrence(s), observed ${allowance.calls}`,
        );
      }
    }

    if (evidence.length === 0) {
      return undefined;
    }

    return new Error(
      `[fail-closed registry "${this.name}"] ${evidence.length} failure(s):\n` +
        evidence.map((item, index) => `${index + 1}. ${item}`).join("\n"),
    );
  }

  private captureRequestMismatch(method: string, path: string): void {
    const samePath = [...this.handlers.values()].filter((handler) => handler.path === path);
    if (samePath.length > 0) {
      const expected = samePath
        .map((handler) => `"${handler.name}" ${handler.method}`)
        .join(", ");
      this.failures.push({
        kind: "method mismatch",
        evidence: `method mismatch: received ${method} ${path}; same path expected ${expected}`,
      });
      return;
    }

    const sameMethod = [...this.handlers.values()].filter((handler) => handler.method === method);
    if (sameMethod.length > 0) {
      const expected = sameMethod
        .map((handler) => `"${handler.name}" ${handler.path}`)
        .join(", ");
      this.failures.push({
        kind: "path mismatch",
        evidence: `path mismatch: received ${method} ${path}; same method expected ${expected}`,
      });
      return;
    }

    this.failures.push({
      kind: "unexpected request",
      evidence: `unexpected request: received ${method} ${path}; no related handler is registered`,
    });
  }

  private isFrontendResource(request: Request): boolean {
    const url = new URL(request.url());
    const method = request.method().toUpperCase();
    return (
      url.origin === this.frontendOrigin &&
      (method === "GET" || method === "HEAD") &&
      isFrontendResourceType(request.resourceType())
    );
  }

  private async fulfil(
    route: Route,
    response: SyntheticResponse,
    handler: RegisteredHandler,
  ): Promise<void> {
    const hasBody = response.body !== undefined;
    const hasJson = Object.prototype.hasOwnProperty.call(response, "json");
    if (hasBody && hasJson) {
      throw new Error(`handler "${handler.name}" returned both body and json`);
    }

    const headers: Record<string, string> = {
      "access-control-allow-origin": "*",
      ...response.headers,
    };
    let body = response.body ?? "";
    let contentType = response.contentType;
    if (hasJson) {
      body = JSON.stringify(response.json ?? null);
      contentType = contentType ?? "application/json";
    }

    await route.fulfill({
      status: response.status ?? 200,
      headers,
      contentType,
      body,
    });
  }
}

export async function createSyntheticFixtureRegistry(
  page: Page,
  options: SyntheticFixtureRegistryOptions,
): Promise<SyntheticFixtureRegistry> {
  const registry = new FailClosedSyntheticFixtureRegistry(page, options);
  await registry.install();
  return registry;
}

type JourneyFixtures = {
  syntheticApi: SyntheticFixtureRegistry;
};

type JourneyOptions = {
  benignConsoleErrors: readonly BenignConsoleError[];
};

/**
 * Selected fail-closed product journey specs import `test` and `expect` from
 * this module, not directly from Playwright. `syntheticApi` is automatic:
 * teardown always asserts request usage and client errors, and closes the
 * managed page while the boundary is still installed. Product specs that still
 * import Playwright directly are not protected by this registry.
 */
export const test = baseTest.extend<JourneyFixtures & JourneyOptions>({
  benignConsoleErrors: [[], { option: true }],
  syntheticApi: [
    async ({ page, benignConsoleErrors }, use, testInfo) => {
      const configuredBaseUrl = testInfo.project.use.baseURL;
      const frontendOrigin =
        typeof configuredBaseUrl === "string" ? configuredBaseUrl : DEFAULT_FRONTEND_ORIGIN;
      const registry = await createSyntheticFixtureRegistry(page, {
        name: testInfo.titlePath.join(" > "),
        frontendOrigin,
        benignConsoleErrors,
        closePageOnDispose: true,
      });

      try {
        await use(registry);
      } finally {
        try {
          await registry.dispose();
        } catch (error: unknown) {
          const evidence = error instanceof Error ? error.message : String(error);
          await testInfo.attach("fail-closed-fixture-evidence", {
            body: evidence,
            contentType: "text/plain",
          });
          throw error;
        }
      }
    },
    { auto: true },
  ],
});
