import { randomBytes } from "node:crypto";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, it } from "vitest";

import { currentBootIdentity, createNodeBootstrapDependencies } from "./bootstrap-io";
import { proveCandidateHealth } from "./candidate-health";

const integration = process.env.FLINTTRADE_SOURCE_UPDATE_INTEGRATION === "1" ? it : it.skip;

integration("proves and cleans up a real candidate interpreter against an isolated workspace", async () => {
  const candidateRoot = path.resolve(import.meta.dirname, "../../../..");
  const root = await mkdtemp(path.join(tmpdir(), "flinttrade-candidate-health-integration-"));
  const sourceRoot = path.join(root, "source");
  const workspace = path.join(root, "isolation", "workspace");
  const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
  await mkdir(workspace, { recursive: true, mode: 0o700 });
  await mkdir(sourceRoot, { recursive: true, mode: 0o700 });
  await writeFile(path.join(workspace, "master_password"), randomBytes(32).toString("hex"), {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  const dependencies = createNodeBootstrapDependencies(process.platform, { operationLeaseTarget });
  const release = await dependencies.fileSystem.acquireOperationLock({
    bootIdentity: currentBootIdentity(),
    ownerPid: process.pid,
    singletonAuthorised: true,
    target: operationLeaseTarget,
  });

  try {
    await expect(
      proveCandidateHealth({
        candidateRoot,
        isolation: {
          flinttradeHome: path.join(root, "isolation", "flinttrade-home"),
          home: path.join(root, "isolation", "home"),
          workspace,
        },
        pingIntervalMs: 50,
        process: dependencies.command,
        timeoutMs: 60_000,
      }),
    ).resolves.toMatchObject({ candidateRoot, port: expect.any(Number) });
  } finally {
    await release();
    await rm(root, { force: true, recursive: true });
  }
}, 70_000);
