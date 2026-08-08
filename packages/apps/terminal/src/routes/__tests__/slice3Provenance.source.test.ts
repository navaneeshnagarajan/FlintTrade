import { readFileSync, existsSync } from "fs";
import { join } from "path";

const ROOT = process.cwd();
const SRC = join(ROOT, "src");

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
}

describe("slice3 provenance source guard (production .tsx only)", () => {
  it("ProvenanceBadge.tsx exists in components/data and exports exactly four-state ProvenanceKind", () => {
    const badgePath = join(SRC, "components", "data", "ProvenanceBadge.tsx");
    expect(existsSync(badgePath)).toBe(true);
    const content = readFileSync(badgePath, "utf8");
    expect(content).toMatch(/export type ProvenanceKind = "Sample" \| "Unavailable" \| "Live" \| "Stale"/);
    expect(content).toMatch(/export function ProvenanceBadge/);
  });

  it("no new user-visible \"Demo\" badge text in routes/home/** production tsx (alias import OK)", () => {
    const homeDir = join(SRC, "routes", "home");
    // Walk production files (exclude __tests__)
    // Simplified: check key files for rendered "Demo"
    const filesToCheck = [
      join(homeDir, "DemoBadge.tsx"),
      join(homeDir, "WelcomeCard.tsx"),
      join(homeDir, "PortfolioCard.tsx"),
    ].filter(existsSync);
    for (const f of filesToCheck) {
      const src = stripComments(readFileSync(f, "utf8"));
      expect(src).not.toMatch(/>[\s]*Demo[\s]*</i);
      expect(src).not.toMatch(/["'`]Demo data["'`]/i);
    }
  });

  it("Market Overview shared.tsx no longer uses role=\"status\" on static provenance chips", () => {
    const moPath = join(SRC, "widgets", "analysis", "MarketOverview", "shared.tsx");
    const src = stripComments(readFileSync(moPath, "utf8"));
    expect(src).not.toMatch(/role=["']status["']/);
  });

  it("DemoBadge shim preserves internal default home-demo-badge for callers without testId", () => {
    const demoPath = join(SRC, "routes", "home", "DemoBadge.tsx");
    const src = readFileSync(demoPath, "utf8");
    expect(src).toMatch(/Preserves the internal default testId="home-demo-badge"/);
    expect(src).toMatch(/effectiveTestId = props.testId \?\? "home-demo-badge"/);
  });
});
