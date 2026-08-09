import { describe, expect, it } from "vitest";

import {
  appendAISymbolContext,
  normaliseAISymbolContext,
  parseAISymbolContext,
} from "@/lib/aiSymbolContext";

describe("aiSymbolContext", () => {
  it("accepts real NSE symbols that contain ampersands such as M&M", () => {
    expect(
      normaliseAISymbolContext({ symbol: "m&m", exchange: "nse", source: "palette" }),
    ).toEqual({
      symbol: "M&M",
      exchange: "NSE",
      source: "palette",
    });
  });

  it("rejects partial, invented, or non-palette context", () => {
    expect(normaliseAISymbolContext({ symbol: "RELIANCE", exchange: "NSE" })).toBeNull();
    expect(
      normaliseAISymbolContext({ symbol: "RELIANCE", exchange: "NSE", source: "url" }),
    ).toBeNull();
    expect(
      normaliseAISymbolContext({ symbol: "BAD SPACE", exchange: "NSE", source: "palette" }),
    ).toBeNull();
  });

  it("parses only an unambiguous URL triplet", () => {
    const valid = new URLSearchParams("symbol=M%26M&exchange=NSE&source=palette");
    expect(parseAISymbolContext(valid)).toEqual({
      symbol: "M&M",
      exchange: "NSE",
      source: "palette",
    });

    const ambiguous = new URLSearchParams("symbol=RELIANCE&symbol=TCS&exchange=NSE&source=palette");
    expect(parseAISymbolContext(ambiguous)).toBeNull();
  });

  it("appends context only to /ai and preserves existing query/hash", () => {
    expect(
      appendAISymbolContext("/trade?tab=orders#top", {
        symbol: "M&M",
        exchange: "NSE",
        source: "palette",
      }),
    ).toBe("/trade?tab=orders#top");

    expect(
      appendAISymbolContext("/ai?tab=chat#panel", {
        symbol: "M&M",
        exchange: "NSE",
        source: "palette",
      }),
    ).toBe("/ai?tab=chat&symbol=M%26M&exchange=NSE&source=palette#panel");
  });
});
