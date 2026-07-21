import { spawn } from "node:child_process";
import { once } from "node:events";
import { access, mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";
import { expect, it } from "vitest";

import {
  ACTIVE_SOURCE_NAME,
  JOURNAL_NAME,
  LAST_KNOWN_GOOD_NAME,
} from "./source-promotion";

const OPERATION_ID = "123e4567-e89b-42d3-a456-426614174000";

interface FixtureResult {
  applyStatus?: string;
  bootedReleases: string[];
  inventoryCalls?: number;
  leaseState: string;
  outcomeStatus?: string;
  quitFailed?: boolean;
  reacquireBlocked?: boolean;
  recoveryBlocked?: boolean;
}

async function runFixture(
  fixturePath: string,
  args: readonly string[],
): Promise<{ code: number | null; signal: NodeJS.Signals | null; stderr: string; stdout: string }> {
  const child = spawn(process.execPath, [fixturePath, ...args], {
    env: { PATH: process.env.PATH },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk: string) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk: string) => {
    stderr += chunk;
  });
  const [code, signal] = (await once(child, "exit")) as [number | null, NodeJS.Signals | null];
  return { code, signal, stderr, stdout };
}

it.runIf(process.platform !== "win32")(
  "retains a live-boot lease in one process and admits exactly one journal boot in a fresh process",
  async () => {
    const temporaryRoot = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-source-retention-")));
    const fixturePath = path.join(temporaryRoot, "source-update-retention-fixture.cjs");
    const sourceDirectory = path.dirname(fileURLToPath(import.meta.url));

    try {
      await build({
        bundle: true,
        format: "cjs",
        outfile: fixturePath,
        platform: "node",
        stdin: {
          contents: String.raw`
            import { readFile } from "node:fs/promises"
            import path from "node:path"

            import { createNodeBootstrapDependencies, currentBootIdentity } from "./bootstrap-io"
            import { createBootstrapQuitGate } from "./bootstrap-shutdown"
            import { createSourceOperationCoordinator } from "./source-operation"
            import {
              createRuntimeSourceUpdaterOperationLease,
            } from "./source-update-io"
            import {
              ACTIVE_SOURCE_NAME,
              JOURNAL_NAME,
              LAST_KNOWN_GOOD_NAME,
              createNodeSourcePromotionFileSystem,
              createSourcePromotion,
            } from "./source-promotion"
            import { sourceContentIdentityKey } from "./source-provenance"
            import { createSourceUpdater } from "./source-updater"
            import { createUpdateState } from "./state"

            async function main() {
            const [mode, scenario, sourceRoot, workspace] = process.argv.slice(2)
            if (!new Set(["old", "recover"]).has(mode)) throw new Error("invalid fixture mode")
            if (!new Set(["promoted", "rollback"]).has(scenario)) throw new Error("invalid fixture scenario")

            const operationId = "123e4567-e89b-42d3-a456-426614174000"
            const originalRevision = "a".repeat(40)
            const candidateRevision = "b".repeat(40)
            const activeSource = path.join(sourceRoot, ACTIVE_SOURCE_NAME)
            const candidateSource = path.join(sourceRoot, "FlintTrade.update-" + operationId)
            const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock")
            const isolationRoot = path.join(workspace, "isolation")
            const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget })
            const operationLease = createRuntimeSourceUpdaterOperationLease({
              bootIdentity: currentBootIdentity(),
              dependencies,
              singletonAuthorised: true,
              sourceRoot,
            })
            const coordinator = createSourceOperationCoordinator()
            const baseFileSystem = createNodeSourcePromotionFileSystem()
            let injectFailure = mode === "old"
            const failedPhase = scenario === "promoted" ? "promoted-boot-after" : "rollback-boot-after"
            const fileSystem = {
              ...baseFileSystem,
              async writeJournalAtomic(target, contents) {
                const phase = JSON.parse(contents).phase
                if (injectFailure && phase === failedPhase) {
                  injectFailure = false
                  throw new Error("simulated live-boot journal write failure")
                }
                await baseFileSystem.writeJournalAtomic(target, contents)
              },
            }
            const identityFor = async (target) => {
              const directory = await baseFileSystem.inspectDirectory(target)
              if (!directory) throw new Error("fixture source identity is missing")
              const release = (await readFile(path.join(target, "release.txt"), "utf8")).trim()
              const candidate = release === "candidate"
              return {
                canonicalPath: directory.canonicalPath,
                contentIdentity: candidate ? "tree:candidate" : "tree:original",
                directoryIdentity: { dev: directory.dev, ino: directory.ino },
                provenance: "git",
                revision: candidate ? candidateRevision : originalRevision,
              }
            }
            const bootedReleases = []
            const bootActive = async ({ activePath: target, onBackendStopped }) => {
              const release = (await readFile(path.join(target, "release.txt"), "utf8")).trim()
              bootedReleases.push(release)
              const healthy = !(mode === "old" && scenario === "rollback" && release === "candidate")
              if (!healthy) onBackendStopped()
              return healthy
            }
            const promotion = createSourcePromotion({
              fileSystem,
              lifecycle: {
                bootActive,
                isAvailable: () => true,
                stopActive: async () => undefined,
                async validateActiveContent(target, expectedContentIdentity) {
                  return sourceContentIdentityKey(await identityFor(target)) === expectedContentIdentity
                },
              },
              onBoundary: () => operationLease.assertHeld(),
              sourceRoot,
            })
            let inventoryCalls = 0
            const cleanup = {
              assertReady: () => undefined,
              inventoryOwnedPaths: async () => { inventoryCalls += 1 },
              recover: async () => undefined,
              removeIsolation: async () => undefined,
              removeOwnedCandidate: async () => undefined,
              removeOwnedPaths: async () => undefined,
              removeReservedPaths: async () => undefined,
              reserveOwnedPaths: async () => undefined,
              validateRecovery: async () => undefined,
            }
            const updater = createSourceUpdater({
              activeSource,
              candidateStager: {
                async stage({ destination, onOwnedPathPrepared, revision }) {
                  const directory = await baseFileSystem.inspectDirectory(destination)
                  if (!directory) throw new Error("fixture candidate identity is missing")
                  const identity = { dev: directory.dev, ino: directory.ino }
                  await onOwnedPathPrepared({ identity, kind: "candidate", path: destination })
                  return { identity, path: destination, provenance: "git", revision }
                },
              },
              cleanup,
              coordinator,
              events: { record: async () => undefined },
              health: {
                async prove({ candidateRoot, onIsolationPrepared }) {
                  const isolationIdentity = { dev: 700, ino: 900 }
                  await onIsolationPrepared(isolationIdentity)
                  return { candidateRoot, isolationIdentity, port: 32123 }
                },
              },
              isolationRoot,
              lifecycle: {
                bootActive,
                async drainCurrent({ onBackendStopped }) {
                  onBackendStopped()
                },
                isAvailable: () => true,
              },
              operationLease,
              promotion,
              provenance: { validate: ({ sourcePath }) => identityFor(sourcePath) },
              revisionResolver: {
                resolve: async () => ({ provenance: "git", revision: candidateRevision }),
              },
              sourceRoot,
              state: createUpdateState("source"),
              uuid: () => operationId,
            })

            if (mode === "old") {
              const checked = await updater.check()
              if (checked.status !== "available") throw new Error("fixture update did not become available")
              const applied = await updater.apply()
              const bootCountAfterApply = bootedReleases.length
              let quitFailed = false
              const quitGate = createBootstrapQuitGate(
                { quit() { throw new Error("simulated Electron app.quit failure") } },
                {
                  async shutdown() {
                    await operationLease.settleForQuit()
                    const state = operationLease.getSnapshot().state
                    if (state !== "process-exit-required") {
                      throw new Error("live-backend quit settlement released its retained lease")
                    }
                  },
                },
              )
              try {
                await quitGate.requestQuit()
              } catch (error) {
                if (!(error instanceof Error) || error.message !== "simulated Electron app.quit failure") throw error
                quitFailed = true
              }
              let reacquireBlocked = false
              try {
                await operationLease.acquire({
                  kind: "startup-recovery",
                  signal: new AbortController().signal,
                })
              } catch {
                reacquireBlocked = true
              }
              let recoveryBlocked = false
              try {
                await updater.recover()
              } catch {
                recoveryBlocked = true
              }
              if (bootedReleases.length !== bootCountAfterApply) {
                throw new Error("same-runtime recovery booted the retained live tree again")
              }
              await coordinator.shutdown()
              process.stdout.write(JSON.stringify({
                applyStatus: applied.status,
                bootedReleases,
                inventoryCalls,
                leaseState: operationLease.getSnapshot().state,
                quitFailed,
                reacquireBlocked,
                recoveryBlocked,
              }))
            } else {
              const outcome = await updater.recover()
              await coordinator.shutdown()
              process.stdout.write(JSON.stringify({
                bootedReleases,
                leaseState: operationLease.getSnapshot().state,
                outcomeStatus: outcome.status,
              }))
            }
            }

            void main().catch((error) => {
              console.error(error)
              process.exitCode = 1
            })
          `,
          loader: "ts",
          resolveDir: sourceDirectory,
          sourcefile: "source-update-retention-fixture.ts",
        },
        target: "node22",
      });

      for (const scenario of ["promoted", "rollback"] as const) {
        const scenarioRoot = path.join(temporaryRoot, scenario);
        const sourceRoot = path.join(scenarioRoot, "source");
        const workspace = path.join(scenarioRoot, "workspace");
        const activeSource = path.join(sourceRoot, ACTIVE_SOURCE_NAME);
        const candidateSource = path.join(sourceRoot, `FlintTrade.update-${OPERATION_ID}`);
        const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
        const journalPath = path.join(sourceRoot, JOURNAL_NAME);
        await mkdir(activeSource, { recursive: true, mode: 0o700 });
        await mkdir(candidateSource, { mode: 0o700 });
        await mkdir(workspace, { recursive: true, mode: 0o700 });
        await writeFile(path.join(activeSource, "release.txt"), "original\n", "utf8");
        await writeFile(path.join(candidateSource, "release.txt"), "candidate\n", "utf8");

        const oldProcess = await runFixture(fixturePath, ["old", scenario, sourceRoot, workspace]);
        expect(oldProcess).toMatchObject({ code: 0, signal: null, stderr: "" });
        const oldResult = JSON.parse(oldProcess.stdout) as FixtureResult;
        expect(oldResult).toMatchObject({
          applyStatus: "failed",
          bootedReleases: scenario === "promoted" ? ["candidate"] : ["candidate", "original"],
          leaseState: "process-exit-required",
          quitFailed: true,
          reacquireBlocked: true,
          recoveryBlocked: true,
        });
        expect(oldResult.inventoryCalls).toBeGreaterThan(0);
        await expect(access(operationLeaseTarget)).resolves.toBeUndefined();
        const journal = JSON.parse(await readFile(journalPath, "utf8")) as Record<string, unknown>;
        expect(journal).toMatchObject(
          scenario === "promoted"
            ? { phase: "promoted-boot-before", promotedBoot: "not-attempted" }
            : {
                phase: "rollback-boot-before",
                promotedBoot: "failed",
                rollbackBoot: "not-attempted",
              },
        );

        const freshProcess = await runFixture(fixturePath, ["recover", scenario, sourceRoot, workspace]);
        expect(freshProcess).toMatchObject({ code: 0, signal: null, stderr: "" });
        const freshResult = JSON.parse(freshProcess.stdout) as FixtureResult;
        expect(freshResult).toMatchObject({
          bootedReleases: [scenario === "promoted" ? "candidate" : "original"],
          leaseState: "idle",
          outcomeStatus: scenario === "promoted" ? "promoted" : "rolled-back",
        });
        await expect(access(journalPath)).rejects.toMatchObject({ code: "ENOENT" });
        await expect(access(operationLeaseTarget)).rejects.toMatchObject({ code: "ENOENT" });
        await expect(readFile(path.join(activeSource, "release.txt"), "utf8")).resolves.toBe(
          scenario === "promoted" ? "candidate\n" : "original\n",
        );
        if (scenario === "promoted") {
          await expect(readFile(path.join(sourceRoot, LAST_KNOWN_GOOD_NAME, "release.txt"), "utf8")).resolves.toBe(
            "original\n",
          );
        }
      }
    } finally {
      await rm(temporaryRoot, { force: true, recursive: true });
    }
  },
  45_000,
);
