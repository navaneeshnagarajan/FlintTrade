import { pathToFileURL } from "node:url";

import { describe, expect, it } from "vitest";

import {
  assertIpcSender,
  classifyRendererUrl,
  normaliseLoopbackOrigin,
  type RendererOriginPolicy,
} from "./origins";

const splashUrl = pathToFileURL("/Applications/FlintTrade/resources/app.asar/splash/index.html").href;
const policy: RendererOriginPolicy = {
  splashUrl,
  terminalOrigin: "http://127.0.0.1:43127",
};

describe("renderer origin classification", () => {
  it("accepts only the exact packaged splash file", () => {
    expect(classifyRendererUrl(splashUrl, policy)).toBe("splash");
    expect(classifyRendererUrl(`${splashUrl}?forged=1`, policy)).toBe("untrusted");
    expect(classifyRendererUrl(pathToFileURL("/tmp/index.html").href, policy)).toBe("untrusted");
  });

  it("accepts only the selected 127.0.0.1 origin", () => {
    expect(classifyRendererUrl("http://127.0.0.1:43127/settings", policy)).toBe("terminal");
    expect(classifyRendererUrl("http://127.0.0.1:43128/settings", policy)).toBe("untrusted");
    expect(classifyRendererUrl("http://localhost:43127/settings", policy)).toBe("untrusted");
    expect(classifyRendererUrl("https://127.0.0.1:43127/settings", policy)).toBe("untrusted");
  });

  it("normalises only explicit loopback HTTP origins", () => {
    expect(normaliseLoopbackOrigin("http://127.0.0.1:43127/path")).toBe("http://127.0.0.1:43127");
    expect(normaliseLoopbackOrigin("http://localhost:43127")).toBeNull();
    expect(normaliseLoopbackOrigin("https://127.0.0.1:43127")).toBeNull();
    expect(normaliseLoopbackOrigin("not a URL")).toBeNull();
  });
});

describe("IPC sender validation", () => {
  it("returns the trusted sender class", () => {
    expect(assertIpcSender({ senderFrame: { url: splashUrl } }, policy)).toBe("splash");
    expect(assertIpcSender({ senderFrame: { url: "http://127.0.0.1:43127/" } }, policy)).toBe("terminal");
  });

  it("rejects missing and untrusted sender frames", () => {
    expect(() => assertIpcSender({}, policy)).toThrowError(/untrusted IPC sender/i);
    expect(() => assertIpcSender({ senderFrame: { url: "https://example.com" } }, policy)).toThrowError(
      /untrusted IPC sender/i,
    );
  });
});
