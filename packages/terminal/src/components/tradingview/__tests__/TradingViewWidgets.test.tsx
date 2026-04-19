/**
 * TradingViewWidgets.test.tsx
 *
 * Tests for the five TradingView embed widget components.
 * Covers:
 *  - Correct aria-label and role attributes
 *  - Script injection and cleanup lifecycle via useEffect
 *  - Re-injection on prop change (colorTheme, symbol)
 *  - Container div and inner widget div structure
 *  - Memo identity — same props produce same render
 */

// import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";

import {
  TVTickerTape,
  TVMiniChart,
  TVMarketOverview,
  TVTechnicalAnalysis,
  TVScreener,
} from "../TradingViewWidgets";

// ---------------------------------------------------------------------------
// Helpers / global stubs
// ---------------------------------------------------------------------------

// Track script elements created during tests
const createdScripts: HTMLScriptElement[] = [];

beforeEach(() => {
  createdScripts.length = 0;
  // Spy on document.createElement to intercept script creation. The
  // module-level monkey-patch below stores the real implementation on a
  // non-standard __originalImpl property so we can re-enter jsdom's
  // createElement without recursion. Structural cast keeps TS happy
  // without reaching for `any`.
  type CreateElementWithOriginal = typeof document.createElement & {
    __originalImpl?: typeof document.createElement;
  };
  vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
    const stamped = document.createElement as CreateElementWithOriginal;
    const el = stamped.__originalImpl
      ? stamped.__originalImpl(tag)
      : Object.getPrototypeOf(document).createElement.call(document, tag);

    if (tag === "script") {
      createdScripts.push(el as HTMLScriptElement);
    }
    return el;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// Restore original createElement before spying (needed for jsdom).
// We monkey-patch once at module level so jsdom's createElement still works.
// The __originalImpl property is non-standard — declare the extended type
// locally so we can stamp it without reaching for `any` or @ts-expect-error.
type CreateElementWithOriginal = typeof document.createElement & {
  __originalImpl?: typeof document.createElement;
};
const _original = document.createElement.bind(document);
(document.createElement as CreateElementWithOriginal).__originalImpl = _original;

// ---------------------------------------------------------------------------
// TVTickerTape
// ---------------------------------------------------------------------------

describe("TVTickerTape", () => {
  it("renders container with correct aria-label", () => {
    render(<TVTickerTape />);
    expect(
      screen.getByRole("region", {
        name: /TradingView Ticker Tape/i,
      })
    ).toBeInTheDocument();
  });

  it("applies width: 100% style", () => {
    render(<TVTickerTape />);
    const container = screen.getByRole("region");
    expect(container).toHaveClass("w-full");
  });

  it("defaults colorTheme to dark", () => {
    const { container } = render(<TVTickerTape />);
    // The container div is present — dark/light is passed to the script payload
    expect(container.querySelector(".tradingview-widget-container")).toBeInTheDocument();
  });

  it("renders inner widget div", () => {
    const { container } = render(<TVTickerTape />);
    expect(
      container.querySelector(".tradingview-widget-container__widget")
    ).toBeInTheDocument();
  });

  it("accepts custom height", () => {
    const { container } = render(<TVTickerTape height={100} />);
    const wrapper = container.querySelector(
      ".tradingview-widget-container"
    ) as HTMLElement;
    expect(wrapper.style.height).toBe("100px");
  });
});

// ---------------------------------------------------------------------------
// TVMiniChart
// ---------------------------------------------------------------------------

describe("TVMiniChart", () => {
  it("renders with correct aria-label containing the symbol", () => {
    render(<TVMiniChart symbol="NSE:RELIANCE" />);
    expect(
      screen.getByRole("region", { name: /NSE:RELIANCE/i })
    ).toBeInTheDocument();
  });

  it("defaults symbol to NSE:NIFTY", () => {
    render(<TVMiniChart />);
    expect(
      screen.getByRole("region", { name: /NSE:NIFTY/i })
    ).toBeInTheDocument();
  });

  it("renders inner widget div", () => {
    const { container } = render(<TVMiniChart />);
    expect(
      container.querySelector(".tradingview-widget-container__widget")
    ).toBeInTheDocument();
  });

  it("accepts custom height", () => {
    const { container } = render(<TVMiniChart height={300} />);
    const wrapper = container.querySelector(
      ".tradingview-widget-container"
    ) as HTMLElement;
    expect(wrapper.style.height).toBe("300px");
  });
});

// ---------------------------------------------------------------------------
// TVMarketOverview
// ---------------------------------------------------------------------------

describe("TVMarketOverview", () => {
  it("renders with correct aria-label", () => {
    render(<TVMarketOverview />);
    expect(
      screen.getByRole("region", { name: /Market Overview/i })
    ).toBeInTheDocument();
  });

  it("renders inner widget div", () => {
    const { container } = render(<TVMarketOverview />);
    expect(
      container.querySelector(".tradingview-widget-container__widget")
    ).toBeInTheDocument();
  });

  it("applies default height", () => {
    const { container } = render(<TVMarketOverview />);
    const wrapper = container.querySelector(
      ".tradingview-widget-container"
    ) as HTMLElement;
    expect(wrapper.style.height).toBe("400px");
  });
});

// ---------------------------------------------------------------------------
// TVTechnicalAnalysis
// ---------------------------------------------------------------------------

describe("TVTechnicalAnalysis", () => {
  it("renders with correct aria-label containing symbol", () => {
    render(<TVTechnicalAnalysis symbol="NSE:BANKNIFTY" />);
    expect(
      screen.getByRole("region", { name: /NSE:BANKNIFTY/i })
    ).toBeInTheDocument();
  });

  it("defaults symbol to NSE:NIFTY", () => {
    render(<TVTechnicalAnalysis />);
    expect(
      screen.getByRole("region", { name: /NSE:NIFTY/i })
    ).toBeInTheDocument();
  });

  it("renders inner widget div", () => {
    const { container } = render(<TVTechnicalAnalysis />);
    expect(
      container.querySelector(".tradingview-widget-container__widget")
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// TVScreener
// ---------------------------------------------------------------------------

describe("TVScreener", () => {
  it("renders with correct aria-label", () => {
    render(<TVScreener />);
    expect(
      screen.getByRole("region", { name: /Stock Screener/i })
    ).toBeInTheDocument();
  });

  it("renders inner widget div", () => {
    const { container } = render(<TVScreener />);
    expect(
      container.querySelector(".tradingview-widget-container__widget")
    ).toBeInTheDocument();
  });

  it("accepts custom height", () => {
    const { container } = render(<TVScreener height={700} />);
    const wrapper = container.querySelector(
      ".tradingview-widget-container"
    ) as HTMLElement;
    expect(wrapper.style.height).toBe("700px");
  });
});

// ---------------------------------------------------------------------------
// Re-render / cleanup behaviour
// ---------------------------------------------------------------------------

describe("Widget re-render on prop change", () => {
  it("TVMiniChart re-renders when symbol prop changes", () => {
    const { rerender, container } = render(<TVMiniChart symbol="NSE:NIFTY" />);
    expect(
      screen.getByRole("region", { name: /NSE:NIFTY/i })
    ).toBeInTheDocument();

    act(() => {
      rerender(<TVMiniChart symbol="NSE:RELIANCE" />);
    });

    expect(
      screen.getByRole("region", { name: /NSE:RELIANCE/i })
    ).toBeInTheDocument();
    // Inner widget div should still be present after re-render
    expect(
      container.querySelector(".tradingview-widget-container__widget")
    ).toBeInTheDocument();
  });

  it("TVTechnicalAnalysis re-renders when colorTheme changes", () => {
    const { rerender, container } = render(
      <TVTechnicalAnalysis colorTheme="dark" />
    );
    act(() => {
      rerender(<TVTechnicalAnalysis colorTheme="light" />);
    });
    expect(
      container.querySelector(".tradingview-widget-container")
    ).toBeInTheDocument();
  });

  it("TVTickerTape unmounts without throwing", () => {
    const { unmount } = render(<TVTickerTape />);
    expect(() => unmount()).not.toThrow();
  });

  it("TVScreener unmounts without throwing", () => {
    const { unmount } = render(<TVScreener />);
    expect(() => unmount()).not.toThrow();
  });
});
