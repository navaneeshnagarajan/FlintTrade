/**
 * Narrow rendered-source guard for Slice 1 canonical vocabulary.
 *
 * Pins exact user-visible strings reviewers flagged as browser-visible defects.
 * Internal identifiers (DemoBadge, demoSession, DEMO_HOLDINGS, SandboxControls,
 * /sandbox API paths, query keys, download filenames, testids) may remain.
 * Genuinely technical "sandboxed interpreter" wording may remain.
 */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const srcRoot = join(process.cwd(), "src");
const welcomePath = join(srcRoot, "routes/WelcomeRoute.tsx");
const miniChartPath = join(srcRoot, "routes/home/MiniChartCard.tsx");
const demoChoicePath = join(srcRoot, "components/demo/DemoChoice.tsx");
const demoDir = join(srcRoot, "components/demo");
const explorePath = join(srcRoot, "routes/ExploreRoute.tsx");
const learnPath = join(srcRoot, "routes/LearnRoute.tsx");
const sandboxControlsPath = join(srcRoot, "components/sandbox/SandboxControls.tsx");
const orderLadderPath = join(srcRoot, "widgets/trading/OrderLadder/OrderLadderWidget.tsx");
const pnlMonitorPath = join(srcRoot, "widgets/trading/PnLMonitor/PnLMonitorWidget.tsx");
const pivotPointsPath = join(srcRoot, "widgets/analysis/PivotPoints/PivotPointsWidget.tsx");

function read(path: string): string {
  return readFileSync(path, "utf8");
}

/** Strip block + line comments so identifiers in comments do not trip the guard. */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("Slice 1 canonical vocabulary — rendered source guard", () => {
  it("WelcomeRoute uses simulated testing (not sandbox testing)", () => {
    const src = stripComments(read(welcomePath));
    expect(src).toMatch(/simulated\s+testing/);
    expect(src).not.toMatch(/sandbox\s+testing/i);
  });

  it("MiniChartCard shows SAMPLE provenance and sample-data aria (not DEMO/demo data)", () => {
    const src = stripComments(read(miniChartPath));
    // Visible badge text must be Sample via ProvenanceBadge or literal Sample
    expect(src).toMatch(/ProvenanceBadge|label=\{?["']Sample["']\}?|>\s*Sample\s*</);
    expect(src).toMatch(/\(sample data\)/);
    // Forbidden browser-visible legacy strings
    expect(src).not.toMatch(/>\s*Demo\s*</);
    expect(src).not.toMatch(/\(demo data\)/i);
    expect(src).not.toMatch(/["'`]DEMO["'`]/);
  });

  it("DemoChoice is unreferenced and removed (or free of Demo Mode copy if revived)", () => {
    // Production import graph must not reference DemoChoice
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === "node_modules" || entry.name === "__tests__") continue;
          walk(full);
          continue;
        }
        if (!/\.(tsx?|jsx?)$/.test(entry.name)) continue;
        if (entry.name === "DemoChoice.tsx") continue;
        const text = read(full);
        if (
          /from\s+["'][^"']*DemoChoice["']/.test(text) ||
          /import\s*\(\s*["'][^"']*DemoChoice["']\s*\)/.test(text)
        ) {
          offenders.push(full.replace(srcRoot, "src"));
        }
      }
    };
    walk(srcRoot);
    expect(offenders).toEqual([]);

    if (!existsSync(demoChoicePath)) {
      // Preferred path: dead component deleted
      expect(existsSync(demoChoicePath)).toBe(false);
      return;
    }

    // If the file is kept for a future public-demo path, canonicalise visible copy
    const src = stripComments(read(demoChoicePath));
    expect(src).not.toMatch(/Demo Mode/);
    expect(src).not.toMatch(/Enter Demo Mode/);
    expect(src).toMatch(/Explore|Guided Tour/);
  });

  it("does not leave a DemoChoice.tsx sibling test expecting Demo Mode if component is gone", () => {
    const testPath = join(demoDir, "__tests__/DemoChoice.test.tsx");
    if (!existsSync(demoChoicePath) && existsSync(testPath)) {
      const testSrc = read(testPath);
      expect(testSrc).not.toMatch(/Demo Mode|Enter Demo Mode/);
    }
  });

  it("ExploreRoute tour uses guided learning and Practice workflows (not paper trading)", () => {
    const src = stripComments(read(explorePath));
    expect(src).toMatch(/guided learning and Practice workflows/i);
    expect(src).not.toMatch(/guided learning,\s*paper trading/i);
    expect(src).not.toMatch(/paper trading/i);
  });

  it("SandboxControls user-visible copy uses Practice terminology (not Paper/sandbox data)", () => {
    const src = stripComments(read(sandboxControlsPath));
    // Required canonical visible strings
    expect(src).toMatch(/Place Practice Order/);
    expect(src).toMatch(/aria-label=["']Place Practice [Oo]rder["']/);
    expect(src).toMatch(/Import Practice data/);
    expect(src).toMatch(/Reset all Practice data\?/);
    expect(src).toMatch(/Practice trades/);
    expect(src).toMatch(/Practice data has been reset/);
    // Forbidden user-visible phrases (errors, aria, titles, status)
    expect(src).not.toMatch(/Place Paper Order/);
    expect(src).not.toMatch(/Place paper order/);
    expect(src).not.toMatch(/Import sandbox data/i);
    expect(src).not.toMatch(/Reset all sandbox data/i);
    expect(src).not.toMatch(/sandbox trades/i);
    expect(src).not.toMatch(/Sandbox data has been reset/i);
    expect(src).not.toMatch(/Failed to reset sandbox data/i);
    expect(src).not.toMatch(/Failed to export sandbox data/i);
    expect(src).not.toMatch(/Failed to import sandbox data/i);
    expect(src).not.toMatch(/Failed to place paper order/i);
    // Internals that must remain
    expect(src).toMatch(/\/ft-api\/v1\/sandbox/);
    expect(src).toMatch(/\["sandboxStatus"\]/);
    expect(src).toMatch(/flinttrade-sandbox-/);
  });

  it("LearnRoute lesson/detail copy uses Practice analysis/review/workflows/mode", () => {
    const src = stripComments(read(learnPath));
    expect(src).toMatch(/Practice analysis/);
    expect(src).toMatch(/Practice review/);
    expect(src).toMatch(/Practice mode/);
    expect(src).toMatch(/Practice workflows/);
    // Forbidden rendered lesson phrasing
    expect(src).not.toMatch(/sandbox analysis/i);
    expect(src).not.toMatch(/sandbox review/i);
    expect(src).not.toMatch(/sandbox workflows/i);
    // "sandbox mode" as Flint copy (not product names like Dhan Sandbox)
    expect(src).not.toMatch(/sandbox mode/i);
    expect(src).not.toMatch(/in replay or sandbox/i);
  });

  it("LearnRoute nav label and paper-tab heading use Practice Trading (not Paper Trading)", () => {
    const src = stripComments(read(learnPath));
    // Internal tab id may remain "paper"; only rendered label/heading change
    expect(src).toMatch(/id:\s*["']paper["']/);
    expect(src).toMatch(/label:\s*["']Practice Trading["']/);
    expect(src).toMatch(/What is Practice Trading\?/);
    expect(src).not.toMatch(/label:\s*["']Paper Trading["']/);
    expect(src).not.toMatch(/What is Paper Trading\?/);
  });

  it("PortfolioOptimiser Practice title uses Practice data scope (not sandbox data scope)", () => {
    const path = join(srcRoot, "widgets/analysis/PortfolioOptimiser/PortfolioOptimiserWidget.tsx");
    const src = stripComments(read(path));
    expect(src).toMatch(/Practice data scope/);
    expect(src).not.toMatch(/sandbox data scope/i);
  });

  it("OrderLadder Explore a11y says sample data (not demo data)", () => {
    const src = stripComments(read(orderLadderPath));
    expect(src).toMatch(/Showing sample data/);
    expect(src).not.toMatch(/Showing demo data/);
    expect(src).toMatch(/>\s*Sample data\s*</);
    expect(src).not.toMatch(/>\s*Demo data\s*</);
  });

  it("PnLMonitor Practice a11y uses Practice account (not local sandbox)", () => {
    const src = stripComments(read(pnlMonitorPath));
    expect(src).toMatch(/Practice account/);
    expect(src).not.toMatch(/local sandbox/i);
    expect(src).not.toMatch(/sandbox account/i);
  });

  it("PivotPoints Practice a11y uses Practice history (not sandbox history)", () => {
    const src = stripComments(read(pivotPointsPath));
    expect(src).toMatch(/Practice history/);
    expect(src).not.toMatch(/sandbox history/i);
  });

  it("production TSX has no rendered Demo/Paper/sandbox-scope forbidden literals (comments/ids OK)", () => {
    // Deterministic full-tree scan of production .tsx (not tests), comment-stripped.
    // Forbidden rendered / a11y copy only:
    //   - badge/text "Demo data", titles "Demo data —", aria "(demo data)" / Showing demo data
    //   - "sandbox data scope" (PortfolioOptimiser title)
    //   - Learn nav/heading "Paper Trading" / "What is Paper Trading?"
    // Comments and internal identifiers (demoSession, DemoBadge, DEMO_*, id:"paper") may remain.
    const forbidden: RegExp[] = [
      />\s*Demo data\s*</,
      /·\s*Demo data/,
      /["'`]Demo data["'`]/,
      /["'`]Demo data\s*[—-]/,
      /Showing demo data/i,
      /\(demo data\)/i,
      /sandbox data scope/i,
      /label:\s*["']Paper Trading["']/,
      /What is Paper Trading\?/,
    ];
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) {
          if (
            entry.name === "node_modules" ||
            entry.name === "__tests__" ||
            entry.name === "e2e" ||
            entry.name === "dist"
          ) {
            continue;
          }
          walk(full);
          continue;
        }
        // Production TSX only — .ts modules can keep internal docs/comments freely
        if (!entry.name.endsWith(".tsx")) continue;
        if (/\.(test|spec)\.tsx$/.test(entry.name)) continue;
        const src = stripComments(read(full));
        for (const re of forbidden) {
          if (re.test(src)) {
            offenders.push(`${full.replace(srcRoot, "src")} ~ ${re}`);
          }
        }
      }
    };
    walk(srcRoot);
    expect(offenders).toEqual([]);
  });
});
