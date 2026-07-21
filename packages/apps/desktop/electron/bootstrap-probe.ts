import { readFileSync } from "node:fs";
import path from "node:path";

import { createFirstRunBootstrap, type BootstrapToolManifest } from "./bootstrap";
import { createNodeBootstrapDependencies } from "./bootstrap-io";
import { createBootstrapState } from "./state";

const rootIndex = process.argv.indexOf("--root");
const manifestIndex = process.argv.indexOf("--manifest");
const repositoryIndex = process.argv.indexOf("--repository");
const branchIndex = process.argv.indexOf("--branch");
const rootArgument = rootIndex < 0 ? undefined : process.argv[rootIndex + 1];
const manifestArgument = manifestIndex < 0 ? undefined : process.argv[manifestIndex + 1];
const repositoryArgument = repositoryIndex < 0 ? undefined : process.argv[repositoryIndex + 1];
const branchArgument = branchIndex < 0 ? undefined : process.argv[branchIndex + 1];
if (!rootArgument || !manifestArgument) {
  throw new Error("usage: bootstrap-probe --root <clean-root> --manifest <tool-manifest.json>");
}
const root = path.resolve(rootArgument);
const manifest = JSON.parse(readFileSync(path.resolve(manifestArgument), "utf8")) as BootstrapToolManifest;
const sourceRoot = path.join(root, "source");
const state = createBootstrapState();
state.subscribe((snapshot) => process.stderr.write(`${JSON.stringify(snapshot)}\n`));
const controller = createFirstRunBootstrap({
  arch: process.arch,
  dependencies: createNodeBootstrapDependencies(process.platform),
  manifest,
  paths: {
    activeSource: path.join(sourceRoot, "FlintTrade"),
    logs: path.join(root, "workspace", "logs"),
    sourceRoot,
    toolsRoot: path.join(root, "tools"),
    workspace: path.join(root, "workspace"),
  },
  platform: process.platform,
  ...(repositoryArgument && branchArgument
    ? {
        repository: {
          archiveBaseUrl: "https://invalid.local/archive",
          branch: branchArgument,
          commitMetadataUrl: "https://invalid.local/commit",
          gitUrl: path.resolve(repositoryArgument),
        },
      }
    : {}),
  state,
});
const result = await controller.start();
process.stdout.write(`${JSON.stringify(result)}\n`);
if (!result.ok) process.exitCode = 1;
