import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import type { BootstrapDependencies } from "./bootstrap";
import { createSafeDirectoryRemover } from "./safe-directory-removal";
import { SourceOperationLeaseRetentionError } from "./source-operation";

function fixture(platform: NodeJS.Platform = "darwin") {
  const resources = path.join(path.sep, "app", "resources", "bootstrap");
  const helper = path.join(resources, "flinttrade-safe-rmtree.py");
  const assertHeld = vi.fn(async () => undefined);
  const run = vi.fn(async () => ({
    contained: true,
    exitCode: 0,
    stderr: "",
    stderrTruncated: false,
    stdout: '{"ok":true,"status":"removed"}\n',
    stdoutTruncated: false,
  }));
  const realpath = vi.fn(async (target: string) => target);
  const dependencies = {
    command: { reconcileOperationContainment: vi.fn(), run },
    fileSystem: {
      existsNoFollow: vi.fn(async (target: string) => target === helper),
      realpath,
    },
  } as unknown as Pick<BootstrapDependencies, "command" | "fileSystem">;
  const remove = createSafeDirectoryRemover({
    bootstrapResources: resources,
    dependencies,
    operationLease: { assertHeld, target: path.join(path.sep, "managed", "source", ".operation.lock") },
    platform,
    pythonExecutable: path.join(path.sep, "managed", "FlintTrade", ".venv", "bin", "python"),
  });
  return { assertHeld, helper, realpath, remove, run };
}

describe("managed safe directory removal boundary", () => {
  it("invokes the packaged helper with basename-confined identity arguments under the lease", async () => {
    const test = fixture();
    await test.remove({
      expected: { canonicalPath: "/managed/source/old", dev: 7, ino: 9 },
      quarantine: "/managed/source/.FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
      target: "/managed/source/FlintTrade.last-known-good",
    });

    expect(test.assertHeld).toHaveBeenCalledTimes(2);
    expect(test.run).toHaveBeenCalledWith(expect.objectContaining({
      args: [
        test.helper,
        "--parent", "/managed/source",
        "--target", "FlintTrade.last-known-good",
        "--quarantine", ".FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
        "--expected-dev", "7",
        "--expected-ino", "9",
      ],
      inheritEnvironment: false,
    }));
  });

  it("fails closed on Windows before launching a helper", async () => {
    const test = fixture("win32");
    await expect(test.remove({
      expected: { canonicalPath: "/managed/source/old", dev: 7, ino: 9 },
      quarantine: "/managed/source/quarantine",
      target: "/managed/source/target",
    })).rejects.toThrow(/unavailable on Windows/i);
    expect(test.run).not.toHaveBeenCalled();
  });

  it("passes the canonical parent when the runtime temporary root contains a platform alias", async () => {
    const test = fixture();
    test.realpath.mockImplementation(async (target: string) =>
      target === "/var/folders/runtime/source" ? "/private/var/folders/runtime/source" : target,
    );

    await test.remove({
      expected: { canonicalPath: "/private/var/folders/runtime/source/isolation", dev: 7, ino: 9 },
      quarantine: "/var/folders/runtime/source/.FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
      target: "/var/folders/runtime/source/source-update-123e4567-e89b-42d3-a456-426614174000",
    });

    expect(test.run).toHaveBeenCalledWith(expect.objectContaining({
      args: expect.arrayContaining(["--parent", "/private/var/folders/runtime/source"]),
    }));
  });

  it("retains the outer lease when helper process containment is unresolved", async () => {
    const test = fixture();
    test.run.mockResolvedValueOnce({
      contained: false,
      exitCode: 125,
      stderr: "",
      stderrTruncated: false,
      stdout: "",
      stdoutTruncated: false,
    });
    await expect(test.remove({
      expected: { canonicalPath: "/managed/source/old", dev: 7, ino: 9 },
      quarantine: "/managed/source/.FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
      target: "/managed/source/FlintTrade.last-known-good",
    })).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect(test.assertHeld).toHaveBeenCalledOnce();
  });

  it("retains the outer lease when the helper command runner rejects without a containment result", async () => {
    const test = fixture();
    test.run.mockRejectedValueOnce(new Error("command runner rejected"));
    await expect(test.remove({
      expected: { canonicalPath: "/managed/source/old", dev: 7, ino: 9 },
      quarantine: "/managed/source/.FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
      target: "/managed/source/FlintTrade.last-known-good",
    })).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect(test.assertHeld).toHaveBeenCalledOnce();
  });

  it("rejects a successful exit without the exact non-path success sentinel", async () => {
    const test = fixture();
    test.run.mockResolvedValueOnce({
      contained: true,
      exitCode: 0,
      stderr: "",
      stderrTruncated: false,
      stdout: "almost\n",
      stdoutTruncated: false,
    });
    await expect(test.remove({
      expected: { canonicalPath: "/managed/source/old", dev: 7, ino: 9 },
      quarantine: "/managed/source/.FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
      target: "/managed/source/FlintTrade.last-known-good",
    })).rejects.toThrow(/exit code 0/i);
    expect(test.assertHeld).toHaveBeenCalledOnce();
  });

  it("rejects stderr on an otherwise successful helper result", async () => {
    const test = fixture();
    test.run.mockResolvedValueOnce({
      contained: true,
      exitCode: 0,
      stderr: '{"ok":false,"code":"UNEXPECTED"}\n',
      stderrTruncated: false,
      stdout: '{"ok":true,"status":"removed"}\n',
      stdoutTruncated: false,
    });
    await expect(test.remove({
      expected: { canonicalPath: "/managed/source/old", dev: 7, ino: 9 },
      quarantine: "/managed/source/.FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
      target: "/managed/source/FlintTrade.last-known-good",
    })).rejects.toThrow(/exit code 0/i);
  });

  it.each(["stdoutTruncated", "stderrTruncated"] as const)(
    "rejects the exact success sentinel when %s is reported",
    async (truncated) => {
      const test = fixture();
      test.run.mockResolvedValueOnce({
        contained: true,
        exitCode: 0,
        stderr: "",
        stderrTruncated: false,
        stdout: '{"ok":true,"status":"removed"}\n',
        stdoutTruncated: false,
        [truncated]: true,
      });

      await expect(test.remove({
        expected: { canonicalPath: "/managed/source/old", dev: 7, ino: 9 },
        quarantine: "/managed/source/.FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
        target: "/managed/source/FlintTrade.last-known-good",
      })).rejects.toThrow(/truncat|incomplete|output/i);
      expect(test.assertHeld).toHaveBeenCalledOnce();
    },
  );

  it("retains the outer lease when the post-removal lease proof fails", async () => {
    const test = fixture();
    test.assertHeld.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("lease changed"));
    await expect(test.remove({
      expected: { canonicalPath: "/managed/source/old", dev: 7, ino: 9 },
      quarantine: "/managed/source/.FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000",
      target: "/managed/source/FlintTrade.last-known-good",
    })).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect(test.assertHeld).toHaveBeenCalledTimes(2);
  });
});
