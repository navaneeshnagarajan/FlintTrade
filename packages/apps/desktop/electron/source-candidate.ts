import path from "node:path";

import {
  createFirstRunBootstrap,
  type BootstrapOptions,
  type BootstrapProvenance,
  type BootstrapResult,
  type FileSystemIdentity,
} from "./bootstrap";
import {
  SourceOperationLeaseRetentionError,
  isSourceOperationLeaseRetentionError,
  type SourceOperationLeaseProof,
} from "./source-operation";
import { createBootstrapState } from "./state";

const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const UPDATE_CANDIDATE_PATTERN = /^FlintTrade\.update-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

interface BootstrapController {
  cancel(): Promise<boolean>;
  start(): Promise<BootstrapResult>;
}

export interface SourceCandidate {
  identity: FileSystemIdentity;
  path: string;
  provenance: BootstrapProvenance;
  revision: string;
}

export type SourceCandidateOwnedPathKind = "candidate" | "staging-candidate" | "staging-unpack";

export interface SourceCandidateOwnedPath {
  identity: FileSystemIdentity;
  kind: SourceCandidateOwnedPathKind;
  path: string;
}

export interface SourceCandidateStager {
  stage(input: {
    destination: string;
    /** Await durable exact no-follow ownership before any staging result escapes. */
    onOwnedPathPrepared(owned: SourceCandidateOwnedPath): Promise<void> | void;
    revision: string;
    signal?: AbortSignal;
  }): Promise<SourceCandidate>;
}

export interface SourceCandidateStagerOptions {
  bootstrap: Omit<
    BootstrapOptions,
    "expectedRevision" | "heldOperationLease" | "operationCoordinator" | "paths" | "state"
  > & {
    paths: BootstrapOptions["paths"];
  };
  createBootstrap?: (options: BootstrapOptions) => BootstrapController;
  operationLease: SourceOperationLeaseProof;
}

function requireRevision(value: string): string {
  const revision = value.trim().toLowerCase();
  if (!COMMIT_PATTERN.test(revision)) throw new Error("Source candidate revision must be a full Git commit.");
  return revision;
}

export function createSourceCandidateStager(options: SourceCandidateStagerOptions): SourceCandidateStager {
  const createBootstrap = options.createBootstrap ?? createFirstRunBootstrap;
  const sourceRoot = options.bootstrap.paths.sourceRoot;
  return {
    async stage({ destination, onOwnedPathPrepared, revision: requestedRevision, signal }): Promise<SourceCandidate> {
      await options.operationLease.assertHeld();
      const revision = requireRevision(requestedRevision);
      if (
        path.dirname(destination) !== sourceRoot ||
        !UPDATE_CANDIDATE_PATTERN.test(path.basename(destination)) ||
        destination === options.bootstrap.paths.activeSource
      ) {
        throw new Error("Update candidate must be a unique managed sibling of the active source.");
      }
      const stagingCandidate = `${destination}.candidate-1`;
      const stagingUnpack = `${stagingCandidate}.unpack`;
      const ownedPaths = [
        { kind: "candidate" as const, path: destination },
        { kind: "staging-candidate" as const, path: stagingCandidate },
        { kind: "staging-unpack" as const, path: stagingUnpack },
      ];
      if (signal?.aborted) throw new DOMException("Source candidate staging was cancelled.", "AbortError");
      for (const owned of ownedPaths) {
        if (await options.bootstrap.dependencies.fileSystem.existsNoFollow(owned.path)) {
          throw new Error("Update candidate destination or bootstrap staging alias already exists; refusing to replace forensic evidence.");
        }
      }
      if (signal?.aborted) throw new DOMException("Source candidate staging was cancelled.", "AbortError");
      const controller = createBootstrap({
        ...options.bootstrap,
        expectedRevision: revision,
        heldOperationLease: options.operationLease,
        paths: { ...options.bootstrap.paths, activeSource: destination },
        state: createBootstrapState(),
      });
      const onAbort = (): void => {
        void controller.cancel();
      };
      signal?.addEventListener("abort", onAbort, { once: true });
      if (signal?.aborted) onAbort();
      const publishOwnedPaths = async (): Promise<SourceCandidateOwnedPath[]> => {
        try {
          const published: SourceCandidateOwnedPath[] = [];
          for (const owned of ownedPaths) {
            if (!(await options.bootstrap.dependencies.fileSystem.existsNoFollow(owned.path))) continue;
            const prepared = {
              identity: await options.bootstrap.dependencies.fileSystem.directoryIdentity(owned.path),
              kind: owned.kind,
              path: owned.path,
            };
            await onOwnedPathPrepared(prepared);
            published.push(prepared);
          }
          return published;
        } catch (ownershipFailure) {
          if (isSourceOperationLeaseRetentionError(ownershipFailure)) throw ownershipFailure;
          throw new SourceOperationLeaseRetentionError(
            "Failed source staging ownership could not be proven for durable cleanup.",
            { cause: ownershipFailure },
          );
        }
      };
      try {
        let result: BootstrapResult;
        try {
          result = await controller.start();
        } catch (error) {
          await publishOwnedPaths();
          if (isSourceOperationLeaseRetentionError(error)) throw error;
          throw new SourceOperationLeaseRetentionError(
            "Source candidate bootstrap rejected without proving child-process containment.",
            { cause: error },
          );
        }
        const published = await publishOwnedPaths();
        if (!result.ok || !result.revision || !result.provenance || !result.sourceIdentity) {
          if (result.containmentFailed) {
            throw new SourceOperationLeaseRetentionError(
              result.error ?? "Source candidate command containment could not be proven.",
            );
          }
          if (result.cancelled) throw new DOMException("Source candidate staging was cancelled.", "AbortError");
          throw new Error(result.error ?? "Source candidate staging failed without a durable result.");
        }
        const destinationOwnership = published.find((owned) => owned.kind === "candidate");
        if (!destinationOwnership) {
          throw new Error("Completed source staging did not create its exact owned destination.");
        }
        if (result.revision !== revision) throw new Error("Staged source candidate does not match the requested revision.");
        if (
          !Number.isSafeInteger(result.sourceIdentity.dev) ||
          result.sourceIdentity.dev < 0 ||
          !Number.isSafeInteger(result.sourceIdentity.ino) ||
          result.sourceIdentity.ino < 0
        ) {
          throw new Error("Staged source candidate has an invalid directory identity.");
        }
        if (
          result.sourceIdentity.dev !== destinationOwnership.identity.dev ||
          result.sourceIdentity.ino !== destinationOwnership.identity.ino
        ) {
          throw new Error("Staged source candidate result does not match its no-follow directory identity.");
        }
        return { identity: result.sourceIdentity, path: destination, provenance: result.provenance, revision };
      } finally {
        signal?.removeEventListener("abort", onAbort);
      }
    },
  };
}
