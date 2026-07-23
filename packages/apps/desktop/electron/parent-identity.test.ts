import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  ParentIdentityError,
  captureParentIdentity,
  createParentIdentityEnvironment,
  parseParentIdentityOutput,
  type ParentIdentityProcessBoundary,
} from "./parent-identity";

const HASH = "a".repeat(64);
const SOURCE = path.resolve("/managed/FlintTrade");

function result(overrides: Partial<Awaited<ReturnType<ParentIdentityProcessBoundary["run"]>>> = {}) {
  return {
    exitCode: 0,
    stderr: "",
    stderrTruncated: false,
    stdout: `FLINTTRADE_PARENT_IDENTITY v1|darwin|4321|macos-start:123|${HASH}\n`,
    stdoutTruncated: false,
    ...overrides,
  };
}

describe("parent identity", () => {
  it("accepts exactly one complete canonical identity line", () => {
    expect(parseParentIdentityOutput(
      `FLINTTRADE_PARENT_IDENTITY v1|linux|4321|linux-start:123|${HASH}\n`,
      4321,
    )).toEqual({
      imageSha256: HASH,
      kernelStartToken: "linux-start:123",
      parentPid: 4321,
      platform: "linux",
      raw: `v1|linux|4321|linux-start:123|${HASH}`,
    });
    expect(parseParentIdentityOutput(
      `FLINTTRADE_PARENT_IDENTITY v1|win32|4321|windows-creation-time:123|${HASH}\r\n`,
      4321,
    )?.platform).toBe("win32");
  });

  it.each([
    [`FLINTTRADE_PARENT_IDENTITY v1|darwin|4321|start|${HASH}`, "complete"],
    [`FLINTTRADE_PARENT_IDENTITY v1|darwin|4321|start|${HASH}\nextra\n`, "one"],
    [`prefix FLINTTRADE_PARENT_IDENTITY v1|darwin|4321|start|${HASH}\n`, "canonical"],
    [`FLINTTRADE_PARENT_IDENTITY v1|darwin|4322|start|${HASH}\n`, "PID"],
    [`FLINTTRADE_PARENT_IDENTITY v1|darwin|4321|start|${HASH.toUpperCase()}\n`, "canonical"],
    [`FLINTTRADE_PARENT_IDENTITY v1|other|4321|start|${HASH}\n`, "canonical"],
    [`FLINTTRADE_PARENT_IDENTITY v1|darwin|4321|bad|token|${HASH}\n`, "canonical"],
  ])("rejects an invalid handshake without prefix recovery", (stdout, message) => {
    expect(() => parseParentIdentityOutput(stdout, 4321)).toThrow(message);
  });

  it("runs the active Python probe with a bounded minimal environment", async () => {
    const run = vi.fn(async () => result());
    const proof = await captureParentIdentity({
      inheritedEnvironment: {
        FLINTTRADE_MASTER_PASSWORD: "must-not-pass",
        PATH: "/trusted/bin",
        PYTHONPATH: "/untrusted",
      },
      parentPid: 4321,
      platform: "darwin",
      process: { run },
      sourceRoot: SOURCE,
      timeoutMs: 2_000,
    });

    expect(proof.raw).toBe(`v1|darwin|4321|macos-start:123|${HASH}`);
    expect(run).toHaveBeenCalledWith(expect.objectContaining({
      args: [path.join(SOURCE, "packaging", "desktop_backend.py"), "--flinttrade-print-parent-identity"],
      command: path.join(SOURCE, ".venv", "bin", "python"),
      cwd: SOURCE,
      env: { PATH: "/trusted/bin", PYTHONNOUSERSITE: "1" },
      maxOutputBytes: 4_096,
      timeoutMs: 2_000,
    }));
    expect(JSON.stringify(run.mock.calls[0])).not.toContain("must-not-pass");
    expect(JSON.stringify(run.mock.calls[0])).not.toContain("PYTHONPATH");
  });

  it.each([
    [result({ exitCode: 1 }), "exit"],
    [result({ stderr: "warning\n" }), "diagnostic"],
    [result({ stdoutTruncated: true }), "bounded"],
    [result({ stderrTruncated: true }), "bounded"],
    [result({ stdout: `FLINTTRADE_PARENT_IDENTITY v1|darwin|9999|start|${HASH}\n` }), "PID"],
  ])("fails closed on unusable probe output", async (probeResult, message) => {
    await expect(captureParentIdentity({
      parentPid: 4321,
      platform: "darwin",
      process: { run: async () => probeResult },
      sourceRoot: SOURCE,
    })).rejects.toThrow(message);
  });

  it("builds the same minimal environment without carrying repository or secret variables", () => {
    expect(createParentIdentityEnvironment(
      { HOME: "/home/operator", PATH: "/bin", FLINTTRADE_WORKSPACE_DIR: "/canary", TOKEN: "secret" },
      "linux",
    )).toEqual({ HOME: "/home/operator", PATH: "/bin", PYTHONNOUSERSITE: "1" });
  });

  it("rejects setup errors before invoking a child", async () => {
    const run = vi.fn();
    await expect(captureParentIdentity({
      parentPid: 0,
      process: { run },
      sourceRoot: SOURCE,
    })).rejects.toBeInstanceOf(ParentIdentityError);
    expect(run).not.toHaveBeenCalled();
  });
});
