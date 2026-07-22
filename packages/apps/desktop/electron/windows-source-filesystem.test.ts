import { describe, expect, it, vi, type Mock } from "vitest";

import type { BootstrapDependencies, CommandResult } from "./bootstrap";
import { SourceOperationLeaseRetentionError } from "./source-operation";
import { createWindowsSourceFilesystemBoundary } from "./windows-source-filesystem";

const HELPER = "C:\\Program Files\\FlintTrade\\bootstrap\\flinttrade-source-fs.exe";
const HELPER_SHA256 = "cd".repeat(32);
const PARENT = "C:\\Users\\trader\\.flinttrade\\src";
const NATIVE_ID = "0123456789abcdef:0123456789abcdef0123456789abcdef";
const PREVIOUS_NATIVE_ID = "fedcba9876543210:fedcba9876543210fedcba9876543210";

function result(overrides: Partial<CommandResult> = {}): CommandResult {
  return {
    contained: true,
    exitCode: 0,
    stderr: "",
    stderrTruncated: false,
    stdout: JSON.stringify({ identity: NATIVE_ID, ok: true, status: "present" }) + "\n",
    stdoutTruncated: false,
    ...overrides,
  };
}

function fixture(
  run: Mock<BootstrapDependencies["command"]["run"]> = vi.fn(async () => result()),
) {
  const assertHeld = vi.fn(async () => undefined);
  const identity = { ctimeMs: 1, dev: 2, ino: 3, mtimeMs: 4, size: 5 };
  const dependencies = {
    command: { reconcileOperationContainment: vi.fn(), run },
    fileSystem: {
      existsNoFollow: vi.fn(async () => true),
      fileIdentity: vi.fn(async () => identity),
      realpath: vi.fn(async (target: string) => target),
    },
  } as unknown as Pick<BootstrapDependencies, "command" | "fileSystem">;
  return {
    assertHeld,
    boundary: createWindowsSourceFilesystemBoundary({
      dependencies,
      expectedHelperSha256: HELPER_SHA256,
      helper: HELPER,
      operationLease: { assertHeld, target: `${PARENT}\\.flinttrade-bootstrap-operation.lock` },
    }),
    run,
  };
}

describe("Windows source filesystem command boundary", () => {
  it("binds inspect and handle-bound rename requests to exact same-parent names and native IDs", async () => {
    const test = fixture();
    await expect(test.boundary.inspectDirectory(`${PARENT}\\FlintTrade`)).resolves.toEqual({
      nativeIdentity: NATIVE_ID,
      status: "present",
    });
    test.run.mockResolvedValueOnce(result({ stdout: '{"ok":true,"status":"renamed"}\n' }));
    await test.boundary.renameDirectory({
      destination: `${PARENT}\\FlintTrade.last-known-good`,
      expectedNativeIdentity: NATIVE_ID,
      source: `${PARENT}\\FlintTrade`,
    });

    expect(test.run).toHaveBeenLastCalledWith(expect.objectContaining({
      args: [
        "--source-fs", "1", "rename", "--parent", PARENT, "--source", "FlintTrade",
        "--destination", "FlintTrade.last-known-good", "--expected", NATIVE_ID,
      ],
      command: HELPER,
      expectedExecutableSha256: HELPER_SHA256,
      inheritEnvironment: false,
    }));
    expect(test.assertHeld).toHaveBeenCalledTimes(4);
  });

  it("maps native locked-file refusal to a bounded Windows retry code", async () => {
    const test = fixture(vi.fn(async () => result({
      exitCode: 75,
      stdout: '{"ok":false,"code":"LOCKED","native":32}\n',
    })));

    await expect(test.boundary.renameDirectory({
      destination: `${PARENT}\\FlintTrade.last-known-good`,
      expectedNativeIdentity: NATIVE_ID,
      source: `${PARENT}\\FlintTrade`,
    })).rejects.toMatchObject({ code: "EBUSY" });
  });

  it("accepts only exact native identity and digest evidence for journal reads", async () => {
    const digest = "ab".repeat(32);
    const test = fixture(vi.fn(async () => result({
      stdout: `${JSON.stringify({
        identity: NATIVE_ID,
        location: "target",
        ok: true,
        sha256: digest,
        status: "journal-present",
      })}\n`,
    })));

    await expect(test.boundary.inspectJournal(`${PARENT}\\.flinttrade-source-promotion.json`)).resolves.toEqual({
      location: "target",
      nativeIdentity: NATIVE_ID,
      sha256: digest,
      status: "journal-present",
    });
    expect(test.run).toHaveBeenCalledWith(expect.objectContaining({
      args: [
        "--source-fs", "1", "inspect-journal", "--path",
        `${PARENT}\\.flinttrade-source-promotion.json`,
      ],
    }));

    const previous = fixture(vi.fn(async () => result({
      stdout: `${JSON.stringify({
        identity: NATIVE_ID,
        location: "previous",
        ok: true,
        sha256: digest,
        status: "journal-present",
      })}\n`,
    })));
    await expect(
      previous.boundary.inspectJournal(`${PARENT}\\.flinttrade-source-promotion.json`),
    ).rejects.toThrow(/invalid journal evidence/i);
  });

  it("binds journal commit and removal to the exact target and proved sidecar absence", async () => {
    const target = `${PARENT}\\.flinttrade-source-promotion.json`;
    const temporary = `${target}.tmp`;
    const targetSha256 = "ab".repeat(32);
    const replacementSha256 = "34".repeat(32);
    const run = vi.fn(async (request: Parameters<BootstrapDependencies["command"]["run"]>[0]) => {
      const command = request.args[2];
      if (command === "inspect-journal-entry") {
        const inspected = request.args[4];
        if (inspected === target) {
          return result({
            stdout: `${JSON.stringify({
              identity: NATIVE_ID,
              ok: true,
              sha256: targetSha256,
              status: "journal-entry-present",
            })}\n`,
          });
        }
        if (inspected === `${target}.previous`) {
          return result({ stdout: '{"ok":true,"status":"missing"}\n' });
        }
      }
      if (command === "commit-journal") {
        return result({ stdout: '{"ok":true,"status":"journal-committed"}\n' });
      }
      if (command === "remove-journal") {
        return result({ stdout: '{"ok":true,"status":"journal-removed"}\n' });
      }
      throw new Error(`unexpected test command: ${command}`);
    });
    const test = fixture(run);

    await test.boundary.commitJournal({ sha256: replacementSha256, target, temporary });
    expect(run).toHaveBeenCalledWith(expect.objectContaining({
      args: [
        "--source-fs", "1", "commit-journal", "--parent", PARENT,
        "--temporary", ".flinttrade-source-promotion.json.tmp",
        "--target", ".flinttrade-source-promotion.json", "--sha256", replacementSha256,
        "--target-identity", NATIVE_ID, "--target-sha256", targetSha256,
        "--previous-identity", "missing", "--previous-sha256", "missing",
      ],
    }));

    await test.boundary.removeJournal({ target });
    expect(run).toHaveBeenLastCalledWith(expect.objectContaining({
      args: [
        "--source-fs", "1", "remove-journal", "--parent", PARENT,
        "--target", ".flinttrade-source-promotion.json",
        "--target-identity", NATIVE_ID, "--target-sha256", targetSha256,
        "--previous-identity", "missing", "--previous-sha256", "missing",
      ],
    }));
  });

  it("preserves and refuses every pre-existing reserved journal sidecar", async () => {
    const target = `${PARENT}\\.flinttrade-source-promotion.json`;
    const targetSha256 = "ab".repeat(32);
    const previousSha256 = "ef".repeat(32);
    const run = vi.fn(async (request: Parameters<BootstrapDependencies["command"]["run"]>[0]) => {
      if (request.args[2] !== "inspect-journal-entry") {
        throw new Error(`unexpected mutation command: ${request.args[2]}`);
      }
      const inspected = request.args[4];
      return result({
        stdout: `${JSON.stringify({
          identity: inspected === `${target}.previous` ? PREVIOUS_NATIVE_ID : NATIVE_ID,
          ok: true,
          sha256: inspected === `${target}.previous` ? previousSha256 : targetSha256,
          status: "journal-entry-present",
        })}\n`,
      });
    });
    const test = fixture(run);

    await expect(test.boundary.commitJournal({
      sha256: "34".repeat(32),
      target,
      temporary: `${target}.tmp`,
    })).rejects.toThrow(/previous sidecar.*refusing to adopt or delete/i);
    await expect(test.boundary.removeJournal({ target })).rejects.toThrow(
      /previous sidecar.*refusing to adopt or delete/i,
    );
    expect(run.mock.calls.map(([request]) => request.args[2])).toEqual([
      "inspect-journal-entry",
      "inspect-journal-entry",
      "inspect-journal-entry",
      "inspect-journal-entry",
    ]);
  });

  it("uses the preserve-only quarantine command for exact directory identity settlement", async () => {
    const test = fixture(vi.fn(async () => result({
      stdout: '{"ok":true,"status":"quarantined"}\n',
    })));

    await expect(test.boundary.quarantineDirectory({
      expectedNativeIdentity: NATIVE_ID,
      quarantine: `${PARENT}\\.FlintTrade.cleanup-quarantine-candidate-123e4567-e89b-42d3-a456-426614174000`,
      target: `${PARENT}\\FlintTrade.update-123e4567-e89b-42d3-a456-426614174000`,
    })).resolves.toEqual({ status: "quarantined" });
    expect(test.run).toHaveBeenCalledWith(expect.objectContaining({
      args: expect.arrayContaining(["quarantine-directory", "--expected", NATIVE_ID]),
    }));
    expect(test.run.mock.calls.flatMap(([request]) => request.args)).not.toContain("remove-directory");
  });

  it.each([
    ["uncontained", { contained: false }],
    ["truncated", { stdoutTruncated: true }],
    ["multi-line", { stdout: '{"ok":true,"status":"missing"}\nnoise\n' }],
  ] as const)("fails closed on %s helper proof", async (_label, override) => {
    const test = fixture(vi.fn(async () => result(override)));
    const operation = test.boundary.inspectDirectory(`${PARENT}\\FlintTrade`);
    if ("contained" in override) await expect(operation).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
    else await expect(operation).rejects.toThrow();
  });

  it("rejects cross-parent and aliased mutation names before invoking the helper", async () => {
    const test = fixture();
    await expect(test.boundary.quarantineDirectory({
      expectedNativeIdentity: NATIVE_ID,
      quarantine: "D:\\foreign\\quarantine",
      target: `${PARENT}\\FlintTrade`,
    })).rejects.toThrow(/same-parent/i);
    expect(test.run).not.toHaveBeenCalled();
  });
});
