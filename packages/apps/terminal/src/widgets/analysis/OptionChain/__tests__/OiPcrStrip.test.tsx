/**
 * FT-TRADE-012 — Option Chain OI profile + PCR strip.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import OiPcrStrip from "../OiPcrStrip";
import type { StrikeRow } from "../types";

const PROFILE_STRIKES: StrikeRow[] = [
  { strike: 25_000, call: { oi: 80_000 }, put: { oi: 95_000 } },
  { strike: 25_100, call: { oi: 120_000 }, put: { oi: 110_000 } },
];

describe("OiPcrStrip", () => {
  it("shows OI profile + PCR for the selected expiry and symbol", () => {
    render(
      <OiPcrStrip
        symbol="BANKNIFTY"
        expiry="2026-04-17"
        expiries={["2026-04-10", "2026-04-17"]}
        strikes={PROFILE_STRIKES}
        pcr={1.24}
        isExplore={false}
      />,
    );

    const strip = screen.getByTestId("oi-pcr-strip");
    expect(strip).toHaveAccessibleName("OI profile and PCR strip");
    expect(strip).toHaveTextContent("OI profile");
    expect(strip).toHaveTextContent("BANKNIFTY");
    expect(strip).toHaveTextContent("2026-04-17");
    expect(screen.getByRole("img", { name: "OI profile by strike" })).toBeInTheDocument();
    expect(strip.querySelectorAll('[data-oi-bar="ce"]')).toHaveLength(2);
    expect(strip.querySelector('[data-oi-bar="ce"][data-strike="25100"]')).toHaveAttribute(
      "data-oi",
      "120000",
    );
    expect(screen.getByText(/PCR 1\.24/)).toBeInTheDocument();
    expect(screen.getByText("Bullish")).toBeInTheDocument();
    expect(screen.queryByTestId("oi-pcr-sample-badge")).not.toBeInTheDocument();
  });

  it("badges Explore as Sample and does not invent live OI", () => {
    render(
      <OiPcrStrip
        symbol="NIFTY"
        expiry="2026-04-10"
        expiries={["2026-04-10"]}
        strikes={PROFILE_STRIKES}
        pcr={1.12}
        isExplore
      />,
    );

    const badge = screen.getByTestId("oi-pcr-sample-badge");
    expect(badge).toHaveTextContent("Sample");
    expect(badge).toHaveAccessibleName("Sample — not live open interest");
    expect(screen.queryByRole("status", { name: /^Live/ })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "OI profile by strike" })).toBeInTheDocument();
  });

  it("shows an honest empty for an empty expiry, not zeros-as-data", () => {
    render(
      <OiPcrStrip
        symbol="NIFTY"
        expiry="2026-04-10"
        expiries={["2026-04-10"]}
        strikes={[
          { strike: 25_000, call: { oi: 0 }, put: { oi: 0 } },
          { strike: 25_100, call: {}, put: {} },
        ]}
        pcr={0}
        isExplore
      />,
    );

    const strip = screen.getByTestId("oi-pcr-strip");
    expect(strip).toHaveTextContent("No OI for this expiry");
    expect(screen.getByTestId("oi-pcr-sample-badge")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "OI profile by strike" })).not.toBeInTheDocument();
    expect(strip.querySelector("[data-oi-bar]")).toBeNull();
    expect(screen.queryByText(/PCR/)).not.toBeInTheDocument();
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  });

  it("shows an honest empty when the symbol has no expiries", () => {
    render(
      <OiPcrStrip
        symbol="NIFTY"
        expiry={null}
        expiries={[]}
        strikes={[{ strike: 25_000, call: { oi: 0 }, put: { oi: 0 } }]}
        pcr={0}
        isExplore
      />,
    );

    expect(screen.getByTestId("oi-pcr-strip")).toHaveTextContent("No expiries for this symbol");
    expect(screen.queryByRole("img", { name: "OI profile by strike" })).not.toBeInTheDocument();
    expect(screen.queryByText(/PCR/)).not.toBeInTheDocument();
  });

  it("keeps omitted OI unavailable instead of painting a zero bar", () => {
    render(
      <OiPcrStrip
        symbol="NIFTY"
        expiry="2026-04-10"
        expiries={["2026-04-10"]}
        strikes={[
          { strike: 25_000, call: {}, put: { oi: 100 } },
          { strike: 25_100, call: { oi: 50 }, put: { oi: 0 } },
        ]}
        pcr={null}
        isExplore={false}
      />,
    );

    const missingCall = document.querySelector(
      '[data-oi-bar="ce"][data-strike="25000"]',
    );
    expect(missingCall).toHaveAttribute("data-oi", "unavailable");
    expect(document.querySelector('[data-oi-bar="pe"][data-strike="25100"]')).toHaveAttribute(
      "data-oi",
      "0",
    );
    expect(screen.queryByText(/PCR/)).not.toBeInTheDocument();
  });
});
