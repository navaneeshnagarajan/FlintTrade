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
    throw new TypeError(`Could not determine home directory for ${JSON.stringify(value)}.`);
  }
  return value;
}

export function resolveDesktopPaths(inputs: DesktopPathInputs): DesktopPaths {
  const pathApi = inputs.platform === "win32" ? path.win32 : path.posix;
  const currentWorkingDirectory = pathApi.resolve(inputs.currentWorkingDirectory);
  const homeDirectory = pathApi.resolve(currentWorkingDirectory, inputs.homeDirectory);
  const sourceRoot = pathApi.join(homeDirectory, ".flinttrade", "src");
  const toolsRoot = pathApi.join(homeDirectory, ".flinttrade", "tools");

  const workspaceOverride = inputs.env.FLINTTRADE_WORKSPACE_DIR;
  const homeOverride = inputs.env.FLINTTRADE_HOME;
  let workspace: string;
  if (workspaceOverride) {
    workspace = pathApi.resolve(
      currentWorkingDirectory,
      expandHome(workspaceOverride, homeDirectory, inputs.platform, pathApi),
    );
  } else if (homeOverride) {
    workspace = pathApi.resolve(
      currentWorkingDirectory,
      expandHome(homeOverride, homeDirectory, inputs.platform, pathApi),
    );
  } else if (inputs.platform === "darwin") {
    workspace = pathApi.join(homeDirectory, "Library", "Application Support", "flinttrade");
  } else if (inputs.platform === "win32") {
    const appData = inputs.env.APPDATA;
    workspace = appData
      ? pathApi.join(appData, "flinttrade")
      : pathApi.join(homeDirectory, "AppData", "Roaming", "flinttrade");
  } else {
    workspace = pathApi.join(homeDirectory, ".flinttrade");
  }

  return {
    activeSource: pathApi.join(sourceRoot, "FlintTrade"),
    logs: pathApi.join(workspace, "logs"),
    sourceRoot,
    toolsRoot,
    workspace,
  };
}
