#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
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
];
if (repository && branch) probeArgs.push("--repository", repository, "--branch", branch);
const result = spawnSync(
  process.execPath,
  probeArgs,
  { env: process.env, stdio: "inherit" },
);
process.exitCode = result.status ?? 1;
