import type { GuardianPendingExitReason } from "./guardian-protocol";

export const SHUTDOWN_COMMAND = "FLINTTRADE_SHUTDOWN\n";
export const FORCE_EXIT_COMMAND = "FLINTTRADE_FORCE_EXIT\n";

export interface BackendDrainTiming {
  containmentMs: number;
  forceMs: number;
  gracefulMs: number;
}

export const DEFAULT_BACKEND_DRAIN_TIMING: Readonly<BackendDrainTiming> = Object.freeze({
  containmentMs: 1_000,
  forceMs: 7_000,
  gracefulMs: 302_000,
});

export interface BackendPendingExitAck {
  reason: GuardianPendingExitReason;
  token: string;
}

export interface BackendDrainEvidence {
  /** Confirmed exit of the exact guardian child launched by Electron. */
  childExited: boolean;
  /** Exact tokens parsed from complete cleanup-proof protocol lines. */
  cleanupTokens: readonly string[];
  /** Confirmation that the owned OS containment is empty or closed. */
  containmentExited: boolean;
  /** Exact pending-record ACKs parsed from complete protocol lines. */
  pendingExitAcks: readonly BackendPendingExitAck[];
  /** Monotonic revision used to avoid snapshot/subscription races. */
  revision: number;
}

export interface BackendDrainEvidenceBoundary {
  snapshot(): BackendDrainEvidence;
  waitForChange(afterRevision: number, signal: AbortSignal): Promise<void>;
}

export interface BackendDrainTarget {
  /** Null until the exact application-PID sentinel has been confirmed. */
  applicationPid: number | null;
  evidence: BackendDrainEvidenceBoundary;
  forceContainment(): Promise<void>;
  launchToken: string;
  writeStdin(command: string): Promise<void>;
}

export type BackendDrainOutcome = "clean" | "contained" | "unresolved";
export type BackendDrainPhase = "containment" | "force" | "graceful";
export type BackendDrainProof = "cleanup-complete" | "pending-exit-ack";

export interface BackendDrainResult {
  childExited: boolean;
  containmentExited: boolean;
  outcome: BackendDrainOutcome;
  phase: BackendDrainPhase;
  proof: BackendDrainProof | null;
  recordRemovalSafe: boolean;
}

function validateTiming(timing: BackendDrainTiming): void {
  for (const [label, value] of Object.entries(timing)) {
    if (!Number.isSafeInteger(value) || value <= 0) {
      throw new RangeError(`Backend drain ${label} must be a positive safe integer.`);
    }
  }
}

function abortable<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<T>((resolve, reject) => {
    const finish = (callback: (value: T | unknown) => void, value: T | unknown): void => {
      signal.removeEventListener("abort", onAbort);
      callback(value);
    };
    const onAbort = (): void => finish(reject, signal.reason);
    signal.addEventListener("abort", onAbort, { once: true });
    operation.then(
      (value) => finish(resolve as (value: T | unknown) => void, value),
      (error: unknown) => finish(reject, error),
    );
  });
}

/** One-shot asynchronous graceful/force/containment shutdown coordinator. */
export class BackendDrain {
  private drainPromise: Promise<BackendDrainResult> | null = null;
  private readonly target: BackendDrainTarget;
  private readonly timing: BackendDrainTiming;

  constructor(target: BackendDrainTarget, timing: BackendDrainTiming = DEFAULT_BACKEND_DRAIN_TIMING) {
    if (!/^[0-9a-fA-F]{64}$/.test(target.launchToken)) {
      throw new TypeError("Backend drain launch token must be exactly 64 hexadecimal characters.");
    }
    if (target.applicationPid !== null
      && (!Number.isSafeInteger(target.applicationPid) || target.applicationPid <= 0 || target.applicationPid > 0xffff_ffff)) {
      throw new TypeError("Backend drain application PID is invalid.");
    }
    validateTiming(timing);
    this.target = target;
    this.timing = { ...timing };
  }

  drain(): Promise<BackendDrainResult> {
    this.drainPromise ??= this.performDrain();
    return this.drainPromise;
  }

  private async performDrain(): Promise<BackendDrainResult> {
    const graceful = await this.runCommandPhase(SHUTDOWN_COMMAND, this.timing.gracefulMs);
    if (graceful) return this.cleanResult("graceful", graceful.evidence, graceful.proof);

    const forced = await this.runCommandPhase(FORCE_EXIT_COMMAND, this.timing.forceMs);
    if (forced) return this.cleanResult("force", forced.evidence, forced.proof);

    const containedProof = await this.runContainmentPhase();
    if (containedProof) return this.cleanResult("containment", containedProof.evidence, containedProof.proof);

    const evidence = this.target.evidence.snapshot();
    const contained = evidence.childExited && evidence.containmentExited;
    return {
      childExited: evidence.childExited,
      containmentExited: evidence.containmentExited,
      outcome: contained ? "contained" : "unresolved",
      phase: "containment",
      proof: null,
      recordRemovalSafe: false,
    };
  }

  private async runCommandPhase(command: string, milliseconds: number): Promise<{
    evidence: BackendDrainEvidence;
    proof: BackendDrainProof;
  } | null> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error("backend drain phase elapsed")), milliseconds);
    try {
      await abortable(this.target.writeStdin(command), controller.signal);
      return await this.waitForSafeProof(controller.signal);
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  private async runContainmentPhase(): Promise<{
    evidence: BackendDrainEvidence;
    proof: BackendDrainProof;
  } | null> {
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(new Error("backend containment opportunity elapsed")),
      this.timing.containmentMs,
    );
    try {
      // Request containment immediately, but do not let a stuck adapter keep
      // Electron's quit path alive beyond the bounded confirmation window.
      try {
        void this.target.forceContainment().catch(() => undefined);
      } catch {
        // Fail closed below: unresolved containment keeps the recovery record.
      }
      return await this.waitForSafeProof(controller.signal);
    } finally {
      clearTimeout(timer);
    }
  }

  private proofFrom(evidence: BackendDrainEvidence): BackendDrainProof | null {
    if (!evidence.childExited) return null;
    if (evidence.cleanupTokens.some((token) => token === this.target.launchToken)) return "cleanup-complete";
    if (this.target.applicationPid === null
      && evidence.pendingExitAcks.some((ack) => ack.token === this.target.launchToken
        && (ack.reason === "force-exit" || ack.reason === "promotion-failed"))) {
      return "pending-exit-ack";
    }
    return null;
  }

  private async waitForSafeProof(signal: AbortSignal): Promise<{
    evidence: BackendDrainEvidence;
    proof: BackendDrainProof;
  } | null> {
    while (true) {
      const evidence = this.target.evidence.snapshot();
      const proof = this.proofFrom(evidence);
      if (proof) return { evidence, proof };
      try {
        await abortable(
          this.target.evidence.waitForChange(evidence.revision, signal),
          signal,
        );
      } catch {
        return null;
      }
    }
  }

  private cleanResult(
    phase: BackendDrainPhase,
    evidence: BackendDrainEvidence,
    proof: BackendDrainProof,
  ): BackendDrainResult {
    return {
      childExited: evidence.childExited,
      containmentExited: evidence.containmentExited,
      outcome: "clean",
      phase,
      proof,
      recordRemovalSafe: true,
    };
  }
}
