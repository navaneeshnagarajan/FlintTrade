import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import type { BootstrapOptions, BootstrapResult } from "./bootstrap";
import {
  createSourceCandidateStager,
  type SourceCandidateOwnedPathKind,
} from "./source-candidate";
import { SourceOperationLeaseRetentionError } from "./source-operation";

const revision = "a".repeat(40);

function fixture(overrides: {
  failedKinds?: readonly SourceCandidateOwnedPathKind[];
  preexistingKinds?: readonly SourceCandidateOwnedPathKind[];
  result?: Record<string, unknown>;
  startError?: Error;
} = {}) {
  const sourceRoot = path.join(path.sep, "managed", "source");
  const activeSource = path.join(sourceRoot, "FlintTrade");
  const cancel = vi.fn(async () => true);
  const start = vi.fn<() => Promise<BootstrapResult>>(async () => {
    if (overrides.startError) throw overrides.startError;
    return {
      ok: true,
      provenance: "git" as const,
      revision,
      sourceIdentity: { dev: 1, ino: 2 },
      ...overrides.result,
    };
  });
  const received: BootstrapOptions[] = [];
  const kindForPath = (target: string): SourceCandidateOwnedPathKind | null => {
    if (target.endsWith(".candidate-1.unpack")) return "staging-unpack";
    if (target.endsWith(".candidate-1")) return "staging-candidate";
    if (path.basename(target).startsWith("FlintTrade.update-")) return "candidate";
    return null;
  };
  const identities: Record<SourceCandidateOwnedPathKind, { dev: number; ino: number }> = {
    candidate: { dev: 1, ino: 2 },
    "staging-candidate": { dev: 1, ino: 3 },
    "staging-unpack": { dev: 1, ino: 4 },
  };
  const operationLease = {
    assertHeld: vi.fn(async () => undefined),
    target: path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock"),
  };
  const bootstrap = {
    arch: "arm64",
    bootIdentity: "boot",
    bootstrapResources: path.join(path.sep, "resources"),
    dependencies: {
      command: { operationLeaseTarget: path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock"), run: vi.fn() },
      download: { file: vi.fn(), text: vi.fn() },
      extractArchive: vi.fn(),
      fileSystem: {
        directoryIdentity: vi.fn(async (target: string) => identities[kindForPath(target)!]),
        existsNoFollow: vi.fn(async (target: string) => {
          const kind = kindForPath(target);
          return kind !== null && (
            start.mock.calls.length === 0
              ? (overrides.preexistingKinds ?? []).includes(kind)
              : (overrides.failedKinds ?? ((overrides.result?.ok ?? true) ? ["candidate"] : [])).includes(kind)
          );
        }),
        remove: vi.fn(async () => undefined),
      },
    },
    manifest: {},
    paths: { activeSource, logs: "", sourceRoot, toolsRoot: "", workspace: "" },
    platform: "darwin" as const,
    singletonAuthorised: true,
  } as unknown as SourceCandidateStagerFixture;
  const stager = createSourceCandidateStager({
    bootstrap,
    createBootstrap(options) {
      received.push(options);
      return { cancel, start };
    },
    operationLease,
  });
  const prepared = vi.fn();
  const stage = (
    input: Omit<Parameters<typeof stager.stage>[0], "onOwnedPathPrepared"> &
      Partial<Pick<Parameters<typeof stager.stage>[0], "onOwnedPathPrepared">>,
  ) => stager.stage({ onOwnedPathPrepared: prepared, ...input });
  return { activeSource, bootstrap, cancel, operationLease, prepared, received, sourceRoot, stage, start };
}

type SourceCandidateStagerFixture = Parameters<typeof createSourceCandidateStager>[0]["bootstrap"];

describe("source candidate staging", () => {
  it("reuses the first-run bootstrap engine for an exact unique revision", async () => {
    const test = fixture();
    const destination = path.join(test.sourceRoot, "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000");

    await expect(test.stage({ destination, revision })).resolves.toEqual({
      identity: { dev: 1, ino: 2 },
      path: destination,
      provenance: "git",
      revision,
    });
    expect(test.received).toHaveLength(1);
    expect(test.received[0]).toMatchObject({
      expectedRevision: revision,
      heldOperationLease: test.operationLease,
      paths: { activeSource: destination, sourceRoot: test.sourceRoot },
    });
    expect(test.operationLease.assertHeld).toHaveBeenCalledOnce();
  });

  it.each([
    ["the active source", (test: ReturnType<typeof fixture>) => test.activeSource],
    ["a foreign sibling", (test: ReturnType<typeof fixture>) => path.join(test.sourceRoot, "foreign")],
    ["an escaped path", (test: ReturnType<typeof fixture>) => path.join(test.sourceRoot, "..", "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000")],
  ])("rejects %s before creating a bootstrap controller", async (_label, destinationFor) => {
    const test = fixture();
    await expect(test.stage({ destination: destinationFor(test), revision })).rejects.toThrow(/unique managed sibling/i);
    expect(test.received).toHaveLength(0);
  });

  it("preserves an existing candidate as forensic evidence", async () => {
    const test = fixture({ preexistingKinds: ["candidate"] });
    const destination = path.join(test.sourceRoot, "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000");
    await expect(test.stage({ destination, revision })).rejects.toThrow(/already exists|forensic/i);
    expect(test.received).toHaveLength(0);
  });

  it("proves the shared filesystem lease before any candidate inspection or mutation", async () => {
    const test = fixture();
    test.operationLease.assertHeld.mockRejectedValueOnce(new Error("source-operation lease is not held"));
    const destination = path.join(
      test.sourceRoot,
      "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000",
    );

    await expect(test.stage({ destination, revision })).rejects.toThrow(/lease is not held/i);
    expect(test.bootstrap.dependencies.fileSystem.existsNoFollow).not.toHaveBeenCalled();
    expect(test.received).toHaveLength(0);
  });

  it("cancels the shared bootstrap mechanics when the update attempt is aborted", async () => {
    const test = fixture();
    let resolveStart!: (value: BootstrapResult) => void;
    test.start.mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveStart = resolve;
      }),
    );
    test.cancel.mockImplementationOnce(async () => {
      resolveStart({ cancelled: true, error: "cancelled", ok: false });
      return true;
    });
    const abort = new AbortController();
    const destination = path.join(test.sourceRoot, "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000");
    const staging = test.stage({ destination, revision, signal: abort.signal });
    await vi.waitFor(() => expect(test.start).toHaveBeenCalledOnce());
    abort.abort();

    await expect(staging).rejects.toMatchObject({ name: "AbortError" });
    expect(test.cancel).toHaveBeenCalledOnce();
  });

  it("rejects non-full revisions and revision drift", async () => {
    const destination = path.join(path.sep, "managed", "source", "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000");
    const invalid = fixture();
    await expect(invalid.stage({ destination, revision: "main" })).rejects.toThrow(/full Git commit/i);

    const drift = fixture({ result: { revision: "b".repeat(40) } });
    await expect(drift.stage({ destination, revision })).rejects.toThrow(/does not match/i);
    expect(drift.prepared).toHaveBeenCalledWith({
      identity: { dev: 1, ino: 2 },
      kind: "candidate",
      path: destination,
    });
  });

  it("publishes exact nested and promoted ownership after an ordinary staging failure", async () => {
    const test = fixture({
      failedKinds: ["candidate", "staging-candidate", "staging-unpack"],
      result: { error: "build failed", ok: false },
    });
    const destination = path.join(
      test.sourceRoot,
      "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000",
    );
    const prepared = vi.fn();

    await expect(test.stage({ destination, onOwnedPathPrepared: prepared, revision })).rejects.toThrow("build failed");
    expect(prepared.mock.calls.map(([owned]) => owned)).toEqual([
      { identity: { dev: 1, ino: 2 }, kind: "candidate", path: destination },
      { identity: { dev: 1, ino: 3 }, kind: "staging-candidate", path: `${destination}.candidate-1` },
      { identity: { dev: 1, ino: 4 }, kind: "staging-unpack", path: `${destination}.candidate-1.unpack` },
    ]);
    expect(test.bootstrap.dependencies.fileSystem.remove).not.toHaveBeenCalled();
  });

  it("publishes exact ownership when the nested bootstrap controller rejects", async () => {
    const controllerFailure = new Error("bootstrap controller rejected");
    const test = fixture({ failedKinds: ["staging-candidate"], startError: controllerFailure });
    const destination = path.join(
      test.sourceRoot,
      "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000",
    );
    const prepared = vi.fn();

    const error = await test.stage({ destination, onOwnedPathPrepared: prepared, revision }).catch(
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(SourceOperationLeaseRetentionError);
    expect((error as Error).cause).toBe(controllerFailure);
    expect(prepared).toHaveBeenCalledWith({
      identity: { dev: 1, ino: 3 },
      kind: "staging-candidate",
      path: `${destination}.candidate-1`,
    });
  });

  it("preserves the outer operation lease when nested bootstrap containment is unproved", async () => {
    const test = fixture({
      failedKinds: ["staging-candidate"],
      result: {
        containmentFailed: true,
        error: "Candidate command containment could not be proven.",
        ok: false,
      },
    });
    const destination = path.join(
      test.sourceRoot,
      "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000",
    );
    const prepared = vi.fn();

    await expect(test.stage({ destination, onOwnedPathPrepared: prepared, revision })).rejects.toBeInstanceOf(
      SourceOperationLeaseRetentionError,
    );
    expect(prepared).toHaveBeenCalledWith({
      identity: { dev: 1, ino: 3 },
      kind: "staging-candidate",
      path: `${destination}.candidate-1`,
    });
    expect(test.bootstrap.dependencies.fileSystem.remove).not.toHaveBeenCalled();
  });

  it("rejects a pre-existing bootstrap staging alias before starting", async () => {
    const test = fixture({ preexistingKinds: ["staging-candidate"] });
    const destination = path.join(
      test.sourceRoot,
      "FlintTrade.update-123e4567-e89b-42d3-a456-426614174000",
    );

    await expect(test.stage({ destination, revision })).rejects.toThrow(/staging alias already exists|forensic/i);
    expect(test.received).toHaveLength(0);
  });
});
