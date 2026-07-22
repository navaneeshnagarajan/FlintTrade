#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (!new Set(["darwin", "linux", "win32"]).has(process.platform)) {
  throw new Error(`Bootstrap probe is unsupported on ${process.platform}.`);
}
const nativeBuilder = process.platform === "win32"
  ? "build-windows-job-supervisor.mjs"
  : "build-atomic-promoter.mjs";
const nativeBuild = spawnSync(process.execPath, [path.join(packageRoot, "scripts", nativeBuilder)], {
  cwd: packageRoot,
  stdio: "inherit",
});
if (nativeBuild.error) throw nativeBuild.error;
if (nativeBuild.status !== 0) {
  throw new Error(`Bootstrap probe native helper build failed with status ${nativeBuild.status ?? "unknown"}.`);
}

const nativeTarget = process.platform === "win32"
  ? "win32-x64"
  : process.platform === "darwin"
    ? "darwin-universal"
    : `linux-${process.arch}`;
const atomicExecutable = process.platform === "win32"
  ? "flinttrade-source-fs.exe"
  : "flinttrade-fs-promoter.node";
const atomicProtocol = process.platform === "win32" ? "windows-source-fs" : "posix";
const nativeRoot = path.join(packageRoot, "dist", "native", nativeTarget);
const atomicHelper = path.join(nativeRoot, atomicExecutable);
const atomicManifestPath = path.join(
  nativeRoot,
  process.platform === "win32"
    ? "flinttrade-source-fs.sha256.json"
    : "flinttrade-fs-promoter.sha256.json",
);
const atomicManifest = JSON.parse(readFileSync(atomicManifestPath, "utf8"));
const expectedKeys = process.platform === "win32"
  ? "executable,schemaVersion,sha256"
  : "executable,schemaVersion,sha256,target";
if (
  !atomicManifest ||
  typeof atomicManifest !== "object" ||
  Array.isArray(atomicManifest) ||
  Object.keys(atomicManifest).sort().join(",") !== expectedKeys ||
  atomicManifest.schemaVersion !== 1 ||
  atomicManifest.executable !== atomicExecutable ||
  (process.platform !== "win32" && atomicManifest.target !== nativeTarget) ||
  typeof atomicManifest.sha256 !== "string" ||
  !/^[0-9a-f]{64}$/.test(atomicManifest.sha256)
) {
  throw new Error("Bootstrap probe native helper manifest is invalid.");
}
const rootIndex = process.argv.indexOf("--root");
if (rootIndex < 0 || !process.argv[rootIndex + 1]) {
  throw new Error("usage: run-bootstrap-probe.mjs --root <clean-root>");
}
const root = path.resolve(process.argv[rootIndex + 1]);
const repositoryIndex = process.argv.indexOf("--repository");
const branchIndex = process.argv.indexOf("--branch");
const repository = repositoryIndex < 0 ? null : process.argv[repositoryIndex + 1];
const branch = branchIndex < 0 ? null : process.argv[branchIndex + 1];
const output = path.join(root, "bootstrap-probe.mjs");
await build({
  bundle: true,
  entryPoints: [path.join(packageRoot, "electron", "bootstrap-probe.ts")],
  format: "esm",
  outfile: output,
  platform: "node",
  target: "node22",
  banner: {
    js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
  },
});
const probeArgs = [
  output,
  "--root",
  root,
  "--manifest",
  path.join(packageRoot, "resources", "bootstrap", "tool-manifest.json"),
  "--atomic-helper",
  atomicHelper,
  "--atomic-sha256",
  atomicManifest.sha256,
  "--atomic-protocol",
  atomicProtocol,
];
if (process.platform === "win32") {
  probeArgs.push(
    "--windows-job-supervisor",
    path.join(nativeRoot, "flinttrade-job-supervisor.exe"),
  );
}
if (repository && branch) probeArgs.push("--repository", repository, "--branch", branch);
const result = spawnSync(
  process.execPath,
  probeArgs,
  { env: process.env, stdio: "inherit" },
);
process.exitCode = result.status ?? 1;
