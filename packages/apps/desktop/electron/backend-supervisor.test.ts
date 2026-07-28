import path from "node:path";
import { lstat, mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import { fileURLToPath } from "node:url";

import { describe, expect, it, vi } from "vitest";

import {
  BackendSupervisor,
  BackendSupervisorError,
  createBackendEnvironment,
  createNodeBackendSpawnBoundary,
  normaliseGuardianBootIdentity,
  type BackendRecordFinaliseInput,
  type BackendExitEvent,
  type BackendSpawnBoundary,
  type BackendSpawnHandle,
  type BackendSpawnInvocation,
  type BackendSupervisorClock,
} from "./backend-supervisor";
import type { ParentIdentityProof } from "./parent-identity";

const SOURCE = path.resolve("/managed/FlintTrade");
const WORKSPACE = path.resolve("/managed/workspace");
const FRONTEND = path.join(SOURCE, "packages", "apps", "terminal", "dist");
const PARENT_PID = 4321;
const HASH = "a".repeat(64);
const IDENTITY: ParentIdentityProof = {
  imageSha256: HASH,
  kernelStartToken: "macos-start:123",
  parentPid: PARENT_PID,
  platform: "darwin",
  raw: `v1|darwin|${PARENT_PID}|macos-start:123|${HASH}`,
};

class FakeBackendHandle implements BackendSpawnHandle {
  readonly forceCalls: Array<number | null> = [];
  readonly pid: number;
  readonly writes: string[] = [];
  private closed = false;
  private readonly invocation: BackendSpawnInvocation;

  constructor(invocation: BackendSpawnInvocation, pid: number) {
    this.invocation = invocation;
    this.pid = pid;
  }

  emitStderr(text: string): void {
    this.invocation.onStderr(Buffer.from(text));
  }

  emitStdout(text: string): void {
    this.invocation.onStdout(Buffer.from(text));
  }

  exit(exitCode = 0, signal: NodeJS.Signals | null = null): void {
    if (this.closed) return;
    this.closed = true;
    this.invocation.onExit({ exitCode, signal });
  }

  async forceContainment(applicationPid: number | null): Promise<boolean> {
    this.forceCalls.push(applicationPid);
    return false;
  }

  async writeStdin(command: string): Promise<void> {
    this.writes.push(command);
  }
}

class FakeBackendSpawn implements BackendSpawnBoundary {
  readonly handles: FakeBackendHandle[] = [];
  readonly invocations: BackendSpawnInvocation[] = [];
  onSpawn: (() => void) | null = null;

  spawn(invocation: BackendSpawnInvocation): BackendSpawnHandle {
    this.invocations.push(invocation);
    this.onSpawn?.();
    const handle = new FakeBackendHandle(invocation, 8_000 + this.handles.length);
    this.handles.push(handle);
    return handle;
  }
}

class FakeClock implements BackendSupervisorClock {
  readonly callbacks = new Map<number, () => void>();
  readonly delays: number[] = [];
  private next = 1;

  clearTimeout(handle: unknown): void {
    this.callbacks.delete(handle as number);
  }

  fireAll(): void {
    for (const [handle, callback] of [...this.callbacks]) {
      this.callbacks.delete(handle);
      callback();
    }
  }

  setTimeout(callback: () => void, milliseconds: number): unknown {
    this.delays.push(milliseconds);
    const handle = this.next++;
    this.callbacks.set(handle, callback);
    return handle;
  }
}

async function eventually(predicate: () => boolean): Promise<void> {
  for (let iteration = 0; iteration < 50; iteration += 1) {
    if (predicate()) return;
    await Promise.resolve();
  }
  throw new Error("fixture condition did not settle");
}

function createFixture(overrides: {
  captureParentIdentity?: () => Promise<ParentIdentityProof>;
  clock?: BackendSupervisorClock;
  finaliseRecord?: (input: BackendRecordFinaliseInput) => Promise<void>;
  health?: (port: number, signal: AbortSignal) => Promise<true>;
  onNotification?: (event: { body: string; title: string }) => void;
  onStableFailure?: (error: BackendSupervisorError) => void;
  onUnexpectedExit?: (event: BackendExitEvent) => void;
  provision?: () => Promise<void>;
  randomBytes?: (size: number) => Buffer;
  spawn?: FakeBackendSpawn;
} = {}) {
  const backendSpawn = overrides.spawn ?? new FakeBackendSpawn();
  const states: unknown[] = [];
  const supervisor = new BackendSupervisor({
    bootSessionIdentity: "darwin:100",
    dependencies: {
      captureParentIdentity: overrides.captureParentIdentity ?? (async () => IDENTITY),
      ...(overrides.clock ? { clock: overrides.clock } : {}),
      finaliseRecord: overrides.finaliseRecord ?? (async () => undefined),
      health: overrides.health ?? (async () => true),
      provision: overrides.provision ?? (async () => undefined),
      randomBytes: overrides.randomBytes ?? (() => Buffer.alloc(32, 0xab)),
      spawn: backendSpawn,
    },
    drainTiming: { containmentMs: 3, forceMs: 3, gracefulMs: 3 },
    frontendDist: FRONTEND,
    inheritedEnvironment: {
      FLINTTRADE_MASTER_PASSWORD: "must-not-pass",
      PATH: "/trusted/bin",
      PYTHONPATH: "/untrusted",
    },
    ...(overrides.onNotification ? { onNotification: overrides.onNotification } : {}),
    ...(overrides.onStableFailure ? { onStableFailure: overrides.onStableFailure } : {}),
    onState: (state) => states.push(state),
    ...(overrides.onUnexpectedExit ? { onUnexpectedExit: overrides.onUnexpectedExit } : {}),
    parentPid: PARENT_PID,
    platform: "darwin",
    preReadyDrainTiming: { containmentMs: 30, forceMs: 2, gracefulMs: 2 },
    sourceRoot: SOURCE,
    workspace: WORKSPACE,
  });
  return { backendSpawn, states, supervisor };
}

async function startReady(supervisor: BackendSupervisor, backendSpawn: FakeBackendSpawn) {
  const starting = supervisor.start();
  await eventually(() => backendSpawn.handles.length === 1);
  const handle = backendSpawn.handles[0]!;
  handle.emitStdout("FLINTTRADE_BACKEND_PID pid=9001\n");
  handle.emitStdout("FLINTTRADE_BACKEND_READY port=5100\n");
  return { handle, running: await starting };
}

describe("backend supervisor", () => {
  it("provisions, captures the parent, mints a token, then launches the exact source guardian", async () => {
    const order: string[] = [];
    const spawn = new FakeBackendSpawn();
    spawn.onSpawn = () => order.push("spawn");
    const { supervisor } = createFixture({
      captureParentIdentity: async () => { order.push("identity"); return IDENTITY; },
      health: async (port) => { order.push(`health:${port}`); return true; },
      provision: async () => { order.push("provision"); },
      randomBytes: (size) => { order.push(`random:${size}`); return Buffer.alloc(size, 0xab); },
      spawn,
    });

    const starting = supervisor.start();
    await eventually(() => spawn.handles.length === 1);
    expect(order).toEqual(["provision", "identity", "random:32", "spawn"]);
    const handle = spawn.handles[0]!;
    handle.emitStderr("ordinary backend diagnostic\n");
    handle.emitStdout("FLINTTRADE_BACKEND_PID pid=");
    handle.emitStdout("9001\nFLINTTRADE_BACKEND_READY port=5100\n");
    const running = await starting;

    expect(order).toEqual(["provision", "identity", "random:32", "spawn", "health:5100"]);
    expect(running).toMatchObject({
      applicationPid: 9001,
      attempt: 1,
      launchToken: "ab".repeat(32),
      port: 5100,
      recordPath: path.join(WORKSPACE, "desktop_backend.pid"),
      url: "http://127.0.0.1:5100",
    });
    expect(spawn.invocations[0]).toMatchObject({
      args: [path.join(SOURCE, "packaging", "desktop_backend.py"), "--port", "0"],
      command: path.join(SOURCE, ".venv", "bin", "python"),
      cwd: SOURCE,
      env: {
        FLINTTRADE_BOOT_ID: Buffer.from("darwin:100").toString("hex"),
        FLINTTRADE_DESKTOP: "1",
        FLINTTRADE_FRONTEND_DIST: FRONTEND,
        FLINTTRADE_LAUNCH_TOKEN: "ab".repeat(32),
        FLINTTRADE_PARENT_IDENTITY: IDENTITY.raw,
        FLINTTRADE_PARENT_PID: String(PARENT_PID),
        FLINTTRADE_SIDECAR_RECORD_PATH: path.join(WORKSPACE, "desktop_backend.pid"),
        FLINTTRADE_SOURCE_ROOT: SOURCE,
        FLINTTRADE_WORKSPACE_DIR: WORKSPACE,
        PATH: "/trusted/bin",
        PYTHONNOUSERSITE: "1",
      },
    });
    const serialised = JSON.stringify(spawn.invocations[0]);
    expect(serialised).not.toContain("must-not-pass");
    expect(serialised).not.toContain("PYTHONPATH");
  });

  it("normalises a stable boot-session value to Python's even lower-hex record field", () => {
    expect(normaliseGuardianBootIdentity("darwin:100")).toBe(Buffer.from("darwin:100").toString("hex"));
    expect(() => normaliseGuardianBootIdentity("")).toThrow("boot-session");
    expect(() => normaliseGuardianBootIdentity("x".repeat(257))).toThrow("boot-session");
  });

  it("builds a minimal launch environment and never precreates or recovers the record", () => {
    const environment = createBackendEnvironment({
      bootSessionIdentity: "linux:100",
      frontendDist: FRONTEND,
      inheritedEnvironment: {
        FLINTTRADE_SIDECAR_RECORD_PATH: "/attacker/record",
        PATH: "/bin",
        SECRET: "canary",
      },
      launchToken: "c".repeat(64),
      parentIdentity: { ...IDENTITY, platform: "linux", raw: IDENTITY.raw.replace("darwin", "linux") },
      parentPid: PARENT_PID,
      platform: "linux",
      recordPath: path.join(WORKSPACE, "desktop_backend.pid"),
      sourceRoot: SOURCE,
      workspace: WORKSPACE,
    });
    expect(environment.FLINTTRADE_SIDECAR_RECORD_PATH).toBe(path.join(WORKSPACE, "desktop_backend.pid"));
    expect(environment.SECRET).toBeUndefined();
    expect(Object.keys(environment)).not.toContain("FLINTTRADE_MASTER_PASSWORD");
  });

  it("fails immediately when ready arrives before the exact application PID", async () => {
    const onStableFailure = vi.fn();
    const { backendSpawn, supervisor } = createFixture({ onStableFailure });
    const starting = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 1);
    backendSpawn.handles[0]!.emitStdout("FLINTTRADE_BACKEND_READY port=5100\n");

    await expect(starting).rejects.toMatchObject({ reason: "protocol", stoppedSafe: false });
    expect(supervisor.getState().stoppedSafe).toBe(false);
    expect(onStableFailure).toHaveBeenCalledTimes(1);
    expect(backendSpawn.handles[0]!.forceCalls).toEqual([null]);
  });

  it("ignores malformed and partial sentinels, drains stderr, and reports a pre-ready exit", async () => {
    const onUnexpectedExit = vi.fn();
    const onStableFailure = vi.fn();
    const { backendSpawn, supervisor } = createFixture({ onStableFailure, onUnexpectedExit });
    const starting = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 1);
    const handle = backendSpawn.handles[0]!;
    handle.emitStderr("x".repeat(200_000));
    handle.emitStdout("prefix FLINTTRADE_BACKEND_PID pid=9001\n");
    handle.emitStdout("FLINTTRADE_BACKEND_READY port=5100");
    handle.exit(2);

    await expect(starting).rejects.toMatchObject({ reason: "early-exit" });
    expect(onStableFailure).toHaveBeenCalledTimes(1);
    expect(onUnexpectedExit).not.toHaveBeenCalled();
  });

  it("stops before identity capture or token minting when provisioning fails", async () => {
    const capture = vi.fn();
    const random = vi.fn();
    const { backendSpawn, supervisor } = createFixture({
      captureParentIdentity: capture,
      provision: async () => { throw new Error("failed"); },
      randomBytes: random,
    });
    await expect(supervisor.start()).rejects.toMatchObject({ reason: "provisioning", stoppedSafe: true });
    expect(supervisor.getState().stoppedSafe).toBe(true);
    expect(capture).not.toHaveBeenCalled();
    expect(random).not.toHaveBeenCalled();
    expect(backendSpawn.handles).toHaveLength(0);
  });

  it("does not mint a launch token when the parent probe fails", async () => {
    const random = vi.fn();
    const { backendSpawn, supervisor } = createFixture({
      captureParentIdentity: async () => { throw new Error("bad probe"); },
      randomBytes: random,
    });
    await expect(supervisor.start()).rejects.toMatchObject({ reason: "parent-identity", stoppedSafe: true });
    expect(random).not.toHaveBeenCalled();
    expect(backendSpawn.handles).toHaveLength(0);
  });

  it("enforces the injected 180-second start watchdog boundary", async () => {
    const clock = new FakeClock();
    const { backendSpawn, supervisor } = createFixture({ clock });
    const starting = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 1);
    expect(clock.callbacks.size).toBe(1);
    expect(clock.delays).toEqual([180_000]);
    clock.fireAll();

    await expect(starting).rejects.toMatchObject({ reason: "timeout" });
    expect(backendSpawn.handles[0]!.forceCalls).toEqual([null]);
  });

  it("cancels a superseded attempt and rejects all of its later protocol events", async () => {
    let token = 0;
    const randomBytes = (size: number): Buffer => Buffer.alloc(size, ++token);
    const { backendSpawn, supervisor, states } = createFixture({ randomBytes });
    const first = supervisor.start();
    const firstRejected = expect(first).rejects.toMatchObject({ reason: "cancelled", stoppedSafe: true });
    await eventually(() => backendSpawn.handles.length === 1);
    const firstHandle = backendSpawn.handles[0]!;

    const second = supervisor.start();
    const secondHandled = second.catch((error: unknown) => { throw error; });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(firstHandle.forceCalls).toEqual([null]);
    expect(backendSpawn.handles).toHaveLength(1);
    firstHandle.emitStdout(
      `FLINTTRADE_BACKEND_PENDING_EXIT_ACK token=${backendSpawn.invocations[0]!.env.FLINTTRADE_LAUNCH_TOKEN} reason=force-exit\n`,
    );
    firstHandle.exit(0);
    await firstRejected;
    await eventually(() => backendSpawn.handles.length === 2);
    const secondHandle = backendSpawn.handles[1]!;
    firstHandle.emitStdout("FLINTTRADE_BACKEND_PID pid=1111\nFLINTTRADE_BACKEND_READY port=5111\n");
    firstHandle.exit(0);
    secondHandle.emitStdout("FLINTTRADE_BACKEND_PID pid=2222\nFLINTTRADE_BACKEND_READY port=5222\n");
    const running = await secondHandled;

    expect(running).toMatchObject({ applicationPid: 2222, attempt: 2, port: 5222 });
    expect(backendSpawn.invocations[0]!.env.FLINTTRADE_LAUNCH_TOKEN)
      .not.toBe(backendSpawn.invocations[1]!.env.FLINTTRADE_LAUNCH_TOKEN);
    expect(JSON.stringify(states)).not.toContain("5111");
  });

  it("treats health as part of readiness and fails if the child exits while ping is pending", async () => {
    const health = vi.fn(() => new Promise<true>(() => undefined));
    const { backendSpawn, supervisor } = createFixture({ health });
    const starting = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 1);
    const handle = backendSpawn.handles[0]!;
    handle.emitStdout("FLINTTRADE_BACKEND_PID pid=9001\nFLINTTRADE_BACKEND_READY port=5100\n");
    await eventually(() => health.mock.calls.length === 1);
    handle.exit(1);

    await expect(starting).rejects.toMatchObject({ reason: "early-exit" });
  });

  it("surfaces an unexpected post-ready exit once, but not an expected drain exit", async () => {
    const onUnexpectedExit = vi.fn();
    const first = createFixture({ onUnexpectedExit });
    const ready = await startReady(first.supervisor, first.backendSpawn);
    ready.handle.exit(9, "SIGTERM");
    expect(onUnexpectedExit).toHaveBeenCalledOnce();
    expect(onUnexpectedExit).toHaveBeenCalledWith({ exitCode: 9, signal: "SIGTERM" });

    const finaliseRecord = vi.fn(async () => undefined);
    const second = createFixture({ finaliseRecord, onUnexpectedExit });
    const expected = await startReady(second.supervisor, second.backendSpawn);
    const draining = expected.running.drain();
    expected.handle.emitStdout(`FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=${expected.running.launchToken}\n`);
    expected.handle.exit(0);
    await expect(draining).resolves.toMatchObject({ outcome: "clean", recordRemovalSafe: true });
    expect(second.supervisor.getState()).toMatchObject({ status: "stopped", stoppedSafe: true });
    expect(finaliseRecord).toHaveBeenCalledWith(expect.objectContaining({
      applicationPid: 9001,
      guardianPid: expected.handle.pid,
      launchToken: expected.running.launchToken,
      recordPath: path.join(WORKSPACE, "desktop_backend.pid"),
    }));
    expect(onUnexpectedExit).toHaveBeenCalledTimes(1);
  });

  it("retains recovery authority when cleanup proof carries the wrong token", async () => {
    const finaliseRecord = vi.fn(async () => undefined);
    const { backendSpawn, supervisor } = createFixture({ finaliseRecord });
    const { handle, running } = await startReady(supervisor, backendSpawn);
    const draining = running.drain();
    handle.emitStdout(`FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=${"f".repeat(64)}\n`);
    handle.exit(0);

    await expect(draining).resolves.toMatchObject({
      outcome: "unresolved",
      proof: null,
      recordRemovalSafe: false,
    });
    expect(handle.writes).toEqual(["FLINTTRADE_SHUTDOWN\n"]);
    expect(finaliseRecord).not.toHaveBeenCalled();
  });

  it("keeps a start interlock when managed exact-record finalisation fails", async () => {
    const finaliseRecord = vi.fn(async () => { throw new Error("record changed"); });
    const { backendSpawn, supervisor } = createFixture({ finaliseRecord });
    const { handle, running } = await startReady(supervisor, backendSpawn);
    const draining = running.drain();
    handle.emitStdout(`FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=${running.launchToken}\n`);
    handle.exit(0);

    await expect(draining).rejects.toMatchObject({ reason: "record-cleanup" });
    await expect(supervisor.start()).rejects.toMatchObject({ reason: "record-cleanup" });
    expect(supervisor.getState().stoppedSafe).toBe(false);
    expect(backendSpawn.handles).toHaveLength(1);
  });

  it("does not start a successor until an expected drain finishes record finalisation", async () => {
    let finishFinalise!: () => void;
    const finaliseRecord = vi.fn(() => new Promise<void>((resolve) => { finishFinalise = resolve; }));
    const { backendSpawn, supervisor } = createFixture({ finaliseRecord });
    const { handle, running } = await startReady(supervisor, backendSpawn);
    const draining = running.drain();
    handle.emitStdout(`FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=${running.launchToken}\n`);
    handle.exit(0);
    await eventually(() => finaliseRecord.mock.calls.length === 1);

    const successor = supervisor.start();
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(backendSpawn.handles).toHaveLength(1);
    finishFinalise();
    await expect(draining).resolves.toMatchObject({ outcome: "clean" });
    await eventually(() => backendSpawn.handles.length === 2);
    backendSpawn.handles[1]!.emitStdout("FLINTTRADE_BACKEND_PID pid=9002\n");
    backendSpawn.handles[1]!.emitStdout("FLINTTRADE_BACKEND_READY port=5200\n");
    await expect(successor).resolves.toMatchObject({ applicationPid: 9002, port: 5200 });
  });

  it("forwards only parsed notification events", async () => {
    const onNotification = vi.fn();
    const { backendSpawn, supervisor } = createFixture({ onNotification });
    const { handle } = await startReady(supervisor, backendSpawn);
    handle.emitStdout("prefix FLINTTRADE_NOTIFY\tBad\tIgnored\n");
    handle.emitStdout("FLINTTRADE_NOTIFY\tEngine alert\tData feed recovered\n");
    expect(onNotification).toHaveBeenCalledOnce();
    expect(onNotification).toHaveBeenCalledWith({ body: "Data feed recovered", title: "Engine alert" });
  });

  it("surfaces an exact workspace-lease refusal as a stable blocked failure", async () => {
    const finaliseRecord = vi.fn(async () => undefined);
    const { backendSpawn, supervisor } = createFixture({ finaliseRecord });
    const starting = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 1);
    backendSpawn.handles[0]!.emitStdout("FLINTTRADE_BACKEND_BLOCKED reason=instance-lease\n");
    backendSpawn.handles[0]!.exit(1);
    await expect(starting).rejects.toMatchObject({ reason: "blocked", stoppedSafe: true });
    expect(finaliseRecord).not.toHaveBeenCalled();

    const retry = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 2);
    backendSpawn.handles[1]!.emitStdout("FLINTTRADE_BACKEND_PID pid=9002\n");
    backendSpawn.handles[1]!.emitStdout("FLINTTRADE_BACKEND_READY port=5200\n");
    await expect(retry).resolves.toMatchObject({ applicationPid: 9002, attempt: 2, port: 5200 });
  });

  it("lets Retry replace a first-event stale-record block without finalising foreign authority", async () => {
    const finaliseRecord = vi.fn(async () => undefined);
    const { backendSpawn, supervisor } = createFixture({ finaliseRecord });
    const starting = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 1);
    backendSpawn.handles[0]!.emitStdout("FLINTTRADE_BACKEND_BLOCKED reason=recovery-record\n");
    backendSpawn.handles[0]!.exit(1);

    await expect(starting).rejects.toMatchObject({
      message: "Backend recovery state is unresolved. Retry after the prior backend exits.",
      reason: "blocked",
      stoppedSafe: true,
    });
    expect(finaliseRecord).not.toHaveBeenCalled();

    const retry = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 2);
    backendSpawn.handles[1]!.emitStdout("FLINTTRADE_BACKEND_PID pid=9002\n");
    backendSpawn.handles[1]!.emitStdout("FLINTTRADE_BACKEND_READY port=5200\n");
    await expect(retry).resolves.toMatchObject({ applicationPid: 9002, attempt: 2, port: 5200 });
  });

  it("does not let a late blocked line bypass exact record finalisation", async () => {
    const finaliseRecord = vi.fn(async () => undefined);
    const { backendSpawn, supervisor } = createFixture({ finaliseRecord });
    const starting = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 1);
    const handle = backendSpawn.handles[0]!;
    handle.emitStdout("FLINTTRADE_BACKEND_PID pid=9001\n");
    handle.emitStdout("FLINTTRADE_BACKEND_BLOCKED reason=instance-lease\n");
    await eventually(() => handle.writes.length === 1);
    const token = backendSpawn.invocations[0]!.env.FLINTTRADE_LAUNCH_TOKEN!;
    handle.emitStdout(`FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=${token}\n`);
    handle.exit(1);

    await expect(starting).rejects.toMatchObject({ reason: "protocol", stoppedSafe: true });
    expect(finaliseRecord).toHaveBeenCalledOnce();
  });

  it("always delegates pending-exit ACK to idempotent managed finalisation", async () => {
    const finaliseRecord = vi.fn(async () => undefined);
    const { backendSpawn, supervisor } = createFixture({ finaliseRecord });
    const starting = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 1);
    const handle = backendSpawn.handles[0]!;
    const token = backendSpawn.invocations[0]!.env.FLINTTRADE_LAUNCH_TOKEN!;
    handle.emitStdout(`FLINTTRADE_BACKEND_PENDING_EXIT_ACK token=${token} reason=promotion-failed\n`);
    handle.exit(1);

    await expect(starting).rejects.toMatchObject({ reason: "early-exit", stoppedSafe: true });
    expect(finaliseRecord).toHaveBeenCalledOnce();
    const retry = supervisor.start();
    await eventually(() => backendSpawn.handles.length === 2);
    backendSpawn.handles[1]!.emitStdout("FLINTTRADE_BACKEND_PID pid=9002\n");
    backendSpawn.handles[1]!.emitStdout("FLINTTRADE_BACKEND_READY port=5200\n");
    await expect(retry).resolves.toMatchObject({ applicationPid: 9002, port: 5200 });
  });
});

it.runIf(process.platform !== "win32")(
  "contains only the exact guardian child and handles a closed stdin pipe without an unhandled error",
  async () => {
    const boundary = createNodeBackendSpawnBoundary(process.platform);
    let stdout = "";
    let resolveExit!: (event: BackendExitEvent) => void;
    const exited = new Promise<BackendExitEvent>((resolve) => { resolveExit = resolve; });
    const handle = boundary.spawn({
      args: [
        "-e",
        "require('fs').closeSync(0); process.stdout.write('closed\\n'); setInterval(() => {}, 1000)",
      ],
      command: process.execPath,
      cwd: process.cwd(),
      env: process.env,
      onExit: resolveExit,
      onStderr: () => undefined,
      onStdout: (chunk) => { stdout += chunk.toString("utf8"); },
    });
    await vi.waitFor(() => expect(stdout).toContain("closed\n"), { timeout: 15_000 });

    await expect(handle.writeStdin("FLINTTRADE_FORCE_EXIT\n")).rejects.toBeInstanceOf(Error);
    await expect(handle.forceContainment(0xffff_fffe)).resolves.toBe(false);
    await expect(exited).resolves.toMatchObject({ signal: "SIGTERM" });
  },
  // Must exceed the 15s waitFor above, or a slow spawn dies as an opaque
  // test-timeout instead of the waitFor's assertion.
  20_000,
);

async function pathIsAbsent(target: string): Promise<boolean> {
  try {
    await lstat(target);
    return false;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return true;
    throw error;
  }
}

async function waitForPidExit(pid: number): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    try {
      process.kill(pid, 0);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ESRCH") return;
      throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`managed process ${pid} survived supervisor drain`);
}

const RUN_REAL_SUPERVISOR = process.env.FLINTTRADE_RUN_INTEGRATION === "1";

it.runIf(RUN_REAL_SUPERVISOR)("boots and drains the real source guardian in a temporary workspace", async () => {
  const electronDirectory = fileURLToPath(new URL(".", import.meta.url));
  const sourceRoot = path.resolve(electronDirectory, "../../../..");
  const workspace = await mkdtemp(path.join(os.tmpdir(), "flinttrade-electron-supervisor-"));
  const recordPath = path.join(workspace, "desktop_backend.pid");
  const proofPath = path.join(workspace, ".desktop_backend.pid.cleanup-complete");
  const bootSessionIdentity = `${process.platform}:${Math.round(Date.now() / 1_000 - os.uptime())}`;
  const supervisor = new BackendSupervisor({
    bootSessionIdentity,
    frontendDist: path.join(sourceRoot, "packages", "apps", "terminal", "dist"),
    sourceRoot,
    workspace,
  });
  let safeToRemove = false;
  try {
    const running = await supervisor.start();
    const record = (await readFile(recordPath, "utf8")).split(/\r?\n/);
    expect(record.slice(0, 6)).toEqual([
      "v4",
      String(running.guardianPid),
      String(running.applicationPid),
      String(process.pid),
      normaliseGuardianBootIdentity(bootSessionIdentity),
      running.launchToken,
    ]);

    const result = await running.drain();
    expect(result).toMatchObject({ childExited: true, outcome: "clean", recordRemovalSafe: true });
    expect(supervisor.getState()).toMatchObject({ status: "stopped", stoppedSafe: true });
    expect(await pathIsAbsent(recordPath)).toBe(true);
    expect(await pathIsAbsent(proofPath)).toBe(true);
    await waitForPidExit(running.guardianPid);
    await waitForPidExit(running.applicationPid);
    safeToRemove = true;
  } catch (error) {
    if (error instanceof BackendSupervisorError && error.stoppedSafe) safeToRemove = true;
    throw error;
  } finally {
    if (safeToRemove) await rm(workspace, { force: true, recursive: true });
  }
}, 360_000);
