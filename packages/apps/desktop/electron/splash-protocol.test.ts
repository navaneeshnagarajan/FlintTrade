import { describe, expect, it } from "vitest";

import {
  resolveSplashRequest,
  SPLASH_CONTENT_SECURITY_POLICY,
  splashSecurityHeaders,
  SPLASH_URL,
} from "./splash-protocol";

describe("splash protocol", () => {
  it("maps only the three packaged splash assets", () => {
    const root = "/Applications/FlintTrade/Contents/Resources/app.asar/splash";

    expect(resolveSplashRequest(SPLASH_URL, root)).toBe(`${root}/index.html`);
    expect(resolveSplashRequest("flinttrade://splash/splash.css", root)).toBe(`${root}/splash.css`);
    expect(resolveSplashRequest("flinttrade://splash/splash.js", root)).toBe(`${root}/splash.js`);
  });

  it.each([
    "flinttrade://splash/../package.json",
    "flinttrade://splash/index.html?query=1",
    "flinttrade://splash/index.html#fragment",
    "flinttrade://other/index.html",
    "flinttrade://user@splash/index.html",
    "file:///Applications/FlintTrade/Contents/Resources/app.asar/splash/index.html",
    "not a url",
  ])("rejects an unrecognised or decorated URL: %s", (url) => {
    expect(resolveSplashRequest(url, "/app/splash")).toBeNull();
  });

  it("serves a restrictive default-deny Content-Security-Policy that allows only same-origin assets", () => {
    expect(SPLASH_CONTENT_SECURITY_POLICY).toContain("default-src 'none'");
    expect(SPLASH_CONTENT_SECURITY_POLICY).toContain("script-src 'self'");
    expect(SPLASH_CONTENT_SECURITY_POLICY).toContain("style-src 'self'");
    expect(SPLASH_CONTENT_SECURITY_POLICY).toContain("frame-ancestors 'none'");
    // No remote origin, inline execution, or object/base hijack is permitted.
    expect(SPLASH_CONTENT_SECURITY_POLICY).not.toMatch(/unsafe-inline|unsafe-eval|https?:|\*/);
  });

  it("attaches the CSP while preserving the asset's own headers and not overriding its content-type", () => {
    const headers = splashSecurityHeaders(new Headers({ "content-type": "text/css" }));
    // The CSP governs sources by origin, not MIME, so the asset's own content-type
    // is preserved and never made load-bearing (no nosniff).
    expect(headers.get("content-type")).toBe("text/css");
    expect(headers.get("content-security-policy")).toBe(SPLASH_CONTENT_SECURITY_POLICY);
    expect(headers.get("x-content-type-options")).toBeNull();
  });
});
