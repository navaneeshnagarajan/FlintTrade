import path from "node:path";

export interface DesktopPathEnvironment {
  APPDATA?: string;
  FLINTTRADE_HOME?: string;
  FLINTTRADE_WORKSPACE_DIR?: string;
}

export interface DesktopPathInputs {
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

function expandHome(value: string, homeDirectory: string, pathApi: typeof path.posix): string {
  if (value === "~") return homeDirectory;
  if (value.startsWith("~/") || value.startsWith("~\\")) return pathApi.join(homeDirectory, value.slice(2));
  return value;
}

export function resolveDesktopPaths(inputs: DesktopPathInputs): DesktopPaths {
  const pathApi = inputs.platform === "win32" ? path.win32 : path.posix;
  const homeDirectory = pathApi.resolve(inputs.homeDirectory);
  const sourceRoot = pathApi.join(homeDirectory, ".flinttrade", "src");
  const toolsRoot = pathApi.join(homeDirectory, ".flinttrade", "tools");

  const workspaceOverride = inputs.env.FLINTTRADE_WORKSPACE_DIR?.trim();
  const homeOverride = inputs.env.FLINTTRADE_HOME?.trim();
  let workspace: string;
  if (workspaceOverride) {
    workspace = pathApi.resolve(expandHome(workspaceOverride, homeDirectory, pathApi));
  } else if (homeOverride) {
    workspace = pathApi.resolve(expandHome(homeOverride, homeDirectory, pathApi));
  } else if (inputs.platform === "darwin") {
    workspace = pathApi.join(homeDirectory, "Library", "Application Support", "flinttrade");
  } else if (inputs.platform === "win32") {
    const appData = inputs.env.APPDATA?.trim();
    workspace = appData
      ? pathApi.join(pathApi.resolve(appData), "flinttrade")
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
