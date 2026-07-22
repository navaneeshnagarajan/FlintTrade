import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

import type { BackendState, BootstrapSnapshot } from "./state";

const splashDirectory = path.resolve(import.meta.dirname, "..", "splash");
const html = readFileSync(path.join(splashDirectory, "index.html"), "utf8");
const css = readFileSync(path.join(splashDirectory, "splash.css"), "utf8");
const script = readFileSync(path.join(splashDirectory, "splash.js"), "utf8");

class FakeClassList {
  readonly values = new Set<string>();

  add(...names: string[]): void {
    for (const name of names) this.values.add(name);
  }

  contains(name: string): boolean {
    return this.values.has(name);
  }

  remove(...names: string[]): void {
    for (const name of names) this.values.delete(name);
  }
}

class FakeElement {
  readonly attributes = new Map<string, string>();
  readonly classList = new FakeClassList();
  readonly listeners = new Map<string, Array<() => void | Promise<void>>>();
  disabled = false;
  readonly style: Record<string, string> = {};
  textContent = "";

  addEventListener(event: string, listener: () => void | Promise<void>): void {
    const listeners = this.listeners.get(event) ?? [];
    listeners.push(listener);
    this.listeners.set(event, listeners);
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name: string): void {
    this.attributes.delete(name);
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  async dispatch(event: string): Promise<void> {
    for (const listener of this.listeners.get(event) ?? []) await listener();
    await flushPromises();
  }
}

function bootstrap(overrides: Partial<BootstrapSnapshot> = {}): BootstrapSnapshot {
  return {
    attempt: 1,
    failure: null,
    heartbeatAt: 100,
    message: "Preparing FlintTrade",
    phase: "preparing",
    progress: 0,
    status: "running",
    ...overrides,
  };
}

function backend(overrides: Partial<BackendState> = {}): BackendState {
  return { port: null, status: "stopped", url: null, ...overrides };
}

async function flushPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function deferred<T>() {
  let reject!: (error: unknown) => void;
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    reject = rejectPromise;
    resolve = resolvePromise;
  });
  return { promise, reject, resolve };
}

async function splashHarness(input: {
  backend?: BackendState;
  bootstrap?: BootstrapSnapshot;
  cancelResult?: boolean | Promise<boolean>;
  retryResult?: boolean | Promise<boolean>;
} = {}) {
  let now = 1_000;
  const elements = new Map<string, FakeElement>();
  for (const id of [
    "status",
    "phase",
    "progress",
    "progress-fill",
    "error",
    "error-message",
    "actions",
    "action-status",
    "retry",
    "cancel",
    "quit",
  ]) {
    elements.set(id, new FakeElement());
  }
  const body = new FakeElement();
  let bootstrapSnapshot = input.bootstrap ?? bootstrap();
  let backendSnapshot = input.backend ?? backend();
  let bootstrapEvent: ((snapshot: BootstrapSnapshot) => void) | null = null;
  let backendEvent: ((snapshot: BackendState) => void) | null = null;
  const unsubscribeBootstrap = vi.fn();
  const unsubscribeBackend = vi.fn();
  const pageListeners = new Map<string, Array<() => void>>();
  const intervals = new Map<number, Map<number, () => void | Promise<void>>>();
  let nextInterval = 1;
  const bridge = {
    cancelBootstrap: vi.fn(async () => await (input.cancelResult ?? true)),
    getBackendState: vi.fn(async () => backendSnapshot),
    getBootstrapSnapshot: vi.fn(async () => bootstrapSnapshot),
    onBackendEvent: vi.fn((listener: (snapshot: BackendState) => void) => {
      backendEvent = listener;
      return unsubscribeBackend;
    }),
    onBootstrapEvent: vi.fn((listener: (snapshot: BootstrapSnapshot) => void) => {
      bootstrapEvent = listener;
      return unsubscribeBootstrap;
    }),
    quitAfterBackendFailure: vi.fn(async () => undefined),
    retryBootstrap: vi.fn(async () => await (input.retryResult ?? true)),
  };
  const fakeWindow = {
    addEventListener(event: string, listener: () => void): void {
      const listeners = pageListeners.get(event) ?? [];
      listeners.push(listener);
      pageListeners.set(event, listeners);
    },
    flintDesktop: bridge,
  };
  const fakeDocument = {
    body,
    getElementById(id: string): FakeElement | null {
      return elements.get(id) ?? null;
    },
  };
  const setInterval = vi.fn((callback: () => void | Promise<void>, milliseconds: number) => {
    const id = nextInterval++;
    const callbacks = intervals.get(milliseconds) ?? new Map<number, () => void | Promise<void>>();
    callbacks.set(id, callback);
    intervals.set(milliseconds, callbacks);
    return id;
  });
  const clearInterval = vi.fn((id: number) => {
    for (const callbacks of intervals.values()) callbacks.delete(id);
  });

  vm.runInNewContext(script, {
    clearInterval,
    Date: { now: () => now },
    document: fakeDocument,
    setInterval,
    window: fakeWindow,
  });
  await flushPromises();

  return {
    advanceTime(milliseconds: number): void {
      now += milliseconds;
    },
    body,
    bridge,
    clearInterval,
    elements,
    emitBackend(snapshot: BackendState): void {
      backendEvent?.(snapshot);
    },
    emitBootstrap(snapshot: BootstrapSnapshot): void {
      bootstrapEvent?.(snapshot);
    },
    async pageEvent(event: string): Promise<void> {
      for (const listener of pageListeners.get(event) ?? []) listener();
      await flushPromises();
    },
    async runInterval(milliseconds: number): Promise<void> {
      for (const callback of intervals.get(milliseconds)?.values() ?? []) await callback();
      await flushPromises();
    },
    setBackend(snapshot: BackendState): void {
      backendSnapshot = snapshot;
    },
    setBootstrap(snapshot: BootstrapSnapshot): void {
      bootstrapSnapshot = snapshot;
    },
    setInterval,
    unsubscribeBackend,
    unsubscribeBootstrap,
  };
}

describe("packaged splash security policy", () => {
  it("loads only external local CSS and JavaScript under a restrictive CSP", () => {
    expect(html).toContain(
      "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'none'; connect-src 'none'; " +
        "font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    );
    expect(html).not.toContain("'unsafe-inline'");
    expect(html).not.toMatch(/<style(?:\s|>)/i);
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/i);
    expect(html).toContain('<link rel="stylesheet" href="./splash.css" />');
    expect(html).toContain('<script src="./splash.js"></script>');
    expect(css).toContain(".progress-fill");
  });

  it("uses only the named Electron bridge and retains no generic Tauri command escape hatch", () => {
    expect(script).toContain("window.flintDesktop");
    expect(script).toContain("bridge.getBootstrapSnapshot()");
    expect(script).toContain("bridge.onBootstrapEvent");
    expect(script).toContain("bridge.getBackendState()");
    expect(script).toContain("bridge.onBackendEvent");
    expect(script).toContain("bridge.retryBootstrap()");
    expect(script).toContain("bridge.cancelBootstrap()");
    expect(script).not.toContain("__TAURI");
    expect(script).not.toContain("ipcRenderer");
    expect(script).not.toMatch(/\.invoke\s*\(/);
    expect(script).not.toContain("bootstrap_status");
    expect(script).not.toContain("retry_bootstrap");
  });
});

describe("splash and recovery behaviour", () => {
  it("renders pushed progress immediately and still polls both ground-truth snapshots every 700 ms", async () => {
    const test = await splashHarness();

    test.emitBootstrap(bootstrap({ heartbeatAt: 200, message: "Cloning source", phase: "cloning-source", progress: 37 }));
    expect(test.elements.get("status")?.textContent).toBe("Cloning source");
    expect(test.elements.get("progress-fill")?.style.width).toBe("37%");

    test.setBootstrap(bootstrap({ heartbeatAt: 300, message: "Installing tools", phase: "installing-tools", progress: 51 }));
    test.setBackend(backend({ status: "starting" }));
    await test.runInterval(700);

    expect(test.bridge.getBootstrapSnapshot).toHaveBeenCalledTimes(2);
    expect(test.bridge.getBackendState).toHaveBeenCalledTimes(2);
    expect(test.elements.get("status")?.textContent).toBe("Installing tools");
    expect(test.elements.get("progress-fill")?.style.width).toBe("51%");
    expect(test.setInterval).toHaveBeenCalledWith(expect.any(Function), 700);
  });

  it("changes the visible heartbeat at the four-second bound during a long phase", async () => {
    const test = await splashHarness({
      bootstrap: bootstrap({ message: "Syncing Python dependencies", phase: "syncing-python", progress: null }),
    });
    const initial = test.elements.get("status")?.textContent;

    await test.runInterval(4_000);
    const firstHeartbeat = test.elements.get("status")?.textContent;
    await test.runInterval(4_000);
    const secondHeartbeat = test.elements.get("status")?.textContent;

    expect(initial).toBe("Syncing Python dependencies");
    expect(firstHeartbeat).toContain("still working · 4s");
    expect(secondHeartbeat).toContain("still working · 8s");
  });

  it("reports a stalled authoritative heartbeat even when snapshot polls keep succeeding", async () => {
    const unchanged = bootstrap({
      heartbeatAt: 200,
      message: "Syncing Python dependencies",
      phase: "syncing-python",
      progress: null,
    });
    const test = await splashHarness({ bootstrap: unchanged });

    for (let poll = 0; poll < 6; poll += 1) {
      test.advanceTime(700);
      test.setBootstrap({ ...unchanged });
      await test.runInterval(700);
    }

    expect(test.elements.get("phase")?.textContent).toBe("Startup response delayed");
    expect(test.elements.get("status")?.textContent).toContain("No recent startup progress was received");
    expect(test.elements.get("status")?.textContent).not.toContain("still working");
  });

  it("keeps a failure stable and rejects stale or same-attempt running publications", async () => {
    const test = await splashHarness({
      bootstrap: bootstrap({ attempt: 2, heartbeatAt: 200, message: "Building terminal", phase: "building-terminal" }),
    });

    test.emitBootstrap(bootstrap({
      attempt: 2,
      failure: "The terminal build failed. See the redacted desktop log.",
      heartbeatAt: 300,
      message: "The terminal build failed. See the redacted desktop log.",
      phase: "failed",
      status: "failed",
    }));
    test.emitBootstrap(bootstrap({ attempt: 1, heartbeatAt: 400, message: "Stale clone", phase: "cloning-source" }));
    test.emitBootstrap(bootstrap({ attempt: 2, heartbeatAt: 400, message: "Late worker", phase: "building-terminal" }));
    test.emitBootstrap(bootstrap({
      attempt: 2,
      failure: "A late failure tried to replace the stable surface.",
      heartbeatAt: 500,
      message: "A late failure tried to replace the stable surface.",
      phase: "failed",
      status: "failed",
    }));

    expect(test.body.classList.contains("errored")).toBe(true);
    expect(test.elements.get("error-message")?.textContent).toBe(
      "The terminal build failed. See the redacted desktop log.",
    );

    test.emitBootstrap(bootstrap({ attempt: 3, heartbeatAt: 500, message: "Retrying source build", phase: "preparing" }));
    expect(test.body.classList.contains("errored")).toBe(false);
    expect(test.elements.get("status")?.textContent).toBe("Retrying source build");
  });

  it("cancels a running attempt and does not clear a failed surface until main admits a newer retry", async () => {
    const running = await splashHarness();
    const cancel = running.elements.get("cancel");
    expect(cancel?.classList.contains("visible")).toBe(true);
    await cancel?.dispatch("click");
    expect(running.bridge.cancelBootstrap).toHaveBeenCalledOnce();

    const failed = await splashHarness({
      bootstrap: bootstrap({
        failure: "Bootstrap cancelled.",
        heartbeatAt: 200,
        message: "Bootstrap cancelled",
        phase: "cancelled",
        status: "failed",
      }),
    });
    const retry = failed.elements.get("retry");
    expect(retry?.classList.contains("visible")).toBe(true);
    await retry?.dispatch("click");

    expect(failed.bridge.retryBootstrap).toHaveBeenCalledOnce();
    expect(failed.body.classList.contains("errored")).toBe(true);
    expect(retry?.disabled).toBe(true);
    await failed.runInterval(700);
    expect(retry?.disabled).toBe(true);
    failed.emitBootstrap(bootstrap({ attempt: 2, heartbeatAt: 300, message: "Retrying bootstrap" }));
    expect(failed.body.classList.contains("errored")).toBe(false);
    expect(retry?.disabled).toBe(false);
  });

  it("replaces a provisional cancellation with a same-attempt containment failure", async () => {
    const test = await splashHarness({
      bootstrap: bootstrap({
        failure: "Bootstrap cancelled.",
        heartbeatAt: 200,
        message: "Bootstrap cancelled",
        phase: "cancelled",
        status: "failed",
      }),
    });
    expect(test.elements.get("action-status")?.textContent).toContain("Waiting for process settlement");
    expect(test.elements.get("action-status")?.textContent).not.toContain("safely");

    test.emitBootstrap(bootstrap({
      failure: "Command process containment could not be proven; restart is blocked.",
      heartbeatAt: 300,
      message: "Command process containment could not be proven; restart is blocked.",
      phase: "failed",
      status: "failed",
    }));

    expect(test.elements.get("error-message")?.textContent).toContain("containment could not be proven");
    expect(test.elements.get("action-status")?.textContent).toBe("");
  });

  it("re-enables Retry when main refuses a containment-latched retry", async () => {
    const test = await splashHarness({
      bootstrap: bootstrap({
        failure: "Command process containment could not be proven; restart is blocked.",
        heartbeatAt: 200,
        message: "Command process containment could not be proven; restart is blocked.",
        phase: "failed",
        status: "failed",
      }),
      retryResult: false,
    });

    await test.elements.get("retry")?.dispatch("click");

    expect(test.bridge.retryBootstrap).toHaveBeenCalledOnce();
    expect(test.elements.get("retry")?.disabled).toBe(false);
    expect(test.elements.get("action-status")?.textContent).toContain("restart did not complete");
  });

  it("keeps a retry's real failure when the admitted restart does not complete", async () => {
    const completion = deferred<boolean>();
    const test = await splashHarness({
      bootstrap: bootstrap({
        failure: "Initial bootstrap failed.",
        heartbeatAt: 200,
        message: "Initial bootstrap failed.",
        phase: "failed",
        status: "failed",
      }),
      retryResult: completion.promise,
    });

    const retrying = test.elements.get("retry")?.dispatch("click");
    await flushPromises();
    test.emitBootstrap(bootstrap({ attempt: 2, heartbeatAt: 300, message: "Retrying bootstrap" }));
    test.emitBootstrap(bootstrap({
      attempt: 2,
      failure: "The candidate terminal build failed.",
      heartbeatAt: 400,
      message: "The candidate terminal build failed.",
      phase: "failed",
      status: "failed",
    }));
    completion.resolve(false);
    await retrying;

    expect(test.elements.get("error-message")?.textContent).toBe("The candidate terminal build failed.");
    expect(test.elements.get("action-status")?.textContent).toContain("restart did not complete");
    expect(test.elements.get("action-status")?.textContent).not.toContain("another start is active");
  });

  it("clears provisional bootstrap-cancellation copy only after main confirms settlement", async () => {
    const cancellation = deferred<boolean>();
    const test = await splashHarness({ cancelResult: cancellation.promise });

    const cancelling = test.elements.get("cancel")?.dispatch("click");
    await flushPromises();
    test.emitBootstrap(bootstrap({
      failure: "Bootstrap cancelled.",
      heartbeatAt: 200,
      message: "Bootstrap cancelled",
      phase: "cancelled",
      status: "failed",
    }));
    expect(test.elements.get("action-status")?.textContent).toContain("Waiting for process settlement");
    expect(test.elements.get("retry")?.disabled).toBe(true);

    cancellation.resolve(true);
    await cancelling;
    expect(test.elements.get("action-status")?.textContent).toBe("");
    expect(test.elements.get("retry")?.disabled).toBe(false);
  });

  it("renders backend-start progress and gives a neutral failed-state Retry and Quit", async () => {
    const test = await splashHarness({
      backend: backend({ status: "starting" }),
      bootstrap: bootstrap({
        heartbeatAt: 200,
        message: "Source is ready",
        phase: "complete",
        progress: 100,
        status: "ready",
      }),
    });
    expect(test.elements.get("status")?.textContent).toBe("Starting the trading engine");
    expect(test.elements.get("progress")?.classList.contains("indeterminate")).toBe(true);

    test.emitBackend(backend({ status: "failed" }));
    expect(test.body.classList.contains("errored")).toBe(true);
    expect(test.elements.get("phase")?.textContent).toBe("Trading engine unavailable");
    expect(test.elements.get("error-message")?.textContent).toContain("could not start or became unavailable");
    expect(test.elements.get("error-message")?.textContent).not.toContain("stopped");
    expect(test.elements.get("retry")?.classList.contains("visible")).toBe(true);
    expect(test.elements.get("quit")?.classList.contains("visible")).toBe(true);

    await test.elements.get("quit")?.dispatch("click");
    expect(test.bridge.quitAfterBackendFailure).toHaveBeenCalledOnce();
    await test.elements.get("retry")?.dispatch("click");
    expect(test.bridge.retryBootstrap).not.toHaveBeenCalled();
    expect(test.body.classList.contains("errored")).toBe(true);
  });

  it("turns a cancelled backend readiness race into an actionable stopped surface", async () => {
    const test = await splashHarness({
      backend: backend({ status: "starting" }),
      bootstrap: bootstrap({
        heartbeatAt: 200,
        message: "Source is ready",
        phase: "complete",
        progress: 100,
        status: "ready",
      }),
    });

    await test.elements.get("cancel")?.dispatch("click");
    test.emitBackend(backend({ port: 51_000, status: "ready", url: "http://127.0.0.1:51000" }));
    test.emitBackend(backend({ status: "stopped" }));

    expect(test.body.classList.contains("errored")).toBe(true);
    expect(test.elements.get("phase")?.textContent).toBe("Trading engine stopped");
    expect(test.elements.get("error-message")?.textContent).toContain("startup was cancelled and stopped");
    expect(test.elements.get("action-status")?.textContent).toBe("");
    expect(test.elements.get("retry")?.classList.contains("visible")).toBe(true);
    expect(test.elements.get("quit")?.classList.contains("visible")).toBe(true);
  });

  it("clears confirmed cancellation copy when the bootstrap terminal event arrives later", async () => {
    const test = await splashHarness({ cancelResult: true });

    await test.elements.get("cancel")?.dispatch("click");
    expect(test.elements.get("action-status")?.textContent).toContain("Requesting cancellation");
    test.emitBootstrap(bootstrap({
      failure: "Bootstrap cancelled.",
      heartbeatAt: 200,
      message: "Bootstrap cancelled",
      phase: "cancelled",
      status: "failed",
    }));

    expect(test.elements.get("action-status")?.textContent).toBe("");
    expect(test.elements.get("retry")?.disabled).toBe(false);
  });

  it("keeps Retry and Quit blocked until a provisional backend cancellation settles", async () => {
    const cancellation = deferred<boolean>();
    const test = await splashHarness({
      backend: backend({ status: "starting" }),
      bootstrap: bootstrap({
        heartbeatAt: 200,
        message: "Source is ready",
        phase: "complete",
        progress: 100,
        status: "ready",
      }),
      cancelResult: cancellation.promise,
    });

    const cancelling = test.elements.get("cancel")?.dispatch("click");
    await flushPromises();
    test.emitBackend(backend({ status: "failed" }));

    expect(test.elements.get("error-message")?.textContent).toContain("failed while cancellation was settling");
    expect(test.elements.get("error-message")?.textContent).not.toContain("cancelled and stopped");
    expect(test.elements.get("retry")?.disabled).toBe(true);
    expect(test.elements.get("quit")?.disabled).toBe(true);
    await test.elements.get("retry")?.dispatch("click");
    await test.elements.get("quit")?.dispatch("click");
    expect(test.bridge.retryBootstrap).not.toHaveBeenCalled();
    expect(test.bridge.quitAfterBackendFailure).not.toHaveBeenCalled();

    cancellation.resolve(true);
    await cancelling;
    expect(test.elements.get("action-status")?.textContent).toBe("");
    expect(test.elements.get("retry")?.disabled).toBe(false);
    expect(test.elements.get("quit")?.disabled).toBe(false);
  });

  it("removes provisional cancellation copy when backend cancellation rejects", async () => {
    const cancellation = deferred<boolean>();
    const test = await splashHarness({
      backend: backend({ status: "starting" }),
      bootstrap: bootstrap({
        heartbeatAt: 200,
        message: "Source is ready",
        phase: "complete",
        progress: 100,
        status: "ready",
      }),
      cancelResult: cancellation.promise,
    });

    const cancelling = test.elements.get("cancel")?.dispatch("click");
    await flushPromises();
    test.emitBackend(backend({ status: "failed" }));
    cancellation.reject(new Error("private cancellation detail"));
    await cancelling;

    expect(test.elements.get("error-message")?.textContent).toContain("could not start or became unavailable");
    expect(test.elements.get("error-message")?.textContent).not.toContain("cancellation was settling");
    expect(test.elements.get("action-status")?.textContent).toContain("Cancellation could not be requested");
    expect(test.elements.get("action-status")?.textContent).not.toContain("private cancellation detail");
    expect(test.elements.get("retry")?.disabled).toBe(false);
    expect(test.elements.get("quit")?.disabled).toBe(false);
  });

  it("accepts an authoritative ready snapshot when a retry's starting push was missed", async () => {
    const test = await splashHarness({
      backend: backend({ status: "failed" }),
      bootstrap: bootstrap({
        heartbeatAt: 200,
        message: "Source is ready",
        phase: "complete",
        progress: 100,
        status: "ready",
      }),
    });

    await test.elements.get("retry")?.dispatch("click");
    test.emitBackend(backend({ port: 51_000, status: "ready", url: "http://127.0.0.1:51000" }));

    expect(test.body.classList.contains("errored")).toBe(false);
    expect(test.elements.get("status")?.textContent).toBe("Opening the FlintTrade terminal");
  });

  it("does not issue Quit while a Retry request is still in flight", async () => {
    const admission = deferred<boolean>();
    const test = await splashHarness({
      backend: backend({ status: "failed" }),
      bootstrap: bootstrap({
        heartbeatAt: 200,
        message: "Source is ready",
        phase: "complete",
        progress: 100,
        status: "ready",
      }),
      retryResult: admission.promise,
    });

    const retrying = test.elements.get("retry")?.dispatch("click");
    await flushPromises();
    expect(test.elements.get("quit")?.disabled).toBe(true);
    await test.elements.get("quit")?.dispatch("click");
    expect(test.bridge.quitAfterBackendFailure).not.toHaveBeenCalled();

    admission.resolve(false);
    await retrying;
    expect(test.elements.get("quit")?.disabled).toBe(false);
  });

  it("unsubscribes from bridge events and clears timers when the local page is discarded", async () => {
    const test = await splashHarness();

    await test.pageEvent("pagehide");

    expect(test.unsubscribeBootstrap).toHaveBeenCalledOnce();
    expect(test.unsubscribeBackend).toHaveBeenCalledOnce();
    expect(test.clearInterval).toHaveBeenCalledTimes(2);
  });
});
