import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// ---------------------------------------------------------------------------
// 1. DOM cleanup after every test.
//
// @testing-library/react auto-registers afterEach(cleanup) when the global
// afterEach is available. We re-register explicitly so that the cleanup runs
// reliably in --pool=forks --poolOptions.forks.singleFork mode where all test
// files share one jsdom process. Without this, residual renders from a
// previous file stay in the DOM and cause "Found multiple elements" failures.
// ---------------------------------------------------------------------------
afterEach(() => {
  cleanup();
});

// ---------------------------------------------------------------------------
// 2. window.matchMedia stub.
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
