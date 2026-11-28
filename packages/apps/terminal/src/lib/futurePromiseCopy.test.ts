/**
 * Terminal and design-system source must not promise features that do not exist.
 * Tests, e2e specs and fixtures are excluded: they may quote the old copy to assert it is gone.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const TERMINAL_SRC = join(process.cwd(), "src");
const DESIGN_SYSTEM_SRC = join(process.cwd(), "..", "..", "core", "design-system", "src");

const FUTURE_PROMISE = /coming[\s-]?soon|future update|in a future (?:update|release|version)/i;
const SOURCE_FILE = /\.(?:ts|tsx)$/;
const TEST_FILE = /\.(?:test|spec)\.(?:ts|tsx)$/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "__tests__" || entry.name === "node_modules" ? [] : sourceFiles(path);
    }
    return SOURCE_FILE.test(entry.name) && !TEST_FILE.test(entry.name) ? [path] : [];
  });
}

describe("future-promise copy guard", () => {
  it("scans the terminal and design-system sources", () => {
    expect(sourceFiles(TERMINAL_SRC).length).toBeGreaterThan(500);
    expect(sourceFiles(DESIGN_SYSTEM_SRC).length).toBeGreaterThan(10);
  });

  it("finds no coming-soon or future-update wording in non-test source", () => {
    const offenders = [...sourceFiles(TERMINAL_SRC), ...sourceFiles(DESIGN_SYSTEM_SRC)].flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .flatMap((line, index) =>
          FUTURE_PROMISE.test(line) ? [`${relative(process.cwd(), file)}:${index + 1}`] : [],
        ),
    );
    expect(offenders).toEqual([]);
  });
});
