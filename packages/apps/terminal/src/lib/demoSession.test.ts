import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import {
  exploreRoutePolicy,
  INSTALLED_EXPLORE_REDIRECT,
  isDemoSessionActive,
  isPublicDemoBuild,
  markDemoSessionActive,
} from "./demoSession";

/**
 * The public demo is served from /demo-app/ on the marketing site. Setup
 * collects an account password, a PIN and broker API keys, none of which
 * should ever be typed into a public origin, so the base path is what gates
 * those routes out of the hosted bundle.
 *
 * Build-aware `/explore` contract (Slice 1):
 * - public demo build may render ExploreRoute
 * - installed build redirects bare /explore to welcome/onboarding
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

describe("exploreRoutePolicy (build-aware /explore contract)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("public demo build may render ExploreRoute", () => {
    vi.stubEnv("BASE_URL", "/demo-app/");
    expect(exploreRoutePolicy()).toEqual({ kind: "render-explore" });
  });

  it("installed build redirects bare /explore to safe onboarding/welcome", () => {
    vi.stubEnv("BASE_URL", "/");
    expect(exploreRoutePolicy()).toEqual({
      kind: "redirect",
      to: INSTALLED_EXPLORE_REDIRECT,
    });
    expect(INSTALLED_EXPLORE_REDIRECT).toBe("/welcome");
  });
});

describe("isDemoSessionActive (hard-refresh remount)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("restores Explore when only the demo-session marker is set", () => {
    localStorage.setItem("flinttrade:demo-session", "active");
    expect(isDemoSessionActive()).toBe(true);
  });

  it("does not restore Explore when the operator left for Practice", () => {
    localStorage.setItem("flinttrade:demo-session", "active");
    localStorage.setItem(
      "flinttrade:mode",
      JSON.stringify({ state: { mode: "practice" }, version: 2 }),
    );
    expect(isDemoSessionActive()).toBe(false);
  });

  it("markDemoSessionActive writes a durable Explore mode record", () => {
    markDemoSessionActive();
    expect(localStorage.getItem("flinttrade:demo-session")).toBe("active");
    expect(isDemoSessionActive()).toBe(true);
    const persisted = JSON.parse(localStorage.getItem("flinttrade:mode") ?? "{}") as {
      state?: { mode?: string };
    };
    expect(persisted.state?.mode).toBe("explore");
  });
});
