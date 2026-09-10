import { describe, expect, it } from "vitest";
import {
  DEFAULT_OPENALGO_HOST,
  DEFAULT_OPENALGO_PORT,
  resolveOpenAlgoHost,
} from "../openAlgoDefaults";

describe("openAlgoDefaults", () => {
  it("pins the shared OpenAlgo REST default to port 5000, never 5001 or 5100", () => {
    expect(DEFAULT_OPENALGO_PORT).toBe("5000");
    expect(DEFAULT_OPENALGO_HOST).toBe("http://127.0.0.1:5000");
    expect(DEFAULT_OPENALGO_HOST).not.toContain("5001");
    expect(DEFAULT_OPENALGO_HOST).not.toContain("5100");
  });

  it("inherits a configured Broker Gateway host", () => {
    expect(resolveOpenAlgoHost("http://192.0.2.10:5010")).toBe("http://192.0.2.10:5010");
    expect(resolveOpenAlgoHost("  http://openalgo.local:5000  ")).toBe("http://openalgo.local:5000");
  });

  it("applies a saved REST port when the Gateway host omits one", () => {
    expect(resolveOpenAlgoHost("http://192.168.1.20", "5001")).toBe("http://192.168.1.20:5001");
    expect(resolveOpenAlgoHost("http://192.168.1.20", 5001)).toBe("http://192.168.1.20:5001");
  });

  it("keeps an explicit host port instead of the separate REST-port field", () => {
    expect(resolveOpenAlgoHost("http://192.168.1.20:5000", "5001")).toBe("http://192.168.1.20:5000");
  });

  it("falls back to the shared default when Gateway host is unset", () => {
    expect(resolveOpenAlgoHost("")).toBe(DEFAULT_OPENALGO_HOST);
    expect(resolveOpenAlgoHost("   ")).toBe(DEFAULT_OPENALGO_HOST);
    expect(resolveOpenAlgoHost(null)).toBe(DEFAULT_OPENALGO_HOST);
    expect(resolveOpenAlgoHost(undefined)).toBe(DEFAULT_OPENALGO_HOST);
    expect(resolveOpenAlgoHost("", "5001")).toBe(DEFAULT_OPENALGO_HOST);
  });
});
