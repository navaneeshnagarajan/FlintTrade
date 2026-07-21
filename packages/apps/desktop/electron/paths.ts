import { existsSync, realpathSync } from "node:fs";
import path from "node:path";

export interface DesktopPathEnvironment {
  APPDATA?: string;
  FLINTTRADE_HOME?: string;
  FLINTTRADE_WORKSPACE_DIR?: string;
}

export interface DesktopPathInputs {
  currentWorkingDirectory: string;
  env: DesktopPathEnvironment;
  homeDirectory: string;
  platform: NodeJS.Platform;
}

export interface DesktopPaths {
  activeSource: string;
  logs: string;
  sourceRoot: string;
  toolsRoot: string;
  workspace: string;
}

function expandHome(
  value: string,
  homeDirectory: string,
  platform: NodeJS.Platform,
  pathApi: typeof path.posix,
): string {
  if (value === "~") return homeDirectory;
  if (value.startsWith("~/") || (platform === "win32" && value.startsWith("~\\"))) {
    return pathApi.join(homeDirectory, value.slice(2));
  }
  if (value.startsWith("~")) {
    if (platform !== "win32" && !value.startsWith("~\\")) {
      throw new TypeError(`Named-user home paths are not supported on POSIX: ${JSON.stringify(value)}.`);
    }
    throw new TypeError(`Could not determine home directory for ${JSON.stringify(value)}.`);
  }
  return value;
}

function canonicaliseExistingComponents(value: string, pathApi: typeof path.posix): string {
  let existing = value;
  const missing: string[] = [];

  while (!existsSync(existing)) {
    const parent = pathApi.dirname(existing);
    if (parent === existing) return value;
    missing.unshift(pathApi.basename(existing));
    existing = parent;
  }

  return pathApi.join(realpathSync.native(existing), ...missing);
}

export function resolveDesktopPaths(inputs: DesktopPathInputs): DesktopPaths {
  const pathApi = inputs.platform === "win32" ? path.win32 : path.posix;
  const canonicalise =
    inputs.platform === process.platform
      ? (value: string) => canonicaliseExistingComponents(value, pathApi)
      : (value: string) => value;
  const currentWorkingDirectory = canonicalise(pathApi.resolve(inputs.currentWorkingDirectory));
  const homeDirectory = canonicalise(pathApi.resolve(currentWorkingDirectory, inputs.homeDirectory));
  const sourceRoot = canonicalise(pathApi.join(homeDirectory, ".flinttrade", "src"));
  const toolsRoot = canonicalise(pathApi.join(homeDirectory, ".flinttrade", "tools"));

  const workspaceOverride = inputs.env.FLINTTRADE_WORKSPACE_DIR;
  const homeOverride = inputs.env.FLINTTRADE_HOME;
  let workspace: string;
  if (workspaceOverride) {
    workspace = canonicalise(
      pathApi.resolve(
        currentWorkingDirectory,
        expandHome(workspaceOverride, homeDirectory, inputs.platform, pathApi),
      ),
    );
  } else if (homeOverride) {
    workspace = canonicalise(
      pathApi.resolve(currentWorkingDirectory, expandHome(homeOverride, homeDirectory, inputs.platform, pathApi)),
    );
  } else if (inputs.platform === "darwin") {
    workspace = canonicalise(pathApi.join(homeDirectory, "Library", "Application Support", "flinttrade"));
  } else if (inputs.platform === "win32") {
    const appData = inputs.env.APPDATA;
    workspace = canonicalise(
      appData
        ? pathApi.join(appData, "flinttrade")
        : pathApi.join(homeDirectory, "AppData", "Roaming", "flinttrade"),
    );
  } else {
    workspace = canonicalise(pathApi.join(homeDirectory, ".flinttrade"));
  }

  return {
    activeSource: canonicalise(pathApi.join(sourceRoot, "FlintTrade")),
    logs: canonicalise(pathApi.join(workspace, "logs")),
    sourceRoot,
    toolsRoot,
    workspace,
  };
}
