/**
 * Coverage for the terminal's two local ESLint rules.
 *
 * These replaced `scripts/check-terminal-type-safety.py`, which enforced the
 * same two house rules with regular expressions over comment-stripped source.
 * Six spellings of an explicit `any` slipped past it - including the most
 * obvious one, `type Payload = any` - because an alias body carries none of the
 * punctuation (`: any`, `as any`, `<any>`, `any[]`) the patterns keyed off, and
 * all six type-check clean under `strict`.
 *
 * The `MISSED BY THE OLD REGEX` cases below are that gap, pinned. Each one fails
 * if the rule is removed, downgraded or reimplemented with pattern matching.
 */
import { Linter } from "eslint";
import babelParser from "@babel/eslint-parser";
import { describe, expect, it } from "vitest";

import localRules from "../../eslint-local-rules.mjs";
import eslintConfig from "../../eslint.config.mjs";

const linter = new Linter();

const CONFIG = {
  // Flat config resolves per filename, so without a matching `files` entry
  // `Linter.verify` reports "No matching configuration found" and runs nothing.
  files: ["**/*.ts", "**/*.tsx"],
  plugins: { local: localRules },
  languageOptions: {
    parser: babelParser,
    parserOptions: {
      requireConfigFile: false,
      babelOptions: { babelrc: false, configFile: false, presets: ["@babel/preset-typescript"] },
      ecmaFeatures: { jsx: true },
    },
    ecmaVersion: 2022,
    sourceType: "module",
  },
  rules: {
    "local/no-explicit-any": "error",
    "local/no-ts-suppression": "error",
  },
} as const;

/**
 * Lint one snippet and return the rule id reported on each line.
 *
 * @param code - The TypeScript source to lint.
 * @returns One `"<line>:<ruleId>"` entry per report, in source order.
 */
function lint(code: string): string[] {
  const messages = linter.verify(code, CONFIG as unknown as Linter.Config, "sample.ts");
  const fatal = messages.filter((message) => message.fatal);
  if (fatal.length > 0) {
    throw new Error(`snippet failed to parse: ${fatal.map((message) => message.message).join("; ")}`);
  }
  return messages.map((message) => `${message.line}:${message.ruleId ?? "unknown"}`);
}

/**
 * Count the reports from one rule.
 *
 * @param code - The TypeScript source to lint.
 * @param ruleId - The rule whose reports should be counted.
 * @returns How many times that rule fired.
 */
function countFor(code: string, ruleId: string): number {
  return lint(code).filter((entry) => entry.endsWith(`:${ruleId}`)).length;
}

describe("local/no-explicit-any", () => {
  // The regression set. Every one of these was green under the regular
  // expressions in scripts/check-terminal-type-safety.py.
  describe("MISSED BY THE OLD REGEX", () => {
    it.each([
      ["bare alias body", "type Payload = any;"],
      ["exported alias body, no semicolon", "export type Payload = any"],
      ["union, any last", "type Payload = string | any;"],
      ["union, any first", "type Payload = any | string;"],
      ["intersection", "type Payload = any & string;"],
      ["function-type return position", "type Fn = (x: number) => any;"],
      ["keyof any", "type Keys = keyof any;"],
    ])("flags %s", (_name, code) => {
      expect(countFor(code, "local/no-explicit-any")).toBe(1);
    });

    it("flags a union member on a continuation line, at that line", () => {
      const code = ["type Payload =", "  | string", "  | any;"].join("\n");
      expect(lint(code)).toEqual(["3:local/no-explicit-any"]);
    });
  });

  // These the old script did catch. Pinned so the parser rewrite is a strict
  // superset rather than a trade.
  describe("still caught", () => {
    it.each([
      ["parameter annotation", "function f(p: any): void {}"],
      ["return annotation", "function f(): any { return 1; }"],
      ["variable annotation", "const x: any = 1;"],
      ["definite-assignment annotation", "let x!: any;"],
      ["interface member", "interface I { field: any }"],
      ["index signature", "type I = { readonly [k: string]: any };"],
      ["array shorthand", "type A = any[];"],
      ["type argument", "type A = Array<any>;"],
      ["nested type argument", "type A = Record<string, any>;"],
      ["promise type argument", "type A = Promise<any>;"],
      ["generic default", "function f<T = any>(t: T): T { return t; }"],
      ["as assertion", "const x = y as any;"],
      ["angle-bracket assertion", "const x = <any>y;"],
      ["catch clause", "try { f(); } catch (e: any) {}"],
      ["callback parameter", "declare function f(cb: (v: any) => void): void;"],
    ])("flags %s", (_name, code) => {
      expect(countFor(code, "local/no-explicit-any")).toBe(1);
    });

    it("flags each occurrence on a line with two", () => {
      expect(countFor("class C { prop: any = 1; method(): any { return 1 } }", "local/no-explicit-any")).toBe(2);
    });
  });

  describe("does not fire on", () => {
    it.each([
      ["the word in prose", "// Direct broker mode: any unified BrokerAccount\nconst x = 1;"],
      ["the word in a string literal", 'throw new Error("as any");'],
      ["the word in a template literal", "const m = `cast to any here`;"],
      ["an identifier containing the substring", "const anyone = 1; const company: string = 'x';"],
      ["unknown", "const x: unknown = 1;"],
      ["a property named any", "const o = { any: 1 }; const v = o.any;"],
    ])("%s", (_name, code) => {
      expect(countFor(code, "local/no-explicit-any")).toBe(0);
    });
  });
});

describe("local/no-ts-suppression", () => {
  it.each([
    ["@ts-ignore in a line comment", "// @ts-ignore\nconst x = 1;"],
    ["@ts-ignore in a block comment", "/* @ts-ignore */\nconst x = 1;"],
    ["@ts-nocheck", "// @ts-nocheck\nconst x = 1;"],
    ["@ts-expect-error with no issue link", "// @ts-expect-error it is broken\nconst x = 1;"],
  ])("flags %s", (_name, code) => {
    expect(countFor(code, "local/no-ts-suppression")).toBe(1);
  });

  it("allows @ts-expect-error carrying an issue link", () => {
    const code = "// @ts-expect-error upstream bug https://github.com/example/repo/issues/1\nconst x = 1;";
    expect(countFor(code, "local/no-ts-suppression")).toBe(0);
  });

  it("still flags @ts-ignore even with a link, since it is never permitted", () => {
    const code = "// @ts-ignore see https://github.com/example/repo/issues/1\nconst x = 1;";
    expect(countFor(code, "local/no-ts-suppression")).toBe(1);
  });

  it("reports the pragma's own line inside a JSDoc block", () => {
    const code = ["/**", " * Some prose.", " * @ts-ignore", " */", "const x = 1;"].join("\n");
    expect(lint(code)).toEqual(["3:local/no-ts-suppression"]);
  });

  // The predecessor matched raw lines, so it flagged any mention of a pragma -
  // including a comment warning people off one, and its own source file.
  it.each([
    ["prose mentioning a pragma", "// never reach for @ts-ignore, narrow the type instead\nconst x = 1;"],
    ["a pragma quoted in a string", 'const sample = "// @ts-ignore";'],
  ])("does not fire on %s", (_name, code) => {
    expect(countFor(code, "local/no-ts-suppression")).toBe(0);
  });
});

describe("gate wiring", () => {
  // Without this, deleting either rule from eslint.config.mjs would leave every
  // test above green while the gate itself stopped running - the exact failure
  // that got the previous eslint.config.mjs deleted.
  const terminalBlock = (eslintConfig as { files?: string[]; rules?: Record<string, string> }[]).find((entry) =>
    entry.files?.includes("src/**/*.{ts,tsx}"),
  );

  it("applies to the terminal source tree", () => {
    expect(terminalBlock).toBeDefined();
  });

  it.each(["local/no-explicit-any", "local/no-ts-suppression"])("enables %s as an error", (ruleId) => {
    expect(terminalBlock?.rules?.[ruleId]).toBe("error");
  });
});
