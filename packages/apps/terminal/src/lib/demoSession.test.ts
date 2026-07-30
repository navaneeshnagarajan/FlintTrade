import { describe, it, expect, afterEach, vi } from "vitest";
import { isPublicDemoBuild } from "./demoSession";

/**
 * The public demo is served from /demo-app/ on the marketing site. Setup
 * collects an account password, a PIN and broker API keys, none of which
 * should ever be typed into a public origin, so the base path is what gates
 * those routes out of the hosted bundle.
 */
describe("isPublicDemoBuild", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("reports true for the hosted demo base path", () => {
    vi.stubEnv("BASE_URL", "/demo-app/");
    expect(isPublicDemoBuild()).toBe(true);
  });

  it("reports false for a local install served from the root", () => {
    vi.stubEnv("BASE_URL", "/");
    expect(isPublicDemoBuild()).toBe(false);
  });

  it("does not match a look-alike base path", () => {
    vi.stubEnv("BASE_URL", "/demo-app-staging/");
    expect(isPublicDemoBuild()).toBe(false);
  });
});
