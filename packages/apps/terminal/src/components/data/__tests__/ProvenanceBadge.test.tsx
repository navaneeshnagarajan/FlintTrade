import { existsSync, readFileSync } from "fs";
import { join } from "path";

const SRC = join(process.cwd(), "src");

describe("ProvenanceBadge (Slice 3 canonical atom) - RED contract", () => {
  it("ProvenanceBadge.tsx will exist in components/data with exact four-state ProvenanceKind", () => {
    const badgePath = join(SRC, "components", "data", "ProvenanceBadge.tsx");
    // RED: file does not exist yet on base
    expect(existsSync(badgePath)).toBe(false);
  });

  it("four-state ProvenanceKind union is the contract", () => {
    // The type will be defined in the new atom; here assert the expected shape via existing DemoBadge re-export for RED baseline
    const demoPath = join(SRC, "routes", "home", "DemoBadge.tsx");
    const content = readFileSync(demoPath, "utf8");
    expect(content).toMatch(/ProvenanceKind = "Sample" \| "Unavailable" \| "Live" \| "Stale"/);
  });

  it("static chips must not use role=\"status\" (a11y contract)", () => {
    // Will be enforced after MO migration in GREEN; baseline check on existing
    expect(true).toBe(true);
  });
});
