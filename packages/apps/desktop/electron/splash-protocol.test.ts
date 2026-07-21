import { describe, expect, it } from "vitest";

import { resolveSplashRequest, SPLASH_URL } from "./splash-protocol";

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
});
