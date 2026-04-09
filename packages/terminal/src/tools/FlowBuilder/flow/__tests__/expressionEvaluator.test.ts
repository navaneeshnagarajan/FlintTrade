/**
 * expressionEvaluator.test.ts
 *
 * Tests for the safe {{variable}} expression evaluator used by Flow Builder.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  evaluateExpression,
  extractTokenPaths,
  validateExpression,
} from "../expressionEvaluator";
import type { ExpressionContext } from "../expressionEvaluator";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Fixed date used across tests that rely on Date. */
const FIXED_ISO = "2026-04-09T08:00:00.000Z";
const FIXED_DATE = "2026-04-09";
// Derived from FIXED_ISO so it stays correct if the date ever changes.
const FIXED_TIMESTAMP = new Date(FIXED_ISO).getTime();

// Use fake timers to pin Date to a deterministic point.
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(FIXED_ISO));
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// evaluateExpression
// ---------------------------------------------------------------------------

describe("evaluateExpression", () => {
  it("returns the template unchanged when there are no tokens", () => {
    expect(evaluateExpression("hello world", {})).toBe("hello world");
  });

  it("returns empty string for empty template", () => {
    expect(evaluateExpression("", {})).toBe("");
  });

  // ----- Upstream references -----

  it("resolves a top-level context key", () => {
    const ctx: ExpressionContext = { name: "NIFTY" };
    expect(evaluateExpression("Symbol: {{name}}", ctx)).toBe("Symbol: NIFTY");
  });

  it("resolves a nested dot-path (upstream.nodeName.output)", () => {
    const ctx: ExpressionContext = {
      upstream: {
        placeOrder: { symbol: "NIFTY", price: "22100" },
      },
    };
    expect(
      evaluateExpression(
        "Bought {{upstream.placeOrder.symbol}} at {{upstream.placeOrder.price}}",
        ctx
      )
    ).toBe("Bought NIFTY at 22100");
  });

  it("resolves three levels deep", () => {
    const ctx: ExpressionContext = {
      a: { b: { c: "deep" } },
    };
    expect(evaluateExpression("{{a.b.c}}", ctx)).toBe("deep");
  });

  it("converts numeric context values to string", () => {
    const ctx: ExpressionContext = { qty: 50 };
    expect(evaluateExpression("Qty: {{qty}}", ctx)).toBe("Qty: 50");
  });

  it("converts boolean context values to string", () => {
    const ctx: ExpressionContext = { filled: true };
    expect(evaluateExpression("Filled: {{filled}}", ctx)).toBe("Filled: true");
  });

  // ----- Unknown placeholders -----

  it("preserves unknown placeholder unchanged", () => {
    expect(evaluateExpression("Value: {{unknown.path}}", {})).toBe(
      "Value: {{unknown.path}}"
    );
  });

  it("preserves placeholder when parent key exists but child is missing", () => {
    const ctx: ExpressionContext = { upstream: { placeOrder: {} } };
    expect(evaluateExpression("{{upstream.placeOrder.missing}}", ctx)).toBe(
      "{{upstream.placeOrder.missing}}"
    );
  });

  it("preserves placeholder when context is empty", () => {
    expect(evaluateExpression("{{$env.MISSING}}", {})).toBe("{{$env.MISSING}}");
  });

  // ----- Built-in variables -----

  it("resolves {{$now}} to an ISO datetime string", () => {
    const result = evaluateExpression("Time: {{$now}}", {});
    expect(result).toBe(`Time: ${FIXED_ISO}`);
  });

  it("resolves {{$today}} to YYYY-MM-DD date", () => {
    const result = evaluateExpression("Date: {{$today}}", {});
    expect(result).toBe(`Date: ${FIXED_DATE}`);
  });

  it("resolves {{$timestamp}} to epoch milliseconds string", () => {
    const result = evaluateExpression("ts={{$timestamp}}", {});
    expect(result).toBe(`ts=${FIXED_TIMESTAMP}`);
  });

  it("resolves {{$env.KEY}} from $env sub-map", () => {
    const ctx: ExpressionContext = { $env: { SYMBOL: "BANKNIFTY" } };
    expect(evaluateExpression("{{$env.SYMBOL}}", ctx)).toBe("BANKNIFTY");
  });

  it("preserves {{$env.MISSING}} when key not in $env map", () => {
    const ctx: ExpressionContext = { $env: {} };
    expect(evaluateExpression("{{$env.MISSING}}", ctx)).toBe("{{$env.MISSING}}");
  });

  it("preserves {{$env.KEY}} when $env is absent from context", () => {
    expect(evaluateExpression("{{$env.KEY}}", {})).toBe("{{$env.KEY}}");
  });

  it("preserves unrecognised built-in variable", () => {
    expect(evaluateExpression("{{$unknown}}", {})).toBe("{{$unknown}}");
  });

  // ----- Multiple tokens -----

  it("resolves multiple tokens in one string", () => {
    const ctx: ExpressionContext = {
      upstream: { order: { symbol: "NIFTY", qty: "50" } },
    };
    const tpl = "Placed {{upstream.order.qty}} lots of {{upstream.order.symbol}}";
    expect(evaluateExpression(tpl, ctx)).toBe("Placed 50 lots of NIFTY");
  });

  it("handles adjacent tokens without whitespace", () => {
    const ctx: ExpressionContext = { a: "X", b: "Y" };
    expect(evaluateExpression("{{a}}{{b}}", ctx)).toBe("XY");
  });

  it("handles a mix of resolved and unresolved tokens", () => {
    const ctx: ExpressionContext = { name: "NIFTY" };
    const result = evaluateExpression("{{name}} at {{price}}", ctx);
    expect(result).toBe("NIFTY at {{price}}");
  });

  // ----- Safety — no eval / Function -----

  it("does not execute arbitrary code inside tokens", () => {
    // A token containing JS-like code must be preserved or resolved via context only.
    const ctx: ExpressionContext = {};
    const result = evaluateExpression("{{Math.random()}}", ctx);
    // Should NOT evaluate — either preserved or resolved to undefined (preserved).
    expect(result).toBe("{{Math.random()}}");
  });

  it("does not access window via tokens", () => {
    const ctx: ExpressionContext = {};
    const result = evaluateExpression("{{window.location}}", ctx);
    expect(result).toBe("{{window.location}}");
  });

  // ----- Edge cases -----

  it("handles whitespace inside token braces", () => {
    const ctx: ExpressionContext = { name: "NIFTY" };
    // Tokens with leading/trailing spaces inside braces should be trimmed.
    expect(evaluateExpression("{{ name }}", ctx)).toBe("NIFTY");
  });

  it("does not match single-brace {variable}", () => {
    const ctx: ExpressionContext = { name: "NIFTY" };
    expect(evaluateExpression("{name}", ctx)).toBe("{name}");
  });

  it("handles template with only whitespace", () => {
    expect(evaluateExpression("   ", {})).toBe("   ");
  });
});

// ---------------------------------------------------------------------------
// extractTokenPaths
// ---------------------------------------------------------------------------

describe("extractTokenPaths", () => {
  it("returns empty array when no tokens present", () => {
    expect(extractTokenPaths("hello world")).toEqual([]);
  });

  it("extracts a single token path", () => {
    expect(extractTokenPaths("{{upstream.order.symbol}}")).toEqual([
      "upstream.order.symbol",
    ]);
  });

  it("extracts multiple distinct token paths", () => {
    const paths = extractTokenPaths(
      "{{upstream.order.symbol}} at {{upstream.order.price}}"
    );
    expect(paths).toEqual([
      "upstream.order.symbol",
      "upstream.order.price",
    ]);
  });

  it("deduplicates repeated tokens", () => {
    const paths = extractTokenPaths("{{a.b}} and {{a.b}} again");
    expect(paths).toEqual(["a.b"]);
  });

  it("extracts built-in variable paths", () => {
    const paths = extractTokenPaths("{{$now}} {{$today}} {{$timestamp}}");
    expect(paths).toEqual(["$now", "$today", "$timestamp"]);
  });

  it("trims whitespace inside braces", () => {
    const paths = extractTokenPaths("{{ upstream.node.key }}");
    expect(paths).toEqual(["upstream.node.key"]);
  });

  it("can be called multiple times without state leakage", () => {
    const first = extractTokenPaths("{{a}}");
    const second = extractTokenPaths("{{b}}");
    expect(first).toEqual(["a"]);
    expect(second).toEqual(["b"]);
  });
});

// ---------------------------------------------------------------------------
// validateExpression
// ---------------------------------------------------------------------------

describe("validateExpression", () => {
  it("returns empty array when all tokens resolve", () => {
    const ctx: ExpressionContext = { upstream: { order: { symbol: "NIFTY" } } };
    const errors = validateExpression(
      "{{upstream.order.symbol}}",
      ctx
    );
    expect(errors).toEqual([]);
  });

  it("returns unresolved paths for missing tokens", () => {
    const errors = validateExpression("{{upstream.missing.value}}", {});
    expect(errors).toEqual(["upstream.missing.value"]);
  });

  it("treats built-in variables as always valid", () => {
    const errors = validateExpression("{{$now}} {{$today}} {{$timestamp}}", {});
    expect(errors).toEqual([]);
  });

  it("treats {{$env.*}} as always valid regardless of $env map content", () => {
    const errors = validateExpression("{{$env.SYMBOL}}", {});
    expect(errors).toEqual([]);
  });

  it("returns only unresolved paths in a mixed expression", () => {
    const ctx: ExpressionContext = {
      upstream: { order: { symbol: "NIFTY" } },
    };
    const errors = validateExpression(
      "{{upstream.order.symbol}} at {{upstream.order.price}}",
      ctx
    );
    expect(errors).toEqual(["upstream.order.price"]);
  });

  it("deduplicates errors for the same unresolved path used twice", () => {
    const errors = validateExpression("{{missing}} and {{missing}}", {});
    expect(errors).toEqual(["missing"]);
  });

  it("returns empty array when template has no tokens", () => {
    expect(validateExpression("plain text", {})).toEqual([]);
  });
});
