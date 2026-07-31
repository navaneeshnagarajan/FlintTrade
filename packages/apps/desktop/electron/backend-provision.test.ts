import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  BackendProvisionError,
  createBackendProvisionEnvironment,
  finaliseBackendRecoveryRecord,
  provisionBackendMasterPassword,
} from "./backend-provision";

const SOURCE = path.resolve("/managed/FlintTrade");
const WORKSPACE = path.resolve("/managed/workspace");

/** Mirrors `packaging/desktop_backend.py::CLEANUP_CONTENDED_EXIT_CODE`. */
const CONTENDED = 75;

/** Cleanup fixture pinned to the host platform, so `SOURCE` stays absolute everywhere. */
function cleanupOptions() {
  return {
    applicationPid: 9001,
    env: {
      FLINTTRADE_BOOT_ID: "ab".repeat(16),
      FLINTTRADE_LAUNCH_TOKEN: "cd".repeat(32),
      FLINTTRADE_PARENT_IDENTITY: `v1|${process.platform}|4321|start|hash`,
      FLINTTRADE_PARENT_PID: "4321",
      FLINTTRADE_SIDECAR_RECORD_PATH: path.join(WORKSPACE, "desktop_backend.pid"),
    },
    guardianPid: 8001,
    platform: process.platform,
    sourceRoot: SOURCE,
  };
}

describe("backend master-password provisioning", () => {
  it("invokes only the managed Python primitive and never requests secret output", async () => {
    const execute = vi.fn(async () => ({ exitCode: 0 }));
    await expect(provisionBackendMasterPassword({
      inheritedEnvironment: {
        FLINTTRADE_MASTER_PASSWORD: "must-not-pass",
        PATH: "/trusted/bin",
        PYTHONPATH: "/untrusted",
      },
      platform: "darwin",
      process: { execute },
      sourceRoot: SOURCE,
      workspace: WORKSPACE,
    })).resolves.toBeUndefined();

    expect(execute).toHaveBeenCalledWith(expect.objectContaining({
      args: ["-m", "flinttrade_core.cli", "init", "--provision-master-password"],
      command: path.join(SOURCE, ".venv", "bin", "python"),
      cwd: SOURCE,
      env: {
        FLINTTRADE_DESKTOP: "1",
        FLINTTRADE_SOURCE_ROOT: SOURCE,
        FLINTTRADE_WORKSPACE_DIR: WORKSPACE,
        PATH: "/trusted/bin",
        PYTHONNOUSERSITE: "1",
      },
      output: "discard",
    }));
    const serialised = JSON.stringify(execute.mock.calls[0]);
    expect(serialised).not.toContain("must-not-pass");
    expect(serialised).not.toContain("PYTHONPATH");
    expect(serialised).not.toContain("master_password");
  });

  it("surfaces one stable failure without child diagnostics", async () => {
    const secretCanary = "operator-owned-secret";
    await expect(provisionBackendMasterPassword({
      process: { execute: async () => { throw new Error(secretCanary); } },
      sourceRoot: SOURCE,
      workspace: WORKSPACE,
    })).rejects.toSatisfy((error: unknown) => (
      error instanceof BackendProvisionError
      && error.message === "Backend credential provisioning failed."
      && !error.message.includes(secretCanary)
    ));

    await expect(provisionBackendMasterPassword({
      process: { execute: async () => ({ exitCode: 1 }) },
      sourceRoot: SOURCE,
      workspace: WORKSPACE,
    })).rejects.toThrow("Backend credential provisioning failed.");
  });

  it("passes cancellation through without inventing a fallback secret path", async () => {
    const controller = new AbortController();
    controller.abort(new Error("cancelled"));
    const execute = vi.fn();
    await expect(provisionBackendMasterPassword({
      process: { execute },
      signal: controller.signal,
      sourceRoot: SOURCE,
      workspace: WORKSPACE,
    })).rejects.toMatchObject({ reason: "cancelled" });
    expect(execute).not.toHaveBeenCalled();
  });

  it("normalises the Windows environment without case-variant override ambiguity", () => {
    expect(createBackendProvisionEnvironment(SOURCE, WORKSPACE, {
      Path: "C:\\canary",
      PATH: "C:\\trusted",
      FLINTTRADE_WORKSPACE_DIR: "C:\\wrong",
      SECRET: "value",
    }, "win32")).toEqual({
      FLINTTRADE_DESKTOP: "1",
      FLINTTRADE_SOURCE_ROOT: SOURCE,
      FLINTTRADE_WORKSPACE_DIR: WORKSPACE,
      PATH: "C:\\trusted",
      PYTHONNOUSERSITE: "1",
    });
  });

  it("delegates exact-record cleanup to managed Python with output discarded", async () => {
    const execute = vi.fn(async () => ({ exitCode: 0 }));
    const env = {
      FLINTTRADE_BOOT_ID: "ab".repeat(16),
      FLINTTRADE_LAUNCH_TOKEN: "cd".repeat(32),
      FLINTTRADE_PARENT_IDENTITY: "v1|darwin|4321|start|hash",
      FLINTTRADE_PARENT_PID: "4321",
      FLINTTRADE_SIDECAR_RECORD_PATH: path.join(WORKSPACE, "desktop_backend.pid"),
    };
    await finaliseBackendRecoveryRecord({
      applicationPid: 9001,
      env,
      guardianPid: 8001,
      platform: "darwin",
      process: { execute },
      sourceRoot: SOURCE,
    });

    expect(execute).toHaveBeenCalledWith(expect.objectContaining({
      args: [
        path.join(SOURCE, "packaging", "desktop_backend.py"),
        "--flinttrade-finalise-cleanup",
        "--guardian-pid",
        "8001",
        "--application-pid",
        "9001",
      ],
      env,
      output: "discard",
    }));
  });

  it("retries the dedicated contention status instead of reporting unproved cleanup", async () => {
    // 75 mirrors packaging/desktop_backend.py::CLEANUP_CONTENDED_EXIT_CODE: a
    // concurrent transition held the lock, so nothing was removed and nothing
    // is wrong with the record. Treating it as a hard failure latched the
    // supervisor's record interlock on a transient Windows lock.
    const codes = [CONTENDED, CONTENDED, 0];
    const execute = vi.fn(async () => ({ exitCode: codes.shift() ?? 0 }));
    const wait = vi.fn(async () => undefined);

    await expect(finaliseBackendRecoveryRecord({
      ...cleanupOptions(),
      contentionRetryIntervalMs: 5,
      process: { execute },
      wait,
    })).resolves.toBeUndefined();

    expect(execute).toHaveBeenCalledTimes(3);
    expect(wait).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenCalledWith(5, undefined);
  });

  it("fails closed once contention outlasts its bound, without retrying forever", async () => {
    const execute = vi.fn(async () => ({ exitCode: CONTENDED }));
    await expect(finaliseBackendRecoveryRecord({
      ...cleanupOptions(),
      contentionAttempts: 3,
      contentionRetryIntervalMs: 0,
      process: { execute },
      wait: async () => undefined,
    })).rejects.toMatchObject({
      message: "Backend recovery-record finalisation stayed contended; recovery state was retained.",
      reason: "provision",
    });
    expect(execute).toHaveBeenCalledTimes(3);
  });

  it("never retries a genuine cleanup failure, so unproved state still fails closed at once", async () => {
    for (const exitCode of [1, 2, 3, null]) {
      const execute = vi.fn(async () => ({ exitCode }));
      const wait = vi.fn(async () => undefined);
      await expect(finaliseBackendRecoveryRecord({
        ...cleanupOptions(),
        process: { execute },
        wait,
      })).rejects.toMatchObject({
        message: "Backend recovery-record finalisation failed.",
        reason: "provision",
      });
      expect(execute).toHaveBeenCalledOnce();
      expect(wait).not.toHaveBeenCalled();
    }
  });

  it("abandons a contention retry the moment the caller cancels", async () => {
    const controller = new AbortController();
    const execute = vi.fn(async () => ({ exitCode: CONTENDED }));
    await expect(finaliseBackendRecoveryRecord({
      ...cleanupOptions(),
      process: { execute },
      signal: controller.signal,
      wait: async () => { controller.abort(new Error("shutting down")); },
    })).rejects.toMatchObject({ reason: "cancelled" });
    expect(execute).toHaveBeenCalledOnce();
  });

  it("rejects a contention bound that would retry forever or pause negatively", async () => {
    const execute = vi.fn(async () => ({ exitCode: 0 }));
    for (const invalid of [{ contentionAttempts: 0 }, { contentionAttempts: 1.5 }, { contentionRetryIntervalMs: -1 }]) {
      await expect(finaliseBackendRecoveryRecord({
        ...cleanupOptions(),
        ...invalid,
        process: { execute },
      })).rejects.toMatchObject({ reason: "setup" });
    }
    expect(execute).not.toHaveBeenCalled();
  });
});
