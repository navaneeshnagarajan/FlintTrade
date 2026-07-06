/**
 * formulaEngine.ts — safe arithmetic evaluator for user-defined watchlist
 * formula columns (W1).
 *
 * Users compose expressions over a fixed set of quote fields (e.g.
 * ``(high - low) / ltp * 100``). Evaluation is a hand-written tokeniser +
 * shunting-yard to RPN — NO ``eval``/``Function``, no property access, no
 * function calls — so a formula can only ever do arithmetic over the allowed
 * variables. Unknown identifiers, bad syntax and division-by-zero are rejected
 * at compile time / return null at eval time rather than throwing.
 */

import type { PartialQuote } from "./types";

/** Quote fields a formula may reference (identifier → extractor). */
export const FORMULA_FIELDS: Record<string, (q: PartialQuote) => number | null> = {
  ltp: (q) => q.ltp ?? q.close ?? null,
  open: (q) => q.open ?? null,
  high: (q) => q.high ?? null,
  low: (q) => q.low ?? null,
  close: (q) => q.close ?? null,
  prev_close: (q) => q.prev_close ?? q.close ?? null,
  volume: (q) => q.volume ?? null,
};

export const FORMULA_FIELD_NAMES = Object.keys(FORMULA_FIELDS);

type Token =
  | { kind: "num"; value: number }
  | { kind: "field"; name: string }
  | { kind: "op"; value: "+" | "-" | "*" | "/" | "u-" }
  | { kind: "lparen" }
  | { kind: "rparen" };

const OPERATORS = new Set(["+", "-", "*", "/"]);
const PRECEDENCE: Record<string, number> = { "u-": 4, "*": 3, "/": 3, "+": 2, "-": 2 };

export interface CompiledFormula {
  evaluate: (quote: PartialQuote | null) => number | null;
}

export type CompileResult =
  | { ok: true; formula: CompiledFormula }
  | { ok: false; error: string };

/** Tokenise an expression, or throw with a human-readable message. */
function tokenise(expr: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const isDigit = (c: string) => c >= "0" && c <= "9";
  const isIdentStart = (c: string) => /[a-zA-Z_]/.test(c);
  const isIdentChar = (c: string) => /[a-zA-Z0-9_]/.test(c);

  while (i < expr.length) {
    const c = expr[i];
    if (c === " " || c === "\t") { i++; continue; }
    if (isDigit(c) || (c === "." && isDigit(expr[i + 1] ?? ""))) {
      let num = "";
      while (i < expr.length && (isDigit(expr[i]) || expr[i] === ".")) num += expr[i++];
      const value = Number(num);
      if (Number.isNaN(value)) throw new Error(`Invalid number "${num}"`);
      tokens.push({ kind: "num", value });
      continue;
    }
    if (isIdentStart(c)) {
      let name = "";
      while (i < expr.length && isIdentChar(expr[i])) name += expr[i++];
      if (!(name in FORMULA_FIELDS)) {
        throw new Error(`Unknown field "${name}". Allowed: ${FORMULA_FIELD_NAMES.join(", ")}`);
      }
      tokens.push({ kind: "field", name });
      continue;
    }
    if (OPERATORS.has(c)) {
      // Unary minus: a '-' at the start or after another operator / '('.
      const prev = tokens[tokens.length - 1];
      const isUnary = c === "-" && (!prev || prev.kind === "op" || prev.kind === "lparen");
      tokens.push({ kind: "op", value: isUnary ? "u-" : (c as "+" | "-" | "*" | "/") });
      i++;
      continue;
    }
    if (c === "(") { tokens.push({ kind: "lparen" }); i++; continue; }
    if (c === ")") { tokens.push({ kind: "rparen" }); i++; continue; }
    throw new Error(`Unexpected character "${c}"`);
  }
  return tokens;
}

/** Shunting-yard: infix tokens → RPN output queue. */
function toRpn(tokens: Token[]): Token[] {
  const output: Token[] = [];
  const stack: Token[] = [];
  for (const tok of tokens) {
    if (tok.kind === "num" || tok.kind === "field") {
      output.push(tok);
    } else if (tok.kind === "op") {
      while (
        stack.length > 0 &&
        stack[stack.length - 1].kind === "op" &&
        PRECEDENCE[(stack[stack.length - 1] as { value: string }).value] >= PRECEDENCE[tok.value]
      ) {
        output.push(stack.pop() as Token);
      }
      stack.push(tok);
    } else if (tok.kind === "lparen") {
      stack.push(tok);
    } else if (tok.kind === "rparen") {
      let matched = false;
      while (stack.length > 0) {
        const top = stack.pop() as Token;
        if (top.kind === "lparen") { matched = true; break; }
        output.push(top);
      }
      if (!matched) throw new Error("Unbalanced parentheses");
    }
  }
  while (stack.length > 0) {
    const top = stack.pop() as Token;
    if (top.kind === "lparen" || top.kind === "rparen") throw new Error("Unbalanced parentheses");
    output.push(top);
  }
  return output;
}

/**
 * Symbolically check RPN operand arity without evaluating values, so a
 * structurally-valid formula that merely divides by zero on a probe is not
 * rejected at compile time. Returns true when the stack never underflows and
 * ends at exactly one value.
 */
function isArityValid(rpn: Token[]): boolean {
  let depth = 0;
  for (const tok of rpn) {
    if (tok.kind === "num" || tok.kind === "field") {
      depth += 1;
    } else if (tok.kind === "op") {
      if (tok.value === "u-") {
        if (depth < 1) return false;
      } else {
        if (depth < 2) return false;
        depth -= 1;
      }
    }
  }
  return depth === 1;
}

/** Evaluate an RPN token list against a quote; null on any missing field / div0. */
function evalRpn(rpn: Token[], quote: PartialQuote): number | null {
  const stack: number[] = [];
  for (const tok of rpn) {
    if (tok.kind === "num") {
      stack.push(tok.value);
    } else if (tok.kind === "field") {
      const v = FORMULA_FIELDS[tok.name](quote);
      if (v == null || Number.isNaN(v)) return null;
      stack.push(v);
    } else if (tok.kind === "op") {
      if (tok.value === "u-") {
        if (stack.length < 1) return null;
        stack.push(-(stack.pop() as number));
        continue;
      }
      if (stack.length < 2) return null;
      const b = stack.pop() as number;
      const a = stack.pop() as number;
      let r: number;
      switch (tok.value) {
        case "+": r = a + b; break;
        case "-": r = a - b; break;
        case "*": r = a * b; break;
        case "/": if (b === 0) return null; r = a / b; break;
        default: return null;
      }
      stack.push(r);
    }
  }
  if (stack.length !== 1) return null;
  const result = stack[0];
  return Number.isFinite(result) ? result : null;
}

/**
 * Compile a formula expression. Validates syntax and field names up front so a
 * bad expression is reported once, not on every row render.
 */
export function compileFormula(expression: string): CompileResult {
  const trimmed = expression.trim();
  if (!trimmed) return { ok: false, error: "Formula is empty" };
  try {
    const tokens = tokenise(trimmed);
    if (!tokens.some((t) => t.kind === "field")) {
      return { ok: false, error: "Formula must reference at least one field" };
    }
    const rpn = toRpn(tokens);
    // Structural arity check (does not reject a valid formula that merely
    // divides by zero on a probe — that returns null at eval time).
    if (!isArityValid(rpn)) {
      return { ok: false, error: "Formula could not be evaluated (check operators)" };
    }
    return {
      ok: true,
      formula: { evaluate: (quote) => (quote ? evalRpn(rpn, quote) : null) },
    };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "Invalid formula" };
  }
}
