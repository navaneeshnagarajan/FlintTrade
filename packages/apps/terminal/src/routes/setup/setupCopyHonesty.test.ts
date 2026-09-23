/**
 * Setup / Mode Select / Broker Connect must not name a calendar day as a
 * product path. Chrome stays Practice, Connected (read), Live, and API smoke.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

/** Weekday names and pack-calendar labels. Identifiers such as isMondayReadBroker do not match. */
const PACK_DAY =
  /\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|pack[ -]?day/gi;

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

/**
 * A weekday token is operator copy when it is not a code identifier.
 * `monday` variables and `isMondayReadBroker` stay; "Monday path" does not.
 */
function isOperatorCopy(source: string, index: number, length: number): boolean {
  const prev = source[index - 1] ?? "";
  const next = source[index + length] ?? "";
  if (prev === "." || prev === "{" || /[\w$]/.test(prev)) return false;
  if (/[\w$]/.test(next) || next === "(") return false;
  let cursor = index + length;
  while (source[cursor] === " " || source[cursor] === "\t") cursor += 1;
  const after = source[cursor] ?? "";
  return !["=", ",", ":", ";", ")", "]", "&", "|", "?"].includes(after);
}

function productionFiles(): string[] {
  const setupDir = join(SRC, "routes", "setup");
  const setupSources = readdirSync(setupDir)
    .filter((name) => name.endsWith(".tsx") && !name.endsWith(".test.tsx"))
    .map((name) => join(setupDir, name));
  return [
    join(SRC, "routes", "ModeSelectRoute.tsx"),
    join(SRC, "routes", "SetupAccountRoute.tsx"),
    join(SRC, "components", "account", "BrokerConnect.tsx"),
    ...setupSources,
  ];
}

describe("Setup chrome copy", () => {
  it("does not name a calendar day as a product path", () => {
    const offenders: string[] = [];
    for (const file of productionFiles()) {
      const stripped = stripComments(readFileSync(file, "utf8"));
      for (const match of stripped.matchAll(new RegExp(PACK_DAY.source, "gi"))) {
        const index = match.index ?? 0;
        if (!isOperatorCopy(stripped, index, match[0].length)) continue;
        const line = stripped.slice(0, index).split("\n").length;
        const rel = file.slice(SRC.length + 1).replace(/\\/g, "/");
        offenders.push(`${rel}:${line}: ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
