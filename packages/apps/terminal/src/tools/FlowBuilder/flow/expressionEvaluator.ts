/**
 * expressionEvaluator.ts — Safe expression evaluator for Flow Builder node configs.
 *
 * Pattern: expression sandboxing (inspired by n8n).
 *
 * Supports {{variable}} interpolation WITHOUT eval() or Function() constructor.
 * All resolution is pure string replacement via a whitelist context object.
 *
 * Supported syntax:
 *   {{upstream.nodeName.output}}   — reference an upstream node's output value
 *   {{$now}}                       — current ISO datetime string (e.g. "2026-04-09T14:30:00.000Z")
 *   {{$today}}                     — current date in YYYY-MM-DD format
 *   {{$timestamp}}                 — Unix epoch milliseconds as string
 *   {{$env.KEY}}                   — look up a key from the env sub-map in context
 *
 * Unknown placeholders are preserved as-is (no throw).
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * A flat or nested context object provided to evaluateExpression.
 * Keys are dot-notation segments; nested values are accessed via path traversal.
 *
 * Example:
 *   {
 *     upstream: { placeOrder: { symbol: "NIFTY", price: "22000" } },
 *     $env: { SYMBOL: "BANKNIFTY" }
 *   }
 */
export type ExpressionContext = Record<string, unknown>;

/** Result of parsing a single {{...}} token. */
interface ParsedToken {
  /** Full match including braces, e.g. "{{upstream.foo.bar}}" */
  raw: string;
  /** Inner path without braces, e.g. "upstream.foo.bar" */
  path: string;
}

// ---------------------------------------------------------------------------
// Token regex
// ---------------------------------------------------------------------------

// Matches {{...}} where content is non-greedy and cannot contain newlines.
// Captured group 1 = inner path (trimmed later).
const TOKEN_REGEX = /\{\{([^}\r\n]+?)\}\}/g;

// ---------------------------------------------------------------------------
// Built-in variable resolver
// ---------------------------------------------------------------------------

/**
 * Returns the value for a built-in variable (those starting with $).
 * Returns undefined if the name is not recognised as a built-in.
 */
function resolveBuiltin(path: string, context: ExpressionContext): string | undefined {
  if (path === "$now") {
    return new Date().toISOString();
  }
  if (path === "$today") {
    const d = new Date();
    // Use ISO date in UTC to keep it deterministic; IST offset is handled externally.
    return d.toISOString().slice(0, 10);
  }
  if (path === "$timestamp") {
    return String(Date.now());
  }
  if (path.startsWith("$env.")) {
    const key = path.slice(5); // strip "$env."
    const envMap = context["$env"];
    if (envMap !== null && typeof envMap === "object" && !Array.isArray(envMap)) {
      const val = (envMap as Record<string, unknown>)[key];
      if (val !== undefined) {
        return String(val);
      }
    }
    return undefined;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Dot-path resolver
// ---------------------------------------------------------------------------

/**
 * Resolves a dot-separated path against an object.
 * Returns undefined if any segment is missing.
 * Throws nothing — callers should treat undefined as "preserve placeholder".
 */
function resolvePath(obj: unknown, segments: string[]): unknown {
  let current: unknown = obj;
  for (const seg of segments) {
    if (current === null || current === undefined) return undefined;
    if (typeof current !== "object" || Array.isArray(current)) return undefined;
    current = (current as Record<string, unknown>)[seg];
  }
  return current;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Evaluates a template string containing {{variable}} placeholders.
 *
 * @param template  - The template string, e.g. "Symbol: {{upstream.order.symbol}}"
 * @param context   - Resolution context. Supports nested objects and built-ins.
 * @returns         - Resolved string. Unknown placeholders are preserved unchanged.
 *
 * @example
 * evaluateExpression("Bought {{upstream.order.symbol}} at {{upstream.order.price}}", {
 *   upstream: { order: { symbol: "NIFTY", price: "22100" } }
 * });
 * // => "Bought NIFTY at 22100"
 *
 * @example
 * evaluateExpression("Time: {{$now}}", {});
 * // => "Time: 2026-04-09T14:30:00.000Z"
 */
export function evaluateExpression(
  template: string,
  context: ExpressionContext
): string {
  if (!template.includes("{{")) {
    // Fast path — no tokens present.
    return template;
  }

  return template.replace(TOKEN_REGEX, (_fullMatch, rawPath: string) => {
    const path = rawPath.trim();

    // 1. Built-in variables ($now, $today, $timestamp, $env.*)
    if (path.startsWith("$")) {
      const resolved = resolveBuiltin(path, context);
      return resolved !== undefined ? resolved : `{{${path}}}`;
    }

    // 2. Context path resolution (dot-separated)
    const segments = path.split(".");
    const resolved = resolvePath(context, segments);

    if (resolved === undefined || resolved === null) {
      // Unknown placeholder — preserve as-is
      return `{{${path}}}`;
    }

    return String(resolved);
  });
}

/**
 * Extracts all {{...}} token paths from a template string.
 * Useful for building autocomplete suggestion lists.
 *
 * @param template - The template string to scan.
 * @returns        - Deduplicated array of inner path strings.
 */
export function extractTokenPaths(template: string): string[] {
  const tokens: ParsedToken[] = [];
  let match: RegExpExecArray | null;

  // Reset lastIndex before each scan (shared regex instance).
  TOKEN_REGEX.lastIndex = 0;

  while ((match = TOKEN_REGEX.exec(template)) !== null) {
    tokens.push({ raw: match[0], path: match[1].trim() });
  }

  // Reset again after use.
  TOKEN_REGEX.lastIndex = 0;

  const seen = new Set<string>();
  const unique: string[] = [];
  for (const t of tokens) {
    if (!seen.has(t.path)) {
      seen.add(t.path);
      unique.push(t.path);
    }
  }
  return unique;
}

/**
 * Validates that all {{...}} tokens in a template are resolvable given the
 * provided context (built-ins are always considered valid).
 *
 * @returns Array of unresolved placeholder paths (empty = all resolved).
 */
export function validateExpression(
  template: string,
  context: ExpressionContext
): string[] {
  const paths = extractTokenPaths(template);
  const unresolved: string[] = [];

  for (const path of paths) {
    if (path.startsWith("$")) {
      // Built-in — always valid (values are runtime-generated).
      continue;
    }
    const segments = path.split(".");
    const resolved = resolvePath(context, segments);
    if (resolved === undefined || resolved === null) {
      unresolved.push(path);
    }
  }

  return unresolved;
}
