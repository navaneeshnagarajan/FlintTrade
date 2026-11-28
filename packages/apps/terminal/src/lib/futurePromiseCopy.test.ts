/**
 * Terminal and design-system source must not promise features that do not exist.
 * It also keeps internal service names and the funded-unlock wording out of UI copy.
 * Tests, e2e specs and fixtures are excluded: they may quote the old copy to assert it is gone.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const TERMINAL_SRC = join(process.cwd(), "src");
const DESIGN_SYSTEM_SRC = join(process.cwd(), "..", "..", "core", "design-system", "src");

const FUTURE_PROMISE = /coming[\s-]?soon|future update|in a future (?:update|release|version)/i;
const INTERNAL_SERVICE_NAME = /\bAI backend\b|FT Python server/i;
const FUNDED_UNLOCK = /funded unlock/i;
const FLINTTRADE_BACKEND = /FlintTrade backend/i;
const COMMENT_LINE = /^\s*(?:\/\/|\/\*|\*)/;

/**
 * Non-comment lines that still say "FlintTrade backend", per file. The count may
 * only go down: a file missing from this list must have none, and a listed file
 * may not gain more. The screens that name Core (Admin, System metrics) are
 * absent on purpose.
 */
const FLINTTRADE_BACKEND_BASELINE: Record<string, number> = {
  "components/account/BrokerConnect.tsx": 1,
  "lib/brokerOrdersApi.ts": 1,
  "lib/operatorIncident.ts": 3,
  "lib/setupAccountApi.ts": 13,
  "routes/SetupAccountRoute.tsx": 2,
  "routes/SetupBackendGate.tsx": 3,
  "routes/invest/tabs/StocksTab.tsx": 1,
  "routes/invest/tabs/TaxTab.tsx": 1,
  "services/advisorChat.ts": 1,
  "tools/Settings/ConnectionStatusPanel.tsx": 1,
  "tools/Settings/SecuritySection.tsx": 1,
  "tools/Settings/VersionInventory.tsx": 1,
  "tools/Settings/WatchlistManagerPanel.tsx": 1,
  "widgets/analysis/VWAPBands/VWAPBandsWidget.tsx": 1,
  "widgets/utility/News/NewsWidget.tsx": 3,
};
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

  function offenders(pattern: RegExp): string[] {
    return [...sourceFiles(TERMINAL_SRC), ...sourceFiles(DESIGN_SYSTEM_SRC)].flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .flatMap((line, index) => (pattern.test(line) ? [`${relative(process.cwd(), file)}:${index + 1}`] : [])),
    );
  }

  it("finds no coming-soon or future-update wording in non-test source", () => {
    expect(offenders(FUTURE_PROMISE)).toEqual([]);
  });

  it("names the local service Core, never the AI backend or the FT Python server", () => {
    expect(offenders(INTERNAL_SERVICE_NAME)).toEqual([]);
    expect("AI Backends").not.toMatch(INTERNAL_SERVICE_NAME);
    expect("AI backend").toMatch(INTERNAL_SERVICE_NAME);
  });

  it("keeps the funded-unlock wording out of non-test source", () => {
    expect(offenders(FUNDED_UNLOCK)).toEqual([]);
    expect("Live read only until funded unlock.").toMatch(FUNDED_UNLOCK);
  });

  it("does not add new UI copy that calls the local service the FlintTrade backend", () => {
    const counts: Record<string, number> = {};
    for (const file of sourceFiles(TERMINAL_SRC)) {
      const hits = readFileSync(file, "utf8")
        .split("\n")
        .filter((line) => FLINTTRADE_BACKEND.test(line) && !COMMENT_LINE.test(line)).length;
      if (hits > 0) counts[relative(TERMINAL_SRC, file)] = hits;
    }
    for (const [file, hits] of Object.entries(counts)) {
      expect(hits, `${file} says "FlintTrade backend" in UI copy; name Core instead`).toBeLessThanOrEqual(
        FLINTTRADE_BACKEND_BASELINE[file] ?? 0,
      );
    }
    expect(counts["routes/AdminRoute.tsx"]).toBeUndefined();
    expect(counts["routes/admin/SystemMetricsPanel.tsx"]).toBeUndefined();
  });
});
