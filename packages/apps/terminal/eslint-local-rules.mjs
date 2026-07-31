// Local ESLint rules for the terminal - the two house rules that neither
// `tsc --noEmit` nor eslint-plugin-react-hooks can enforce.
//
// WHY THESE ARE AST RULES AND NOT A REGULAR EXPRESSION
// ---------------------------------------------------
// `scripts/check-terminal-type-safety.py` used to enforce both by matching
// regular expressions against comment-stripped source. It was deleted in favour
// of this file because a regular expression cannot see a type position, and the
// gap was not academic - it missed the single most obvious way to write the
// thing it banned:
//
//     type Payload = any;          // missed
//     type Payload = string | any; // missed
//     type Fn = (x: number) => any;// missed
//     type Both = any & string;    // missed
//     export type P = any;         // missed
//     type Keys = keyof any;       // missed
//
// All six type-check clean under `strict`, so nothing else caught them either.
// The old patterns keyed off punctuation next to the word - `: any`, `as any`,
// `<any>`, `any[]` - and an alias body has none of that punctuation. Adding more
// patterns only moves the boundary; the parser removes it, because `any` in a
// type position is exactly one node type, TSAnyKeyword, wherever it appears.
//
// @babel/eslint-parser (already the parser for this config - see the note in
// eslint.config.mjs about typescript-eslint being unusable on TypeScript 7)
// emits TSAnyKeyword for every one of these forms, and ESLint traverses it via
// the parser's own visitor keys. Both rules below are purely syntactic; neither
// needs type information.
//
// ESCAPE HATCH, DELIBERATELY NOT POLICED
// --------------------------------------
// `// eslint-disable-next-line local/no-explicit-any` still works. That is on
// purpose: unlike `@ts-ignore` it names the rule it defeats, it is greppable,
// and `reportUnusedDisableDirectives` in eslint.config.mjs deletes it the moment
// it stops suppressing anything. A gate that cannot be escaped in the open gets
// escaped in the dark.

/** Matches the issue link the house rules require on a `@ts-expect-error`. */
const ISSUE_LINK = /https?:\/\/\S+/;

/**
 * Matches a suppression pragma only where TypeScript itself honours one: at the
 * start of a comment line, allowing for JSDoc `*` decoration.
 *
 * Anchoring here is what lets prose mention a pragma without tripping the gate -
 * `// never reach for @ts-ignore, narrow the type instead` is a comment about a
 * pragma, not a pragma. The regular-expression predecessor matched raw lines and
 * would have flagged that sentence, and this very file along with it.
 */
const PRAGMA = /^[\s*]*@ts-(ignore|expect-error|nocheck)\b/;

/**
 * Bans an explicit `any` in every type position.
 *
 * `strict` permits explicit `any` by design - it is the deliberate escape from
 * the type system, so the compiler has nothing to say about it. In a terminal
 * where a mistyped value can reach an order payload, that escape is the thing
 * worth gating.
 *
 * Caught, because all of them are a TSAnyKeyword: an alias body, a union or
 * intersection member, a parameter, a return type, a variable annotation, a
 * class property, an index signature, a type argument (`Array<any>`,
 * `Record<string, any>`, `Promise<any>`), a generic default (`<T = any>`), an
 * array shorthand (`any[]`), an assertion (`x as any`, `<any>x`), a catch-clause
 * annotation, and `keyof any` (write `PropertyKey`).
 *
 * Not caught, because it is not an explicit `any`: an *implicit* any, which is
 * `tsc --noEmit`'s job under `strict` and is already gated beside this one.
 */
const noExplicitAny = {
  meta: {
    type: "problem",
    docs: { description: "Ban an explicit `any` in any type position." },
    schema: [],
    messages: {
      explicitAny: "explicit `any` is banned - type it, or use `unknown` and narrow at the boundary",
    },
  },
  create(context) {
    return {
      TSAnyKeyword(node) {
        context.report({ node, messageId: "explicitAny" });
      },
    };
  },
};

/**
 * Bans `@ts-ignore` and `@ts-nocheck`, and requires an issue link on a
 * `@ts-expect-error`.
 *
 * Reads real comment tokens rather than raw text, so a pragma quoted inside a
 * string literal - a test fixture, an error message - is not a finding, and a
 * pragma inside a JSDoc block is.
 */
const noTsSuppression = {
  meta: {
    type: "problem",
    docs: { description: "Ban type-check suppression pragmas." },
    schema: [],
    messages: {
      tsIgnore: "@ts-ignore is never permitted; fix the type or narrow it",
      tsNocheck: "@ts-nocheck disables the whole file; type it instead",
      needsLink: "@ts-expect-error needs an issue link in the same comment",
    },
  },
  create(context) {
    const sourceCode = context.sourceCode ?? context.getSourceCode();
    return {
      Program() {
        for (const comment of sourceCode.getAllComments()) {
          for (const [offset, line] of comment.value.split("\n").entries()) {
            const match = PRAGMA.exec(line);
            if (match === null) {
              continue;
            }
            const kind = match[1];
            if (kind === "expect-error" && ISSUE_LINK.test(comment.value)) {
              continue;
            }
            const messageId = kind === "ignore" ? "tsIgnore" : kind === "nocheck" ? "tsNocheck" : "needsLink";
            // Report against the offending line inside the comment, not the
            // comment's first line, so a JSDoc block points at the pragma.
            const reportLine = comment.loc.start.line + offset;
            context.report({
              loc: { line: reportLine, column: offset === 0 ? comment.loc.start.column : 0 },
              messageId,
            });
          }
        }
      },
    };
  },
};

/** The rules, keyed by the name they carry under the `local/` plugin prefix. */
export const rules = {
  "no-explicit-any": noExplicitAny,
  "no-ts-suppression": noTsSuppression,
};

export default { rules };
