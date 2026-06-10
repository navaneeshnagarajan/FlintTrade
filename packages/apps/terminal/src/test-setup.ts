import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// ---------------------------------------------------------------------------
// 1. React test environment flag.
// ---------------------------------------------------------------------------
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", {
  writable: true,
  configurable: true,
  value: true,
});

// ---------------------------------------------------------------------------
// 2. DOM cleanup after every test.
//
// @testing-library/react auto-registers afterEach(cleanup) when the global
// afterEach is available. We re-register explicitly so that the cleanup runs
// reliably in --pool=forks --poolOptions.forks.singleFork mode where all test
// files share one jsdom process. Without this, residual renders from a
// previous file stay in the DOM and cause "Found multiple elements" failures.
// ---------------------------------------------------------------------------
afterEach(() => {
  cleanup();
  if (typeof globalThis.localStorage?.clear === "function") {
    globalThis.localStorage.clear();
  }
  if (typeof globalThis.sessionStorage?.clear === "function") {
    globalThis.sessionStorage.clear();
  }
});

// ---------------------------------------------------------------------------
// 3. window.matchMedia stub.
//
// jsdom does not implement window.matchMedia. Several components (themeStore,
// GlassCard, particles) call it during render. We define a stable stub once
// at setup time so it is always available regardless of test file order.
// Any test that needs different behaviour can override it locally with
// vi.spyOn(window, "matchMedia") or Object.defineProperty in its own
// beforeEach — the writable + configurable flags allow that.
// ---------------------------------------------------------------------------
Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// ---------------------------------------------------------------------------
// 3b. Element.prototype.scrollIntoView stub.
//
// jsdom does not implement scrollIntoView. HomeRoute's card-highlight effect
// calls it inside a requestAnimationFrame, which fires AFTER the triggering
// test finishes — so the TypeError escaped every test's error handling and
// surfaced as an "Unhandled Error" failing the whole run (all tests green,
// exit code 1). Stub it once here so any component may scroll safely.
// ---------------------------------------------------------------------------
if (typeof Element.prototype.scrollIntoView !== "function") {
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    writable: true,
    configurable: true,
    value: () => {},
  });
}

// ---------------------------------------------------------------------------
// 4. Web Storage globals.
//
// Newer Node runtimes expose their own Web Storage globals, but leave them
// unavailable unless Node is started with --localstorage-file. Vitest runs the
// app in jsdom, where window.localStorage/window.sessionStorage are the stores
// we actually want tests and Zustand persistence middleware to use. Rebind the
// unqualified globals so code that calls localStorage directly hits jsdom.
// ---------------------------------------------------------------------------
class TestStorage implements Storage {
  #items: Record<string, string> = {};

  get length(): number {
    return Object.keys(this.#items).length;
  }

  clear(): void {
    for (const key of Object.keys(this.#items)) {
      this.removeItem(key);
    }
  }

  getItem(key: string): string | null {
    return Object.hasOwn(this.#items, key) ? this.#items[key] : null;
  }

  key(index: number): string | null {
    return Object.keys(this.#items)[index] ?? null;
  }

  removeItem(key: string): void {
    delete this.#items[key];
    delete (this as unknown as Record<string, string>)[key];
  }

  setItem(key: string, value: string): void {
    this.#items[key] = String(value);
    if (!Object.hasOwn(this, key)) {
      Object.defineProperty(this, key, {
        configurable: true,
        enumerable: true,
        get: () => this.#items[key],
        set: (nextValue: string) => {
          this.#items[key] = String(nextValue);
        },
      });
    }
  }
}

Object.defineProperty(globalThis, "Storage", {
  writable: true,
  configurable: true,
  value: TestStorage,
});

const testLocalStorage = new TestStorage();
const testSessionStorage = new TestStorage();

for (const target of [globalThis, window]) {
  Object.defineProperty(target, "localStorage", {
    writable: true,
    configurable: true,
    value: testLocalStorage,
  });

  Object.defineProperty(target, "sessionStorage", {
    writable: true,
    configurable: true,
    value: testSessionStorage,
  });
}
