import { spawn } from "node:child_process";
import { randomBytes as nodeRandomBytes } from "node:crypto";
import path from "node:path";

import {
  BackendDrain,
  DEFAULT_BACKEND_DRAIN_TIMING,
  type BackendDrainEvidence,
  type BackendDrainEvidenceBoundary,
  type BackendDrainResult,
  type BackendDrainTiming,
} from "./backend-drain";
import { waitForBackendHealth } from "./backend-health";
import {
  finaliseBackendRecoveryRecord,
  provisionBackendMasterPassword,
} from "./backend-provision";
import { minimalChildEnvironment } from "./bootstrap-io";
import {
  activeSourcePythonPath,
  captureParentIdentity,
  parseParentIdentityOutput,
  sourceGuardianScriptPath,
  type ParentIdentityProof,
} from "./parent-identity";
import {
  GuardianProtocol,
  type GuardianEvent,
} from "./guardian-protocol";

const DEFAULT_START_TIMEOUT_MS = 180_000;
const DEFAULT_PRE_READY_DRAIN_TIMING: Readonly<BackendDrainTiming> = Object.freeze({
  containmentMs: 1_000,
  forceMs: 7_000,
  gracefulMs: 100,
});
const RECOVERY_RECORD_NAME = "desktop_backend.pid";
const MAX_DIAGNOSTIC_TAIL_BYTES = 4_096;
const MAX_PROCESS_ID = 0xffff_ffff;

export type BackendSupervisorFailureReason =
  | "blocked"
  | "cancelled"
  | "early-exit"
  | "health"
  | "parent-identity"
  | "protocol"
  | "provisioning"
  | "record-cleanup"
  | "setup"
  | "spawn"
  | "timeout";

export type BackendSupervisorStatus =
  | "idle"
  | "provisioning"
  | "probing-parent"
  | "starting"
  | "checking-health"
  | "ready"
  | "stopping"
  | "stopped"
  | "failed";

export interface BackendSupervisorState {
  applicationPid: number | null;
  attempt: number;
  failure: string | null;
  port: number | null;
  status: BackendSupervisorStatus;
  stoppedSafe: boolean;
}

export interface BackendExitEvent {
  error?: unknown;
  exitCode: number | null;
  signal: NodeJS.Signals | null;
}

export interface BackendSpawnInvocation {
  args: readonly string[];
  command: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
  onExit(event: BackendExitEvent): void;
  onStderr(chunk: Buffer): void;
  onStdout(chunk: Buffer): void;
}

export interface BackendSpawnHandle {
  readonly pid: number;
  /** True only when the complete owned containment is confirmed empty. */
  forceContainment(applicationPid: number | null): Promise<boolean>;
  writeStdin(command: string): Promise<void>;
}

export interface BackendSpawnBoundary {
  spawn(invocation: BackendSpawnInvocation): BackendSpawnHandle;
}

export interface BackendSupervisorClock {
  clearTimeout(handle: unknown): void;
  setTimeout(callback: () => void, milliseconds: number): unknown;
}

export interface BackendRecordFinaliseInput {
  applicationPid: number | null;
  bootId: string;
  environment: NodeJS.ProcessEnv;
  guardianPid: number;
  launchToken: string;
  parentIdentity: string;
  parentPid: number;
  platform: NodeJS.Platform;
  recordPath: string;
  sourceRoot: string;
}

export interface BackendSupervisorDependencies {
  captureParentIdentity?(input: {
    inheritedEnvironment: NodeJS.ProcessEnv;
    parentPid: number;
    platform: NodeJS.Platform;
    signal: AbortSignal;
    sourceRoot: string;
  }): Promise<ParentIdentityProof>;
  clock?: BackendSupervisorClock;
  finaliseRecord?(input: BackendRecordFinaliseInput): Promise<void>;
  health?(port: number, signal: AbortSignal): Promise<true>;
  provision?(input: {
    inheritedEnvironment: NodeJS.ProcessEnv;
    platform: NodeJS.Platform;
    signal: AbortSignal;
    sourceRoot: string;
    workspace: string;
  }): Promise<void>;
  randomBytes?(size: number): Buffer;
  spawn?: BackendSpawnBoundary;
}

export interface BackendSupervisorOptions {
  bootSessionIdentity: string;
  dependencies?: BackendSupervisorDependencies;
  drainTiming?: BackendDrainTiming;
  frontendDist: string;
  inheritedEnvironment?: NodeJS.ProcessEnv;
  onNotification?(event: { body: string; title: string }): void;
  onStableFailure?(error: BackendSupervisorError): void;
  onState?(state: Readonly<BackendSupervisorState>): void;
  onUnexpectedExit?(event: BackendExitEvent): void;
  parentPid?: number;
  platform?: NodeJS.Platform;
  preReadyDrainTiming?: BackendDrainTiming;
  sourceRoot: string;
  startTimeoutMs?: number;
  workspace: string;
}

export interface RunningBackend {
  readonly applicationPid: number;
  readonly attempt: number;
  readonly guardianPid: number;
  readonly launchToken: string;
  readonly port: number;
  readonly recordPath: string;
  readonly url: string;
  drain(): Promise<BackendDrainResult>;
}

export class BackendSupervisorError extends Error {
  readonly reason: BackendSupervisorFailureReason;
  readonly stoppedSafe: boolean;

  constructor(reason: BackendSupervisorFailureReason, message: string, cause?: unknown, stoppedSafe = false) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "BackendSupervisorError";
    this.reason = reason;
    this.stoppedSafe = stoppedSafe;
  }
}

interface EvidenceWaiter {
  afterRevision: number;
  reject(error: unknown): void;
  resolve(): void;
  signal: AbortSignal;
}

class SupervisorEvidence implements BackendDrainEvidenceBoundary {
  private state: BackendDrainEvidence = {
    childExited: false,
    cleanupTokens: [],
    containmentExited: false,
    pendingExitAcks: [],
    revision: 0,
  };
  private readonly waiters = new Set<EvidenceWaiter>();

  snapshot(): BackendDrainEvidence {
    return this.state;
  }

  waitForChange(afterRevision: number, signal: AbortSignal): Promise<void> {
    if (this.state.revision !== afterRevision) return Promise.resolve();
    if (signal.aborted) return Promise.reject(signal.reason);
    return new Promise((resolve, reject) => {
      const waiter: EvidenceWaiter = { afterRevision, reject, resolve, signal };
      const onAbort = (): void => {
        this.waiters.delete(waiter);
        reject(signal.reason);
      };
      this.waiters.add(waiter);
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  publish(patch: Partial<Omit<BackendDrainEvidence, "revision">>): void {
    this.state = {
      ...this.state,
      ...patch,
      cleanupTokens: patch.cleanupTokens ? [...patch.cleanupTokens] : this.state.cleanupTokens,
      pendingExitAcks: patch.pendingExitAcks ? [...patch.pendingExitAcks] : this.state.pendingExitAcks,
      revision: this.state.revision + 1,
    };
    for (const waiter of [...this.waiters]) {
      if (waiter.afterRevision === this.state.revision) continue;
      this.waiters.delete(waiter);
      waiter.resolve();
    }
  }
}

interface Deferred<T> {
  promise: Promise<T>;
  reject(error: unknown): void;
  resolve(value: T): void;
}

function deferred<T>(): Deferred<T> {
  let reject!: (error: unknown) => void;
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    reject = rejectPromise;
    resolve = resolvePromise;
  });
  void promise.catch(() => undefined);
  return { promise, reject, resolve };
}

interface Attempt {
  abort: AbortController;
  applicationPid: number | null;
  childExited: boolean;
  cleanupPromise: Promise<boolean> | null;
  environment: NodeJS.ProcessEnv | null;
  evidence: SupervisorEvidence;
  expectedStop: boolean;
  failure: BackendSupervisorError | null;
  finalisePromise: Promise<void> | null;
  handle: BackendSpawnHandle | null;
  id: number;
  launchToken: string | null;
  noRecordProof: boolean;
  parentIdentity: ParentIdentityProof | null;
  port: number | null;
  protocol: GuardianProtocol;
  protocolEventsSeen: number;
  publicDrainPromise: Promise<BackendDrainResult> | null;
  ready: boolean;
  readyDeferred: Deferred<RunningBackend> | null;
  startupEventsAccepted: boolean;
  stderrTail: string;
  watchdog: unknown | null;
}

interface ResolvedDependencies {
  captureParentIdentity: NonNullable<BackendSupervisorDependencies["captureParentIdentity"]>;
  clock: BackendSupervisorClock;
  finaliseRecord: NonNullable<BackendSupervisorDependencies["finaliseRecord"]>;
  health: NonNullable<BackendSupervisorDependencies["health"]>;
  provision: NonNullable<BackendSupervisorDependencies["provision"]>;
  randomBytes: NonNullable<BackendSupervisorDependencies["randomBytes"]>;
  spawn: BackendSpawnBoundary;
}

const NODE_CLOCK: BackendSupervisorClock = {
  clearTimeout(handle) {
    clearTimeout(handle as ReturnType<typeof setTimeout>);
  },
  setTimeout(callback, milliseconds) {
    return setTimeout(callback, milliseconds);
  },
};

function validPid(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 1 && value <= MAX_PROCESS_ID;
}

function validTiming(timing: BackendDrainTiming): boolean {
  return Object.values(timing).every((value) => Number.isSafeInteger(value) && value > 0);
}

function platformPath(platform: NodeJS.Platform): typeof path.posix {
  return platform === "win32" ? path.win32 : path.posix;
}

function appendUtf8Tail(current: string, chunk: Buffer, maximumBytes: number): string {
  const combined = Buffer.concat([Buffer.from(current, "utf8"), chunk]);
  if (combined.byteLength <= maximumBytes) return combined.toString("utf8");
  return combined.subarray(combined.byteLength - maximumBytes).toString("utf8");
}

export function normaliseGuardianBootIdentity(raw: string): string {
  if (raw.length === 0 || Buffer.byteLength(raw, "utf8") > 256 || raw.trim() !== raw) {
    throw new BackendSupervisorError("setup", "Backend boot-session identity is invalid.");
  }
  const normalised = Buffer.from(raw, "utf8").toString("hex");
  if (normalised.length < 16 || normalised.length > 512 || normalised.length % 2 !== 0) {
    throw new BackendSupervisorError("setup", "Backend boot-session identity is invalid.");
  }
  return normalised;
}

export interface CreateBackendEnvironmentInput {
  bootSessionIdentity: string;
  frontendDist: string;
  inheritedEnvironment?: NodeJS.ProcessEnv;
  launchToken: string;
  parentIdentity: ParentIdentityProof;
  parentPid: number;
  platform?: NodeJS.Platform;
  recordPath: string;
  workspace: string;
}

export function createBackendEnvironment(input: CreateBackendEnvironmentInput): NodeJS.ProcessEnv {
  const platform = input.platform ?? process.platform;
  let verifiedParent: ParentIdentityProof;
  try {
    verifiedParent = parseParentIdentityOutput(
      `FLINTTRADE_PARENT_IDENTITY ${input.parentIdentity.raw}\n`,
      input.parentPid,
    );
  } catch (error) {
    throw new BackendSupervisorError("setup", "Backend launch identity is invalid.", error);
  }
  if (!/^[0-9a-f]{64}$/.test(input.launchToken) || !validPid(input.parentPid)
    || input.parentIdentity.parentPid !== input.parentPid
    || verifiedParent.platform !== input.parentIdentity.platform
    || verifiedParent.raw !== input.parentIdentity.raw) {
    throw new BackendSupervisorError("setup", "Backend launch identity is invalid.");
  }
  const environment = minimalChildEnvironment(
    { PYTHONNOUSERSITE: "1" },
    input.inheritedEnvironment,
    platform,
  );
  Object.assign(environment, {
    FLINTTRADE_BOOT_ID: normaliseGuardianBootIdentity(input.bootSessionIdentity),
    FLINTTRADE_DESKTOP: "1",
    FLINTTRADE_FRONTEND_DIST: input.frontendDist,
    FLINTTRADE_LAUNCH_TOKEN: input.launchToken,
    FLINTTRADE_PARENT_IDENTITY: input.parentIdentity.raw,
    FLINTTRADE_PARENT_PID: String(input.parentPid),
    FLINTTRADE_SIDECAR_RECORD_PATH: input.recordPath,
    FLINTTRADE_WORKSPACE_DIR: input.workspace,
  });
  return environment;
}

export function createNodeBackendSpawnBoundary(
  platform: NodeJS.Platform = process.platform,
): BackendSpawnBoundary {
  return {
    spawn(invocation) {
      const child = spawn(invocation.command, [...invocation.args], {
        cwd: invocation.cwd,
        env: invocation.env,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      });
      let closed = false;
      let stdinError: Error | null = null;
      const publishExit = (event: BackendExitEvent): void => {
        if (closed) return;
        closed = true;
        invocation.onExit(event);
      };
      child.stdout.on("data", (chunk: Buffer) => invocation.onStdout(chunk));
      child.stderr.on("data", (chunk: Buffer) => invocation.onStderr(chunk));
      child.stdin.on("error", (error) => {
        stdinError = error;
      });
      child.once("error", (error) => publishExit({ error, exitCode: null, signal: null }));
      child.once("close", (exitCode, signal) => publishExit({ exitCode, signal }));
      if (!child.pid || !validPid(child.pid)) {
        child.kill("SIGKILL");
        throw new BackendSupervisorError("spawn", "Backend guardian did not receive a valid process ID.");
      }
      return {
        pid: child.pid,
        async forceContainment(_applicationPid) {
          if (closed) return false;
          // Signal only the exact child handle still owned by Electron. The
          // Python guardian's installed POSIX handler owns identity-bound tree
          // containment; Electron must never signal a reusable numeric app PID
          // or destroy the guardian that retains the workspace lease.
          if (platform !== "win32") child.kill("SIGTERM");
          return false;
        },
        writeStdin(command) {
          if (closed || stdinError || !child.stdin.writable) {
            return Promise.reject(stdinError ?? new Error("backend guardian stdin is closed"));
          }
          return new Promise<void>((resolve, reject) => {
            child.stdin.write(command, (error) => {
              if (error || stdinError) reject(error ?? stdinError);
              else resolve();
            });
          });
        },
      };
    },
  };
}

function closedDrainResult(attempt: Attempt): BackendDrainResult | null {
  if (!attempt.childExited) return null;
  const evidence = attempt.evidence.snapshot();
  const token = attempt.launchToken;
  if (token !== null && evidence.cleanupTokens.includes(token)) {
    return {
      childExited: true,
      containmentExited: evidence.containmentExited,
      outcome: "clean",
      phase: "graceful",
      proof: "cleanup-complete",
      recordRemovalSafe: true,
    };
  }
  if (token !== null && attempt.applicationPid === null
    && evidence.pendingExitAcks.some((ack) => ack.token === token)) {
    return {
      childExited: true,
      containmentExited: evidence.containmentExited,
      outcome: "clean",
      phase: "force",
      proof: "pending-exit-ack",
      recordRemovalSafe: true,
    };
  }
  return {
    childExited: true,
    containmentExited: evidence.containmentExited,
    outcome: evidence.containmentExited ? "contained" : "unresolved",
    phase: "containment",
    proof: null,
    recordRemovalSafe: false,
  };
}

/** Attempt-scoped source guardian supervisor. */
export class BackendSupervisor {
  private readonly bootSessionIdentity: string;
  private readonly dependencies: ResolvedDependencies;
  private readonly drainTiming: BackendDrainTiming;
  private readonly frontendDist: string;
  private readonly inheritedEnvironment: NodeJS.ProcessEnv;
  private readonly onNotification?: BackendSupervisorOptions["onNotification"];
  private readonly onStableFailure?: BackendSupervisorOptions["onStableFailure"];
  private readonly onState?: BackendSupervisorOptions["onState"];
  private readonly onUnexpectedExit?: BackendSupervisorOptions["onUnexpectedExit"];
  private readonly parentPid: number;
  private readonly platform: NodeJS.Platform;
  private readonly preReadyDrainTiming: BackendDrainTiming;
  private readonly recordPath: string;
  private readonly sourceRoot: string;
  private readonly startTimeoutMs: number;
  private readonly workspace: string;
  private attemptSequence = 0;
  private current: Attempt | null = null;
  private recordInterlock: BackendSupervisorError | null = null;
  private state: Readonly<BackendSupervisorState> = Object.freeze({
    applicationPid: null,
    attempt: 0,
    failure: null,
    port: null,
    status: "idle",
    stoppedSafe: true,
  });

  constructor(options: BackendSupervisorOptions) {
    const platform = options.platform ?? process.platform;
    const pathApi = platformPath(platform);
    const parentPid = options.parentPid ?? process.pid;
    const startTimeoutMs = options.startTimeoutMs ?? DEFAULT_START_TIMEOUT_MS;
    const drainTiming = options.drainTiming ?? DEFAULT_BACKEND_DRAIN_TIMING;
    const preReadyDrainTiming = options.preReadyDrainTiming ?? options.drainTiming ?? DEFAULT_PRE_READY_DRAIN_TIMING;
    if (!["darwin", "linux", "win32"].includes(platform)
      || !pathApi.isAbsolute(options.sourceRoot)
      || !pathApi.isAbsolute(options.workspace)
      || !pathApi.isAbsolute(options.frontendDist)
      || !validPid(parentPid)
      || !Number.isSafeInteger(startTimeoutMs) || startTimeoutMs <= 0
      || !validTiming(drainTiming) || !validTiming(preReadyDrainTiming)) {
      throw new BackendSupervisorError("setup", "Backend supervisor inputs are invalid.");
    }
    normaliseGuardianBootIdentity(options.bootSessionIdentity);
    this.platform = platform;
    this.sourceRoot = options.sourceRoot;
    this.workspace = options.workspace;
    this.frontendDist = options.frontendDist;
    this.recordPath = pathApi.join(options.workspace, RECOVERY_RECORD_NAME);
    this.bootSessionIdentity = options.bootSessionIdentity;
    this.parentPid = parentPid;
    this.startTimeoutMs = startTimeoutMs;
    this.drainTiming = { ...drainTiming };
    this.preReadyDrainTiming = { ...preReadyDrainTiming };
    this.inheritedEnvironment = { ...(options.inheritedEnvironment ?? process.env) };
    this.onNotification = options.onNotification;
    this.onStableFailure = options.onStableFailure;
    this.onState = options.onState;
    this.onUnexpectedExit = options.onUnexpectedExit;
    const injected = options.dependencies ?? {};
    this.dependencies = {
      captureParentIdentity: injected.captureParentIdentity ?? ((input) => captureParentIdentity(input)),
      clock: injected.clock ?? NODE_CLOCK,
      finaliseRecord: injected.finaliseRecord ?? ((input) => finaliseBackendRecoveryRecord({
        applicationPid: input.applicationPid,
        env: input.environment,
        guardianPid: input.guardianPid,
        platform: input.platform,
        sourceRoot: input.sourceRoot,
      })),
      health: injected.health ?? ((port, signal) => waitForBackendHealth({
        port,
        signal,
        timeoutMs: this.startTimeoutMs,
      })),
      provision: injected.provision ?? ((input) => provisionBackendMasterPassword(input)),
      randomBytes: injected.randomBytes ?? nodeRandomBytes,
      spawn: injected.spawn ?? createNodeBackendSpawnBoundary(platform),
    };
  }

  getState(): Readonly<BackendSupervisorState> {
    return this.state;
  }

  start(): Promise<RunningBackend> {
    if (this.recordInterlock) return Promise.reject(this.recordInterlock);
    const previous = this.current;
    if (previous?.ready && !previous.childExited) {
      return Promise.reject(new BackendSupervisorError("setup", "A backend is already running."));
    }
    const attempt = this.createAttempt();
    this.current = attempt;
    const previousSettlement = previous && !previous.ready
      ? this.cancelAttempt(previous, true)
      : previous?.cleanupPromise ?? Promise.resolve(true);
    return this.runAttempt(attempt, previousSettlement);
  }

  async cancelCurrent(): Promise<void> {
    const attempt = this.current;
    if (!attempt || attempt.ready) return;
    await this.cancelAttempt(attempt, false);
  }

  private createAttempt(): Attempt {
    return {
      abort: new AbortController(),
      applicationPid: null,
      childExited: false,
      cleanupPromise: null,
      environment: null,
      evidence: new SupervisorEvidence(),
      expectedStop: false,
      failure: null,
      finalisePromise: null,
      handle: null,
      id: ++this.attemptSequence,
      launchToken: null,
      noRecordProof: false,
      parentIdentity: null,
      port: null,
      protocol: new GuardianProtocol(),
      protocolEventsSeen: 0,
      publicDrainPromise: null,
      ready: false,
      readyDeferred: null,
      startupEventsAccepted: true,
      stderrTail: "",
      watchdog: null,
    };
  }

  private publish(attempt: Attempt, patch: Partial<Omit<BackendSupervisorState, "attempt">>): void {
    if (this.current !== attempt) return;
    this.state = Object.freeze({ ...this.state, ...patch, attempt: attempt.id });
    try {
      this.onState?.(this.state);
    } catch {
      // Lifecycle state is authoritative; observers cannot roll it back.
    }
  }

  private assertCurrent(attempt: Attempt): void {
    if (this.current !== attempt || attempt.abort.signal.aborted || attempt.failure) {
      throw attempt.failure ?? new BackendSupervisorError("cancelled", "Backend start was cancelled.");
    }
    if (this.recordInterlock) throw this.recordInterlock;
  }

  private async runAttempt(attempt: Attempt, previousSettlement: Promise<boolean>): Promise<RunningBackend> {
    try {
      const previousSafe = await previousSettlement;
      if (!previousSafe) throw this.recordInterlock
        ?? new BackendSupervisorError("record-cleanup", "Previous backend cleanup could not be proved.");
      this.assertCurrent(attempt);
      this.publish(attempt, {
        applicationPid: null,
        failure: null,
        port: null,
        status: "provisioning",
        stoppedSafe: false,
      });
      await this.dependencies.provision({
        inheritedEnvironment: this.inheritedEnvironment,
        platform: this.platform,
        signal: attempt.abort.signal,
        sourceRoot: this.sourceRoot,
        workspace: this.workspace,
      });
      this.assertCurrent(attempt);
      this.publish(attempt, { status: "probing-parent" });
      const parentIdentity = await this.dependencies.captureParentIdentity({
        inheritedEnvironment: this.inheritedEnvironment,
        parentPid: this.parentPid,
        platform: this.platform,
        signal: attempt.abort.signal,
        sourceRoot: this.sourceRoot,
      });
      this.assertCurrent(attempt);
      if (parentIdentity.parentPid !== this.parentPid || parentIdentity.platform !== this.platform) {
        throw new BackendSupervisorError("parent-identity", "Backend parent identity did not match Electron.");
      }
      attempt.parentIdentity = parentIdentity;

      // The token exists only after the exact direct-parent generation was captured.
      const tokenBytes = this.dependencies.randomBytes(32);
      if (!Buffer.isBuffer(tokenBytes) || tokenBytes.byteLength !== 32) {
        throw new BackendSupervisorError("setup", "Backend launch-token generation failed.");
      }
      const launchToken = tokenBytes.toString("hex");
      if (!/^[0-9a-f]{64}$/.test(launchToken)) {
        throw new BackendSupervisorError("setup", "Backend launch-token generation failed.");
      }
      attempt.launchToken = launchToken;
      attempt.environment = createBackendEnvironment({
        bootSessionIdentity: this.bootSessionIdentity,
        frontendDist: this.frontendDist,
        inheritedEnvironment: this.inheritedEnvironment,
        launchToken,
        parentIdentity,
        parentPid: this.parentPid,
        platform: this.platform,
        recordPath: this.recordPath,
        workspace: this.workspace,
      });
      attempt.readyDeferred = deferred<RunningBackend>();
      this.publish(attempt, { status: "starting" });
      try {
        attempt.handle = this.dependencies.spawn.spawn({
          args: [sourceGuardianScriptPath(this.sourceRoot, this.platform), "--port", "0"],
          command: activeSourcePythonPath(this.sourceRoot, this.platform),
          cwd: this.sourceRoot,
          env: attempt.environment,
          onExit: (event) => this.handleExit(attempt, event),
          onStderr: (chunk) => {
            attempt.stderrTail = appendUtf8Tail(attempt.stderrTail, chunk, MAX_DIAGNOSTIC_TAIL_BYTES);
          },
          onStdout: (chunk) => this.handleStdout(attempt, chunk),
        });
      } catch (error) {
        throw error instanceof BackendSupervisorError
          ? error
          : new BackendSupervisorError("spawn", "Backend guardian could not be started.", error);
      }
      if (!validPid(attempt.handle.pid)) {
        throw new BackendSupervisorError("spawn", "Backend guardian did not receive a valid process ID.");
      }
      attempt.watchdog = this.dependencies.clock.setTimeout(() => {
        void this.failAttempt(
          attempt,
          new BackendSupervisorError("timeout", "Backend start timed out before readiness."),
        );
      }, this.startTimeoutMs);
      return await attempt.readyDeferred.promise;
    } catch (error) {
      const mapped = this.mapStartError(attempt, error);
      if (!attempt.failure) await this.failAttempt(attempt, mapped);
      throw attempt.failure ?? mapped;
    }
  }

  private mapStartError(attempt: Attempt, error: unknown): BackendSupervisorError {
    if (attempt.failure) return attempt.failure;
    if (error instanceof BackendSupervisorError) return error;
    if (attempt.abort.signal.aborted) {
      return new BackendSupervisorError("cancelled", "Backend start was cancelled.");
    }
    switch (this.state.status) {
      case "provisioning":
        return new BackendSupervisorError("provisioning", "Backend credential provisioning failed.");
      case "probing-parent":
        return new BackendSupervisorError("parent-identity", "Backend parent identity probe failed.");
      default:
        return new BackendSupervisorError("spawn", "Backend guardian could not be started.");
    }
  }

  private handleStdout(attempt: Attempt, chunk: Buffer): void {
    if (attempt.childExited) return;
    for (const event of attempt.protocol.feed(chunk)) this.handleProtocolEvent(attempt, event);
  }

  private handleProtocolEvent(attempt: Attempt, event: GuardianEvent): void {
    const isFirstProtocolEvent = attempt.protocolEventsSeen === 0;
    attempt.protocolEventsSeen += 1;
    if (event.type === "cleanup-complete") {
      const current = attempt.evidence.snapshot();
      attempt.evidence.publish({ cleanupTokens: [...current.cleanupTokens, event.token] });
      return;
    }
    if (event.type === "pending-exit-ack") {
      const current = attempt.evidence.snapshot();
      attempt.evidence.publish({ pendingExitAcks: [...current.pendingExitAcks, {
        reason: event.reason,
        token: event.token,
      }] });
      return;
    }
    if (!attempt.startupEventsAccepted || attempt.childExited) return;
    if (event.type === "notification") {
      try {
        this.onNotification?.({ body: event.body, title: event.title });
      } catch {
        // Parsed native notifications are advisory and cannot own lifecycle.
      }
      return;
    }
    if (event.type === "blocked") {
      if (!isFirstProtocolEvent || attempt.applicationPid !== null || attempt.port !== null || attempt.ready) {
        void this.failAttempt(
          attempt,
          new BackendSupervisorError("protocol", "Backend guardian emitted an invalid blocked sequence."),
        );
        return;
      }
      attempt.noRecordProof = event.reason === "instance-lease";
      void this.failAttempt(
        attempt,
        new BackendSupervisorError("blocked", "Backend startup was blocked by another workspace owner."),
      );
      return;
    }
    if (event.type === "application-pid") {
      if (attempt.applicationPid !== null || attempt.port !== null) {
        void this.failAttempt(
          attempt,
          new BackendSupervisorError("protocol", "Backend guardian emitted an invalid application-PID sequence."),
        );
        return;
      }
      attempt.applicationPid = event.pid;
      this.publish(attempt, { applicationPid: event.pid });
      return;
    }
    if (event.type === "ready") {
      if (attempt.applicationPid === null || attempt.port !== null) {
        void this.failAttempt(
          attempt,
          new BackendSupervisorError("protocol", "Backend guardian emitted readiness before its application PID."),
        );
        return;
      }
      attempt.port = event.port;
      this.publish(attempt, { port: event.port, status: "checking-health" });
      void this.finishHealth(attempt, event.port);
    }
  }

  private async finishHealth(attempt: Attempt, port: number): Promise<void> {
    try {
      await this.dependencies.health(port, attempt.abort.signal);
      this.assertCurrent(attempt);
      if (attempt.childExited || attempt.applicationPid === null || attempt.handle === null
        || attempt.launchToken === null || attempt.parentIdentity === null || attempt.environment === null) {
        throw new BackendSupervisorError("early-exit", "Backend guardian exited before health proof completed.");
      }
      attempt.ready = true;
      this.clearWatchdog(attempt);
      const running = this.createRunningBackend(attempt);
      this.publish(attempt, { failure: null, status: "ready" });
      attempt.readyDeferred?.resolve(running);
    } catch (error) {
      if (attempt.failure) return;
      await this.failAttempt(
        attempt,
        error instanceof BackendSupervisorError
          ? error
          : new BackendSupervisorError("health", "Backend loopback health proof failed."),
      );
    }
  }

  private handleExit(attempt: Attempt, event: BackendExitEvent): void {
    if (attempt.childExited) return;
    for (const protocolEvent of attempt.protocol.end()) this.handleProtocolEvent(attempt, protocolEvent);
    attempt.childExited = true;
    attempt.evidence.publish({ childExited: true });
    this.clearWatchdog(attempt);
    if (attempt.expectedStop) return;
    if (!attempt.ready) {
      void this.failAttempt(
        attempt,
        new BackendSupervisorError("early-exit", "Backend guardian exited before readiness."),
      );
      return;
    }
    attempt.startupEventsAccepted = false;
    this.publish(attempt, {
      failure: "The trading engine stopped unexpectedly.",
      status: "failed",
      stoppedSafe: false,
    });
    attempt.cleanupPromise = this.finaliseClosedAttemptIfProven(attempt);
    try {
      this.onUnexpectedExit?.(event);
    } catch {
      // Recovery state is authoritative; a callback cannot suppress it.
    }
  }

  private async failAttempt(attempt: Attempt, error: BackendSupervisorError): Promise<boolean> {
    if (attempt.failure) return attempt.cleanupPromise ?? false;
    attempt.failure = error;
    attempt.startupEventsAccepted = false;
    attempt.abort.abort(error);
    this.clearWatchdog(attempt);
    if (this.current === attempt) {
      this.publish(attempt, { failure: error.message, status: "failed" });
      if (error.reason !== "cancelled") {
        try {
          this.onStableFailure?.(error);
        } catch {
          // A recovery observer cannot change the stable failure.
        }
      }
    }
    attempt.cleanupPromise ??= attempt.handle
      ? this.drainAndFinalise(attempt, this.preReadyDrainTiming)
      : Promise.resolve(true);
    const safe = await attempt.cleanupPromise;
    const settledError = error.stoppedSafe === safe
      ? error
      : new BackendSupervisorError(error.reason, error.message, error.cause, safe);
    attempt.failure = settledError;
    this.publish(attempt, { stoppedSafe: safe });
    attempt.readyDeferred?.reject(settledError);
    return safe;
  }

  private cancelAttempt(attempt: Attempt, superseded: boolean): Promise<boolean> {
    if (attempt.failure) return attempt.cleanupPromise ?? Promise.resolve(!this.recordInterlock);
    const error = new BackendSupervisorError("cancelled", "Backend start was cancelled.");
    if (superseded && this.current !== attempt) {
      attempt.failure = error;
      attempt.startupEventsAccepted = false;
      attempt.abort.abort(error);
      this.clearWatchdog(attempt);
      attempt.cleanupPromise ??= attempt.handle
        ? this.drainAndFinalise(attempt, this.preReadyDrainTiming)
        : Promise.resolve(true);
      void attempt.cleanupPromise.then((safe) => {
        const settledError = new BackendSupervisorError(error.reason, error.message, error.cause, safe);
        attempt.failure = settledError;
        attempt.readyDeferred?.reject(settledError);
      });
      return attempt.cleanupPromise;
    }
    return this.failAttempt(attempt, error);
  }

  private createRunningBackend(attempt: Attempt): RunningBackend {
    const applicationPid = attempt.applicationPid!;
    const guardianPid = attempt.handle!.pid;
    const launchToken = attempt.launchToken!;
    const port = attempt.port!;
    return Object.freeze({
      applicationPid,
      attempt: attempt.id,
      guardianPid,
      launchToken,
      port,
      recordPath: this.recordPath,
      url: `http://127.0.0.1:${port}`,
      drain: (): Promise<BackendDrainResult> => {
        if (!attempt.publicDrainPromise) {
          attempt.publicDrainPromise = this.drainRunningAttempt(attempt);
          attempt.cleanupPromise = attempt.publicDrainPromise.then(
            (result) => result.recordRemovalSafe && result.childExited && this.recordInterlock === null,
            () => false,
          );
        }
        return attempt.publicDrainPromise;
      },
    });
  }

  private async drainRunningAttempt(attempt: Attempt): Promise<BackendDrainResult> {
    attempt.expectedStop = true;
    attempt.startupEventsAccepted = false;
    this.publish(attempt, { status: "stopping", stoppedSafe: false });
    const result = await this.drainAttempt(attempt, this.drainTiming);
    if (!result.recordRemovalSafe || !result.childExited) {
      this.blockOnRecordCleanup(attempt, "Backend cleanup could not be proved; recovery state was retained.");
      return result;
    }
    try {
      await this.finaliseAttemptRecord(attempt);
    } catch (error) {
      const failure = this.blockOnRecordCleanup(
        attempt,
        "Backend recovery-record finalisation failed; recovery state was retained.",
        error,
      );
      throw failure;
    }
    this.publish(attempt, {
      applicationPid: null,
      failure: null,
      port: null,
      status: "stopped",
      stoppedSafe: true,
    });
    return result;
  }

  private async drainAndFinalise(attempt: Attempt, timing: BackendDrainTiming): Promise<boolean> {
    const result = await this.drainAttempt(attempt, timing);
    if (attempt.noRecordProof && result.childExited) {
      this.publish(attempt, { stoppedSafe: true });
      return true;
    }
    if (!result.recordRemovalSafe || !result.childExited) {
      this.blockOnRecordCleanup(attempt, "Backend cleanup could not be proved; recovery state was retained.");
      return false;
    }
    try {
      // Pending ACK proves the token-bound pending record is safe to clear, not
      // that a prior clear necessarily succeeded. Managed Python performs the
      // idempotent present-or-exact-absence finalisation under its transition lock.
      await this.finaliseAttemptRecord(attempt);
      this.publish(attempt, { stoppedSafe: true });
      return true;
    } catch (error) {
      this.blockOnRecordCleanup(
        attempt,
        "Backend recovery-record finalisation failed; recovery state was retained.",
        error,
      );
      return false;
    }
  }

  private async drainAttempt(attempt: Attempt, timing: BackendDrainTiming): Promise<BackendDrainResult> {
    const closed = closedDrainResult(attempt);
    if (closed) return closed;
    const handle = attempt.handle;
    const launchToken = attempt.launchToken;
    if (!handle || !launchToken) {
      return {
        childExited: attempt.childExited,
        containmentExited: false,
        outcome: "unresolved",
        phase: "containment",
        proof: null,
        recordRemovalSafe: false,
      };
    }
    return new BackendDrain({
      applicationPid: attempt.applicationPid,
      evidence: attempt.evidence,
      forceContainment: async () => {
        if (await handle.forceContainment(attempt.applicationPid)) {
          attempt.evidence.publish({ containmentExited: true });
        }
      },
      launchToken,
      writeStdin: (command) => attempt.childExited ? Promise.resolve() : handle.writeStdin(command),
    }, timing).drain();
  }

  private finaliseAttemptRecord(attempt: Attempt): Promise<void> {
    if (attempt.finalisePromise) return attempt.finalisePromise;
    if (!attempt.childExited || !attempt.handle || !attempt.launchToken
      || !attempt.parentIdentity || !attempt.environment) {
      return Promise.reject(new BackendSupervisorError(
        "record-cleanup",
        "Backend recovery record cannot be finalised without exact stopped-process evidence.",
      ));
    }
    attempt.finalisePromise = this.dependencies.finaliseRecord({
      applicationPid: attempt.applicationPid,
      bootId: normaliseGuardianBootIdentity(this.bootSessionIdentity),
      environment: attempt.environment,
      guardianPid: attempt.handle.pid,
      launchToken: attempt.launchToken,
      parentIdentity: attempt.parentIdentity.raw,
      parentPid: this.parentPid,
      platform: this.platform,
      recordPath: this.recordPath,
      sourceRoot: this.sourceRoot,
    });
    return attempt.finalisePromise;
  }

  private async finaliseClosedAttemptIfProven(attempt: Attempt): Promise<boolean> {
    const result = closedDrainResult(attempt);
    if (!result?.recordRemovalSafe) {
      this.blockOnRecordCleanup(attempt, "Unexpected backend exit left unproved recovery state.");
      return false;
    }
    try {
      await this.finaliseAttemptRecord(attempt);
      this.publish(attempt, { stoppedSafe: true });
      return true;
    } catch (error) {
      this.blockOnRecordCleanup(
        attempt,
        "Backend recovery-record finalisation failed; recovery state was retained.",
        error,
      );
      return false;
    }
  }

  private blockOnRecordCleanup(attempt: Attempt, message: string, cause?: unknown): BackendSupervisorError {
    const failure = new BackendSupervisorError("record-cleanup", message, cause);
    this.recordInterlock ??= failure;
    this.publish(attempt, { failure: failure.message, status: "failed", stoppedSafe: false });
    return failure;
  }

  private clearWatchdog(attempt: Attempt): void {
    if (attempt.watchdog === null) return;
    this.dependencies.clock.clearTimeout(attempt.watchdog);
    attempt.watchdog = null;
  }
}
