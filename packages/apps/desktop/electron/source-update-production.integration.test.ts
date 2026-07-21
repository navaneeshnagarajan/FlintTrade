import { constants } from "node:fs";
import {
  access,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, it } from "vitest";

import { createNodeBootstrapDependencies, currentBootIdentity } from "./bootstrap-io";
import { createSafeDirectoryRemover } from "./safe-directory-removal";
import { sourceUpdateIsolationRoot } from "./source-update-runtime";
import {
  createNodeSourcePromotionHealthLifecycle,
  createNodeSourceUpdaterCleanup,
  createNodeSourceUpdaterHealth,
  createRuntimeSourceUpdaterOperationLease,
} from "./source-update-io";
import {
  ACTIVE_SOURCE_NAME,
  JOURNAL_NAME,
  LAST_KNOWN_GOOD_NAME,
  createNodeSourcePromotionFileSystem,
  createSourcePromotion,
} from "./source-promotion";

const CANDIDATE_OPERATION_ID = "123e4567-e89b-42d3-a456-426614174000";
const PROMOTED_HEALTH_OPERATION_ID = "4d925d16-70f8-4c4a-a158-8604ebf4d6b8";
const ORIGINAL_CONTENT_IDENTITY = "fixture-content:original";
const CANDIDATE_CONTENT_IDENTITY = "fixture-content:candidate";

const repositoryRoot = path.resolve(import.meta.dirname, "../../../..");
const bootstrapResources = path.resolve(import.meta.dirname, "../resources/bootstrap");
const pythonCandidates = [
  path.join(repositoryRoot, ".venv", "bin", "python"),
  "/opt/homebrew/bin/python3",
  "/usr/local/bin/python3",
  "/usr/bin/python3",
];

async function availablePython(): Promise<string | null> {
  for (const candidate of pythonCandidates) {
    try {
      await access(candidate, constants.X_OK);
      return await realpath(candidate);
    } catch {
      // Try the next deterministic interpreter location.
    }
  }
  return null;
}

async function writeFakeCandidate(candidateRoot: string, python: string): Promise<void> {
  const packageRoot = path.join(candidateRoot, "flinttrade_core");
  const interpreter = path.join(candidateRoot, ".venv", "bin", "python");
  await mkdir(path.dirname(interpreter), { recursive: true });
  await mkdir(packageRoot, { recursive: true });
  await mkdir(path.join(candidateRoot, "packages", "apps", "terminal", "dist"), { recursive: true });
  await symlink(python, interpreter);
  await writeFile(path.join(packageRoot, "__init__.py"), "", "utf8");
  await writeFile(
    path.join(packageRoot, "cli.py"),
    String.raw`
import json
import os
from pathlib import Path
import secrets
import sys


def fail(message):
    print(message, file=sys.stderr, flush=True)
    raise SystemExit(2)


if sys.argv[1:] != ["init", "--provision-master-password"]:
    fail("unexpected provisioning arguments")
if any(os.environ.get(key) for key in ("FLINTTRADE_FAKE_HOST_SECRET", "HTTPS_PROXY", "USERPROFILE")):
    fail("host secret leaked into candidate provisioning")
if os.environ.get("PYTHONNOUSERSITE") != "1":
    fail("candidate user-site isolation is missing")

candidate = Path.cwd().resolve()
workspace = Path(os.environ["FLINTTRADE_WORKSPACE_DIR"]).resolve()
flinttrade_home = Path(os.environ["FLINTTRADE_HOME"]).resolve()
home = Path(os.environ["HOME"]).resolve()
frontend = Path(os.environ["FLINTTRADE_FRONTEND_DIST"]).resolve()
if frontend != candidate / "packages" / "apps" / "terminal" / "dist":
    fail("frontend path escaped the candidate")

for target in (workspace, flinttrade_home, home):
    target.mkdir(parents=True, exist_ok=True)
password = workspace / "master_password"
with password.open("x", encoding="utf-8") as handle:
    handle.write(secrets.token_hex(32))
os.chmod(password, 0o600)
(workspace / "provision-evidence.json").write_text(
    json.dumps(
        {
            "candidate": str(candidate),
            "flinttradeHome": str(flinttrade_home),
            "home": str(home),
            "hostSecretPresent": "FLINTTRADE_FAKE_HOST_SECRET" in os.environ,
            "workspace": str(workspace),
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
`,
    "utf8",
  );
  await writeFile(
    path.join(packageRoot, "desktop.py"),
    String.raw`
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import signal
import sys


def fail(message):
    print(message, file=sys.stderr, flush=True)
    raise SystemExit(2)


if sys.argv[1:] != ["--port", "0"]:
    fail("unexpected desktop arguments")
if any(os.environ.get(key) for key in ("FLINTTRADE_FAKE_HOST_SECRET", "HTTPS_PROXY", "USERPROFILE")):
    fail("host secret leaked into candidate health")

candidate = Path.cwd().resolve()
workspace = Path(os.environ["FLINTTRADE_WORKSPACE_DIR"]).resolve()
flinttrade_home = Path(os.environ["FLINTTRADE_HOME"]).resolve()
home = Path(os.environ["HOME"]).resolve()
frontend = Path(os.environ["FLINTTRADE_FRONTEND_DIST"]).resolve()
if frontend != candidate / "packages" / "apps" / "terminal" / "dist":
    fail("frontend path escaped the candidate")
if not (workspace / "master_password").is_file():
    fail("candidate workspace was not provisioned")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/v1/ping":
            self.send_response(404)
            self.end_headers()
            return
        (workspace / "health-evidence.json").write_text(
            json.dumps(
                {
                    "candidate": str(candidate),
                    "flinttradeHome": str(flinttrade_home),
                    "home": str(home),
                    "hostSecretPresent": "FLINTTRADE_FAKE_HOST_SECRET" in os.environ,
                    "workspace": str(workspace),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


server = HTTPServer(("127.0.0.1", 0), Handler)
running = True


def stop(_signum, _frame):
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
server.timeout = 0.05
print(f"FLINTTRADE_BACKEND_READY port={server.server_port}", flush=True)
while running:
    server.handle_request()
server.server_close()
`,
    "utf8",
  );
  await writeFile(path.join(candidateRoot, "release.txt"), "candidate\n", "utf8");
}

it.runIf(process.platform !== "win32")(
  "provisions, proves, cleans, and promotes a contained fake candidate with production boundaries",
  async () => {
    const python = await availablePython();
    if (!python) {
      throw new Error("The production source-update integration fixture requires a local Python 3 interpreter.");
    }

    const root = await realpath(await mkdtemp(path.join(tmpdir(), "flinttrade-source-update-production-")));
    const sourceRoot = path.join(root, "source");
    const workspace = path.join(root, "workspace");
    const isolationRoot = sourceUpdateIsolationRoot(workspace);
    const activeSource = path.join(sourceRoot, ACTIVE_SOURCE_NAME);
    const candidateRoot = path.join(sourceRoot, `FlintTrade.update-${CANDIDATE_OPERATION_ID}`);
    const candidateIsolationPath = path.join(isolationRoot, `source-update-${CANDIDATE_OPERATION_ID}`);
    const promotedIsolationPath = path.join(isolationRoot, `source-update-${PROMOTED_HEALTH_OPERATION_ID}`);
    const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
    await mkdir(sourceRoot, { recursive: true, mode: 0o700 });
    await mkdir(activeSource, { mode: 0o700 });
    await writeFile(path.join(activeSource, "release.txt"), "original\n", "utf8");
    await mkdir(candidateRoot, { mode: 0o700 });
    await writeFakeCandidate(candidateRoot, python);

    const dependencies = createNodeBootstrapDependencies(process.platform, {
      environment: {
        FLINTTRADE_FAKE_HOST_SECRET: "must-not-reach-the-candidate",
        HTTPS_PROXY: "https://user:proxy-canary@example.invalid",
        LANG: process.env.LANG,
        PATH: process.env.PATH,
        TMPDIR: process.env.TMPDIR,
        USERPROFILE: "/real/profile-canary",
      },
      operationLeaseTarget,
    });
    const operationLease = createRuntimeSourceUpdaterOperationLease({
      bootIdentity: currentBootIdentity(),
      dependencies,
      singletonAuthorised: true,
      sourceRoot,
    });
    const promotionFileSystem = createNodeSourcePromotionFileSystem({
      safeRemove: createSafeDirectoryRemover({
        bootstrapResources,
        dependencies,
        operationLease,
        platform: process.platform,
        pythonExecutable: python,
      }),
    });
    const cleanup = createNodeSourceUpdaterCleanup({
      fileSystem: promotionFileSystem,
      isolationRoot,
      sourceRoot,
      workspace,
    });
    const releaseOperationLease = await operationLease.acquire({
      kind: "update-apply",
      signal: new AbortController().signal,
    });

    try {
      const candidateIsolation = {
        flinttradeHome: path.join(candidateIsolationPath, "flinttrade-home"),
        home: path.join(candidateIsolationPath, "home"),
        workspace: path.join(candidateIsolationPath, "workspace"),
      };
      let candidateIsolationIdentity: { dev: number; ino: number } | undefined;
      const health = createNodeSourceUpdaterHealth({
        dependencies,
        isolationRoot,
        pingIntervalMs: 10,
        sourceRoot,
        timeoutMs: 20_000,
        workspace,
      });
      const proof = await health.prove({
        candidateRoot,
        isolation: candidateIsolation,
        onIsolationPrepared(identity) {
          candidateIsolationIdentity = identity;
        },
        signal: new AbortController().signal,
      });

      expect(proof).toMatchObject({
        candidateRoot,
        isolationIdentity: candidateIsolationIdentity,
        port: expect.any(Number),
      });
      const provisionEvidence = JSON.parse(
        await readFile(path.join(candidateIsolation.workspace, "provision-evidence.json"), "utf8"),
      ) as Record<string, unknown>;
      const healthEvidence = JSON.parse(
        await readFile(path.join(candidateIsolation.workspace, "health-evidence.json"), "utf8"),
      ) as Record<string, unknown>;
      const canonicalIsolation = {
        flinttradeHome: await realpath(candidateIsolation.flinttradeHome),
        home: await realpath(candidateIsolation.home),
        workspace: await realpath(candidateIsolation.workspace),
      };
      const expectedEvidence = {
        candidate: candidateRoot,
        flinttradeHome: canonicalIsolation.flinttradeHome,
        home: canonicalIsolation.home,
        hostSecretPresent: false,
        workspace: canonicalIsolation.workspace,
      };
      expect(provisionEvidence).toEqual(expectedEvidence);
      expect(healthEvidence).toEqual(expectedEvidence);
      const passwordMetadata = await lstat(path.join(candidateIsolation.workspace, "master_password"));
      expect(passwordMetadata.isFile()).toBe(true);
      expect(passwordMetadata.mode & 0o777).toBe(0o600);

      if (!candidateIsolationIdentity) throw new Error("Candidate isolation ownership was not published.");
      await cleanup.removeIsolation({
        identity: candidateIsolationIdentity,
        isolationPath: candidateIsolationPath,
      });
      await expect(lstat(candidateIsolationPath)).rejects.toMatchObject({ code: "ENOENT" });

      const originalIdentity = await promotionFileSystem.inspectDirectory(activeSource);
      const candidateIdentity = await promotionFileSystem.inspectDirectory(candidateRoot);
      if (!originalIdentity || !candidateIdentity) throw new Error("Promotion fixture identities are missing.");
      const bootLifecycle = createNodeSourcePromotionHealthLifecycle({
        cleanup,
        dependencies,
        isolationRoot,
        operationLease,
        pingIntervalMs: 10,
        sourceRoot,
        timeoutMs: 20_000,
        uuid: () => PROMOTED_HEALTH_OPERATION_ID,
        workspace,
      });
      const promotion = createSourcePromotion({
        fileSystem: promotionFileSystem,
        lifecycle: {
          bootActive: bootLifecycle.bootActive,
          async stopActive() {
            return undefined;
          },
          async validateActiveContent(target, expectedContentIdentity) {
            const release = await readFile(path.join(target, "release.txt"), "utf8");
            const actual = release === "candidate\n" ? CANDIDATE_CONTENT_IDENTITY : ORIGINAL_CONTENT_IDENTITY;
            return actual === expectedContentIdentity;
          },
        },
        sourceRoot,
      });

      const promotionOutcome = await promotion.promote({
        candidateContentIdentity: CANDIDATE_CONTENT_IDENTITY,
        candidateDirectoryIdentity: { dev: candidateIdentity.dev, ino: candidateIdentity.ino },
        candidatePath: candidateRoot,
        originalActiveContentIdentity: ORIGINAL_CONTENT_IDENTITY,
        originalActiveDirectoryIdentity: { dev: originalIdentity.dev, ino: originalIdentity.ino },
      });
      expect(promotionOutcome).toMatchObject({ status: "promoted" });
      await expect(readFile(path.join(activeSource, "release.txt"), "utf8")).resolves.toBe("candidate\n");
      await expect(readFile(path.join(sourceRoot, LAST_KNOWN_GOOD_NAME, "release.txt"), "utf8")).resolves.toBe(
        "original\n",
      );
      await expect(lstat(candidateRoot)).rejects.toMatchObject({ code: "ENOENT" });
      await expect(lstat(path.join(sourceRoot, JOURNAL_NAME))).resolves.toBeDefined();
      if (promotionOutcome.status === "idle") throw new Error("Promotion unexpectedly returned idle.");
      await promotion.acknowledge(promotionOutcome);
      await expect(lstat(path.join(sourceRoot, JOURNAL_NAME))).rejects.toMatchObject({ code: "ENOENT" });
      await expect(lstat(promotedIsolationPath)).rejects.toMatchObject({ code: "ENOENT" });
      await operationLease.assertHeld();
    } finally {
      try {
        await releaseOperationLease();
      } finally {
        await Promise.all([
          rm(root, { force: true, recursive: true }),
          rm(isolationRoot, { force: true, recursive: true }),
        ]);
      }
    }
  },
  45_000,
);
