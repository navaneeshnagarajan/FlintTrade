/**
 * Venue badges follow the symbols on the tape. The default marquee scrolls
 * NSE and BSE indices with MCX metals and energy, so an MCX-only badge fails.
 */

import { describe, expect, it } from "vitest";
import { createStore } from "jotai";
import { indicesSummaryAtom } from "@/atoms/marketAtoms";
import { deriveTickerVenueStrip, venueForTickerSymbol } from "../tickerVenues";

describe("deriveTickerVenueStrip", () => {
  it("derives NSE, BSE and MCX from the default tape, never MCX alone", () => {
    const store = createStore();
    const tape = store.get(indicesSummaryAtom);
    const strip = deriveTickerVenueStrip(tape, () => false);

    expect(tape.map((row) => row.name)).toEqual([
      "NIFTY 50",
      "SENSEX",
      "BANK NIFTY",
      "VIX",
      "GOLD",
      "SILVER",
      "CRUDEOIL",
      "NATGAS",
    ]);
    expect(strip).toMatchObject({
      kind: "badges",
      badges: [
        { venue: "NSE", label: "NSE closed" },
        { venue: "BSE", label: "BSE closed" },
        { venue: "MCX", label: "MCX closed" },
      ],
    });
    if (strip.kind === "badges") {
      expect(strip.badges.map((badge) => badge.venue)).toEqual(["NSE", "BSE", "MCX"]);
    }
  });

  it("adds NFO only when an F&O symbol feeds", () => {
    const strip = deriveTickerVenueStrip(
      [
        { name: "NIFTY 50", venue: "NSE" },
        { name: "NIFTY 24500 CE", exchange: "NFO" },
      ],
      (exchange) => exchange === "NFO",
    );

    expect(strip).toMatchObject({
      kind: "badges",
      badges: [
        { venue: "NSE", open: false, label: "NSE closed" },
        {
          venue: "NFO",
          open: true,
          label: "NFO open",
          title: "NFO session is open (09:15–15:40 IST)",
        },
      ],
    });
  });

  it("omits an empty tape and refuses a fake venue for unknown symbols", () => {
    expect(deriveTickerVenueStrip([], () => true)).toEqual({ kind: "empty" });
    expect(deriveTickerVenueStrip([{ name: "MYSTERY SCRIP" }], () => true)).toEqual({
      kind: "unavailable",
    });
    expect(venueForTickerSymbol({ name: "GOLD", exchange: "MCX" })).toBe("MCX");
    expect(venueForTickerSymbol({ name: "SENSEX" })).toBe("BSE");
    expect(venueForTickerSymbol({ name: "NFO:NIFTY24500CE" })).toBe("NFO");
  });
});
