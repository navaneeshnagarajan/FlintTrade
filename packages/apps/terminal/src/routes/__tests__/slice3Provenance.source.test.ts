import { readFileSync, readdirSync, existsSync } from "fs";
import { join, relative } from "path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();
// Vitest cwd is packages/apps/terminal — climb to monorepo root for docs.
const REPO_ROOT = join(ROOT, "..", "..", "..");
const SRC = join(ROOT, "src");

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

function walkProductionTs(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out;
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name === "__tests__" || ent.name === "node_modules") continue;
      walkProductionTs(full, out);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(ent.name)) continue;
    if (/\.(test|spec)\.(ts|tsx)$/.test(ent.name)) continue;
    out.push(full);
  }
  return out;
}

describe("slice3 provenance source guard (production .tsx only)", () => {
  it("ProvenanceBadge.tsx exists in components/data and exports exactly four-state ProvenanceKind", () => {
    const badgePath = join(SRC, "components", "data", "ProvenanceBadge.tsx");
    expect(existsSync(badgePath)).toBe(true);
    const content = readFileSync(badgePath, "utf8");
    expect(content).toMatch(
      /export type ProvenanceKind = "Sample" \| "Unavailable" \| "Live" \| "Stale"/,
    );
    expect(content).toMatch(/export function ProvenanceBadge/);
    // Atom ownership: route shim owns DemoBadge alias, not the shared atom.
    expect(content).not.toMatch(/export function DemoBadge/);
  });

  it("no user-visible canonical Demo / Demo data badge copy under routes/home production", () => {
    const homeDir = join(SRC, "routes", "home");
    const offenders: string[] = [];
    for (const f of walkProductionTs(homeDir)) {
      const src = stripComments(readFileSync(f, "utf8"));
      // User-visible Demo badge copy (not identifier DemoBadge).
      if (/>\s*Demo\s*</i.test(src) || /["'`]Demo data["'`]/i.test(src) || /["'`]Demo data\s*[—-]/i.test(src)) {
        offenders.push(relative(SRC, f).replace(/\\/g, "/"));
      }
      // Bare children text "Demo" as badge label default would be user-visible.
      if (/\blabel\s*=\s*["']Demo["']/i.test(src)) {
        offenders.push(relative(SRC, f).replace(/\\/g, "/"));
      }
    }
    expect(offenders).toEqual([]);
  });

  it("Home production has no order-write imports/calls/hooks (Slice 2 vocabulary +)", () => {
    const homeDir = join(SRC, "routes", "home");
    const ORDER_WRITE =
      /placeOrder|assertNativeWriteTargetReadyOrThrow|cancelOrder|modifyOrder|usePlaceOrder|useCancelOrder|useModifyOrder|gate_order|BrokerRouter\.place/;
    const offenders: string[] = [];
    for (const f of walkProductionTs(homeDir)) {
      const text = stripComments(readFileSync(f, "utf8"));
      if (ORDER_WRITE.test(text)) {
        offenders.push(relative(SRC, f).replace(/\\/g, "/"));
      }
    }
    expect(offenders).toEqual([]);
  });

  it("Market Overview static provenance contains no role=status or aria-live", () => {
    const moPath = join(SRC, "widgets", "analysis", "MarketOverview", "shared.tsx");
    const src = stripComments(readFileSync(moPath, "utf8"));
    expect(src).not.toMatch(/role=["']status["']/);
    expect(src).not.toMatch(/aria-live/);
  });

  it("production source does not wire Stale label anywhere in this Slice 3 wave (Home + MO chrome)", () => {
    const roots = [
      join(SRC, "routes", "home"),
      join(SRC, "widgets", "analysis", "MarketOverview"),
    ];
    const offenders: string[] = [];
    for (const root of roots) {
      for (const f of walkProductionTs(root)) {
        const src = stripComments(readFileSync(f, "utf8"));
        // Wiring Stale as a runtime label / prop — type union may still mention it in atom.
        if (f.replace(/\\/g, "/").includes("ProvenanceBadge.tsx")) continue;
        if (/\blabel\s*=\s*\{?\s*["']Stale["']/.test(src) || />\s*Stale\s*</.test(src)) {
          offenders.push(relative(SRC, f).replace(/\\/g, "/"));
        }
        if (/\bdata-provenance\s*=\s*["']Stale["']/.test(src)) {
          offenders.push(relative(SRC, f).replace(/\\/g, "/"));
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("DemoBadge shim preserves internal default home-demo-badge for callers without testId", () => {
    const demoPath = join(SRC, "routes", "home", "DemoBadge.tsx");
    const src = readFileSync(demoPath, "utf8");
    expect(src).toMatch(/export function DemoBadge/);
    expect(src).toMatch(/props\.testId \?\? ["']home-demo-badge["']/);
  });

  it("docs/INVENTORY.md from repository root has count 71 and canonical mode truths", () => {
    const invPath = join(REPO_ROOT, "docs", "INVENTORY.md");
    expect(existsSync(invPath)).toBe(true);
    const inv = readFileSync(invPath, "utf8");
    expect(inv).toMatch(/\b71\b/);
    expect(inv).toMatch(/Operating modes:\s*Explore\s*\/\s*Practice\s*\/\s*Live/);
    expect(inv).toMatch(/website sample opens ordinary Home in Explore mode/i);
    expect(inv).toMatch(/installed app has no first-class Demo mode/i);
    expect(inv).toMatch(/simulated order/i);
    // Explicitly forbid paper-order framing except as a negated truth (“never a paper order”).
    expect(inv).toMatch(/never a .+paper order/i);
    expect(inv).not.toMatch(/paper trading/i);
    expect(inv).not.toMatch(/Screens:\s*welcome\s*\/\s*dashboard\s*\/\s*explore/i);
  });
});
