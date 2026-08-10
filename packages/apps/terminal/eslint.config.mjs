// ESLint flat config for the terminal - deliberately four rules and nothing else.
//
// WHY THIS EXISTS AT ALL
// ----------------------
// `tsc --noEmit` (npm run typecheck) covers types and unused bindings. It cannot
// see three other things, all of which type-check clean:
//
// 1. A React hook's *call position* and a dependency array's *closure* - runtime
//    semantics, covered by the two react-hooks rules below.
// 2. An *explicit* `any`, which `strict` permits by design because it is the
//    deliberate escape from the type system.
// 3. A suppression pragma, which is a comment.
//
// (2) and (3) used to live in `scripts/check-terminal-type-safety.py`, which
// matched regular expressions against comment-stripped source. That script has
// been deleted and its two checks reimplemented as AST rules in
// ./eslint-local-rules.mjs, because the regular expressions missed the most
// obvious spelling of the thing they banned - `type Payload = any` - along with
// unions, intersections, function-type return positions and `keyof any`. The
// full list, and why the parser has no such boundary, is in that file's header.
//
// Taking the hooks rules in particular:
//
//   * react-hooks/rules-of-hooks catches a hook called conditionally or inside a
//     callback/loop. That corrupts React's hook ordering and crashes at runtime,
//     and it type-checks perfectly.
//   * react-hooks/exhaustive-deps catches a dependency missing from a useEffect /
//     useMemo / useCallback array. The effect then closes over a stale value. In
//     71 widgets fed by a WebSocket price stream, a stale closure means acting on
//     a stale price - which is a trading bug, not a style nit.
//
// A previous eslint.config.mjs here referenced four plugins that were never in
// pnpm-lock.yaml, had no npm script and no CI job. It was deleted rather than
// left to imply a check that did not exist. This one is wired to `npm run lint`
// in this package and to the `node-core-tests` job in .github/workflows/test.yml,
// beside the TypeScript strict check.
//
// WHY NO BROAD RULE SETS
// ----------------------
// No eslint:recommended, no stylistic presets, no typescript-eslint rule sets.
// Ruff-equivalent churn across 1000+ files buys nothing here; correctness does.
// Adding a rule to this file should mean a class of runtime bug was found, or a
// house rule that no other gate in the repository can enforce.
//
// WHY @babel/eslint-parser AND NOT typescript-eslint
// --------------------------------------------------
// The usual choice for .ts/.tsx is @typescript-eslint/parser. It cannot be used
// in this repo: it loads the `typescript` package and calls ts.createSourceFile /
// ts.SyntaxKind, and TypeScript 7 (the native port, which this package pins)
// no longer exports that API - `require("typescript")` yields { version,
// versionMajorMinor } and nothing else. Its peer range stops at <6.1.0 for the
// same reason. @babel/eslint-parser parses TS and TSX syntax without the
// TypeScript compiler, and all four rules below are syntactic - none needs type
// information - so nothing is lost. Revisit when typescript-eslint ships a
// TypeScript 7 line.
//
// This is also why `local/no-explicit-any` exists here instead of
// `@typescript-eslint/no-explicit-any`: that package cannot be installed, but
// the node it keys off (TSAnyKeyword) is emitted by this parser too, so the
// check itself costs nothing beyond the rule in ./eslint-local-rules.mjs.
//
// @babel/core is already in the tree; the parser adds only @babel/eslint-parser
// and @babel/preset-typescript on top of eslint + eslint-plugin-react-hooks
// (which itself has zero runtime dependencies at 5.x).
//
// KNOWN LIMITATION OF THAT PARSER CHOICE - READ THIS BEFORE "FIXING" A REPORT
// --------------------------------------------------------------------------
// @babel/eslint-parser's scope analysis walks the members of an INLINE object
// type in expression position, so
//
//     const raw = (await res.json()) as { entries: LogEntry[] };
//
// inside a hook makes the rule believe the component's `entries` value was read,
// and it demands `entries` as a dependency. It is a phantom: adding the name to
// the array silences the report but changes when the hook re-runs, so DO NOT do
// that. Give the cast a named type instead -
//
//     interface RecentLogsResponse { entries: LogEntry[] }
//     const raw = (await res.json()) as RecentLogsResponse;
//
// - which clears the report and reads better anyway. Three sites hit this when
// the gate was introduced (AdminRoute x2, ChartWidget x1) and all three were
// converted to named types. Only inline type literals reachable from an
// expression are affected; parameter and variable annotations are not.

import reactHooks from "eslint-plugin-react-hooks";
import babelParser from "@babel/eslint-parser";
import localRules from "./eslint-local-rules.mjs";

export default [
  {
    // Build output, coverage and Playwright reports are generated, never authored.
    ignores: ["dist/**", "coverage/**", "playwright-report/**", "test-results/**"],
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks, local: localRules },
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        // There is no babel.config.* in this package - Vite drives the build via
        // esbuild/SWC - so the parser is configured inline instead.
        requireConfigFile: false,
        babelOptions: {
          babelrc: false,
          configFile: false,
          // preset-typescript enables the TSX syntax plugins for .tsx files and
          // the plain TS ones for .ts, keyed off the filename.
          presets: ["@babel/preset-typescript"],
        },
        ecmaFeatures: { jsx: true },
      },
      ecmaVersion: 2022,
      sourceType: "module",
    },
    linterOptions: {
      // A suppression that suppresses nothing is worse than none: it reads as
      // "this was considered and accepted" when nothing was.
      //
      // This was briefly "off", on the reasoning that the only reports would be
      // directives naming rules this config does not enable. That reasoning was
      // wrong, and measuring it is what showed the debt: of the nine unused
      // directives at the time, eight named `react-hooks/exhaustive-deps` - this
      // gate's own rule - and only one named a foreign rule. All nine were dead
      // and have been removed, so this can stay on and keep it that way.
      reportUnusedDisableDirectives: "error",
    },
    rules: {
      // Non-negotiable. A conditional hook call is a crash, not a preference.
      "react-hooks/rules-of-hooks": "error",

      // DEBT, 2026-07-30. When this gate was switched on the terminal already
      // carried 33 `eslint-disable-next-line react-hooks/exhaustive-deps`
      // comments, inert for as long as no ESLint ran here. Those 33 are
      // untouched. Turning the rule on surfaced 52 further violations, which
      // were fixed rather than silenced: 22 redundant dependencies removed, 16
      // genuinely missing ones added or restructured, 5 unstable values wrapped
      // in their own useMemo, and 3 phantom reports cleared by naming an inline
      // cast type (see the parser note above). 10 hooks needed a NEW directive
      // because the dependency is real but invisible to static analysis - a ref
      // read, a CSS-variable read keyed on the theme, a refetch counter, an
      // unmount teardown. Every one of those 10 carries a written reason on the
      // line above it.
      //
      // Then `reportUnusedDisableDirectives` was measured rather than assumed,
      // and 8 of the original 33 turned out to be suppressing nothing at all -
      // the code had drifted out from under them. Those 8 are gone, along with
      // one dead `require-yield` directive in a test. Total directives: 35, and
      // the option above now keeps that honest automatically.
      //
      // Retiring one means proving the effect is correct without it, a hook at a
      // time. It does not mean deleting the comment, adding a file-level or
      // rule-level disable, or downgrading this rule to "warn".
      "react-hooks/exhaustive-deps": "error",

      // The house rule `tsc` cannot enforce: explicit `any` is legal under
      // `strict`, so the compiler is silent on it by design. Clean across all
      // 1017 files at the time this replaced the regular-expression script, so
      // it starts at zero debt - see ./eslint-local-rules.mjs for the six forms
      // the predecessor let through.
      "local/no-explicit-any": "error",

      // @ts-ignore and @ts-nocheck outright; @ts-expect-error only with an issue
      // link, per the house rules. Also clean at zero findings today.
      "local/no-ts-suppression": "error",
    },
  },
  {
    // Playwright infrastructure is outside src/, but carries the same two
    // TypeScript safety rules. Hooks rules are irrelevant to non-React E2E code.
    files: ["e2e/**/*.ts", "playwright.config.ts", "playwright.infra.config.ts"],
    plugins: { local: localRules },
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        requireConfigFile: false,
        babelOptions: {
          babelrc: false,
          configFile: false,
          presets: ["@babel/preset-typescript"],
        },
      },
      ecmaVersion: 2022,
      sourceType: "module",
    },
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
    rules: {
      "local/no-explicit-any": "error",
      "local/no-ts-suppression": "error",
    },
  },
];
