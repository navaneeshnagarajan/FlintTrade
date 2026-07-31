import { describe, it, expect, afterEach, vi } from "vitest";
import { buildSections, DEMO_HIDDEN_SECTIONS } from "./settingsConfig";

/**
 * Gating /setup and /setup-account was not sufficient on its own. ExploreRoute's
 * "Demo Mode" button signs in the `demo-user` sentinel and navigates to /home,
 * from where Settings is reachable — so every section that collects a real
 * secret has to be absent from the hosted demo too.
 */
describe("settings sections in the public demo build", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("omits every credential-collecting section from the hosted demo", () => {
    const ids = buildSections(false, true).map((section) => section.id);
    for (const hidden of DEMO_HIDDEN_SECTIONS) {
      expect(ids).not.toContain(hidden);
    }
  });

  it("keeps them in a local install", () => {
    const ids = buildSections(false, false).map((section) => section.id);
    for (const hidden of DEMO_HIDDEN_SECTIONS) {
      expect(ids).toContain(hidden);
    }
  });

  it("names the sections that actually collect a secret", () => {
    // A regression guard: adding a credential-bearing section without listing it
    // here is exactly how this gap reopens.
    expect([...DEMO_HIDDEN_SECTIONS].sort()).toEqual(
      ["api", "brokers", "llm", "security", "telegram"].sort(),
    );
  });

  it("still returns the harmless sections in the demo", () => {
    const ids = buildSections(false, true).map((section) => section.id);
    expect(ids).toContain("appearance");
    expect(ids).toContain("about");
  });
});
