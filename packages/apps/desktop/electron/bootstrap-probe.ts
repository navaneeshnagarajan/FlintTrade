import { readFileSync } from "node:fs";
import path from "node:path";

import { createFirstRunBootstrap, type BootstrapToolManifest } from "./bootstrap";
import { createNodeBootstrapDependencies, currentBootIdentity } from "./bootstrap-io";
import { createBootstrapState } from "./state";

const rootIndex = process.argv.indexOf("--root");
const manifestIndex = process.argv.indexOf("--manifest");
const repositoryIndex = process.argv.indexOf("--repository");
const branchIndex = process.argv.indexOf("--branch");
const atomicHelperIndex = process.argv.indexOf("--atomic-helper");
const atomicSha256Index = process.argv.indexOf("--atomic-sha256");
const atomicProtocolIndex = process.argv.indexOf("--atomic-protocol");
const windowsJobSupervisorIndex = process.argv.indexOf("--windows-job-supervisor");
const rootArgument = rootIndex < 0 ? undefined : process.argv[rootIndex + 1];
const manifestArgument = manifestIndex < 0 ? undefined : process.argv[manifestIndex + 1];
const repositoryArgument = repositoryIndex < 0 ? undefined : process.argv[repositoryIndex + 1];
const branchArgument = branchIndex < 0 ? undefined : process.argv[branchIndex + 1];
const atomicHelperArgument = atomicHelperIndex < 0 ? undefined : process.argv[atomicHelperIndex + 1];
const atomicSha256Argument = atomicSha256Index < 0 ? undefined : process.argv[atomicSha256Index + 1];
const atomicProtocolArgument = atomicProtocolIndex < 0 ? undefined : process.argv[atomicProtocolIndex + 1];
const windowsJobSupervisorArgument = windowsJobSupervisorIndex < 0
  ? undefined
  : process.argv[windowsJobSupervisorIndex + 1];
if (
  !rootArgument ||
  !manifestArgument ||
  !atomicHelperArgument ||
  !atomicSha256Argument ||
  !atomicProtocolArgument ||
  !/^[0-9a-f]{64}$/.test(atomicSha256Argument) ||
  !["posix", "windows-source-fs"].includes(atomicProtocolArgument)
) {
  throw new Error(
    "usage: bootstrap-probe --root <clean-root> --manifest <tool-manifest.json> " +
    "--atomic-helper <absolute-path> --atomic-sha256 <digest> --atomic-protocol <posix|windows-source-fs>",
  );
}
const root = path.resolve(rootArgument);
const manifest = JSON.parse(readFileSync(path.resolve(manifestArgument), "utf8")) as BootstrapToolManifest;
const sourceRoot = path.join(root, "source");
const state = createBootstrapState();
state.subscribe((snapshot) => process.stderr.write(`${JSON.stringify(snapshot)}\n`));
const operationLeaseTarget = path.join(sourceRoot, ".flinttrade-bootstrap-operation.lock");
const controller = createFirstRunBootstrap({
  arch: process.arch,
  bootIdentity: currentBootIdentity(),
  bootstrapResources: path.dirname(path.resolve(manifestArgument)),
  dependencies: createNodeBootstrapDependencies(process.platform, {
    atomicPromotion: {
      expectedHelperSha256: atomicSha256Argument,
      helper: path.resolve(atomicHelperArgument),
      protocol: atomicProtocolArgument as "posix" | "windows-source-fs",
    },
    operationLeaseTarget,
    windowsJobSupervisor: windowsJobSupervisorArgument
      ? path.resolve(windowsJobSupervisorArgument)
      : path.join(path.dirname(path.resolve(manifestArgument)), "flinttrade-job-supervisor.exe"),
  }),
  manifest,
  paths: {
    activeSource: path.join(sourceRoot, "FlintTrade"),
    logs: path.join(root, "workspace", "logs"),
    sourceRoot,
    toolsRoot: path.join(root, "tools"),
    workspace: path.join(root, "workspace"),
  },
  platform: process.platform,
  singletonAuthorised: true,
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
