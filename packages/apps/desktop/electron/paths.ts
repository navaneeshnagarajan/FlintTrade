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

interface PathResolutionHooks {
  exists(candidate: string): boolean;
  realpath(candidate: string): string;
}

function appendRaw(base: string, value: string, pathApi: typeof path.posix): string {
  if (pathApi.isAbsolute(value)) return value;
  return `${base}${base.endsWith(pathApi.sep) ? "" : pathApi.sep}${value}`;
}

export function canonicalisePathComponents(
  value: string,
  pathApi: typeof path.posix,
  hooks: PathResolutionHooks = {
    exists: existsSync,
    realpath: realpathSync.native,
  },
): string {
  if (!pathApi.isAbsolute(value)) throw new TypeError("Component-wise canonicalisation requires an absolute path.");
  const root = pathApi.parse(value).root;
  let resolved = hooks.exists(root) ? hooks.realpath(root) : root;
  const components = value.slice(root.length).split(/[\\/]+/);
  for (const component of components) {
    if (!component || component === ".") continue;
    if (component === "..") {
      resolved = pathApi.dirname(resolved);
      continue;
    }
    const candidate = pathApi.join(resolved, component);
    resolved = hooks.exists(candidate) ? hooks.realpath(candidate) : candidate;
  }
  return resolved;
}

export function resolveDesktopPaths(inputs: DesktopPathInputs): DesktopPaths {
  const pathApi = inputs.platform === "win32" ? path.win32 : path.posix;
  const canonicalise =
    inputs.platform === process.platform
      ? (value: string) => canonicalisePathComponents(value, pathApi)
      : (value: string) => value;
  const initialWorkingDirectory = pathApi.isAbsolute(inputs.currentWorkingDirectory)
    ? inputs.currentWorkingDirectory
    : pathApi.resolve(inputs.currentWorkingDirectory);
  const currentWorkingDirectory = canonicalise(initialWorkingDirectory);
  const homeDirectory = canonicalise(appendRaw(currentWorkingDirectory, inputs.homeDirectory, pathApi));
  const sourceRoot = canonicalise(pathApi.join(homeDirectory, ".flinttrade", "src"));
  const toolsRoot = canonicalise(pathApi.join(homeDirectory, ".flinttrade", "tools"));

  const workspaceOverride = inputs.env.FLINTTRADE_WORKSPACE_DIR;
  const homeOverride = inputs.env.FLINTTRADE_HOME;
  let workspace: string;
  if (workspaceOverride) {
    workspace = canonicalise(
      appendRaw(currentWorkingDirectory, expandHome(workspaceOverride, homeDirectory, inputs.platform, pathApi), pathApi),
    );
  } else if (homeOverride) {
    workspace = canonicalise(
      appendRaw(currentWorkingDirectory, expandHome(homeOverride, homeDirectory, inputs.platform, pathApi), pathApi),
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
