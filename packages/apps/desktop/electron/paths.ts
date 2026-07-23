import { lstatSync, readlinkSync, realpathSync } from "node:fs";
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
  lstat(candidate: string): { isSymbolicLink(): boolean } | null;
  readlink(candidate: string): string;
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
    lstat(candidate) {
      try {
        return lstatSync(candidate);
      } catch (error) {
        if (["ELOOP", "ENOENT", "ENOTDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) return null;
        throw error;
      }
    },
    readlink: readlinkSync,
    realpath: realpathSync.native,
  },
): string {
  if (!pathApi.isAbsolute(value)) throw new TypeError("Component-wise canonicalisation requires an absolute path.");
  const split = (input: string): string[] => input.split(pathApi === path.win32 ? /[\\/]+/ : /\/+/).filter(Boolean);
  const root = pathApi.parse(value).root;
  let resolved = hooks.lstat(root) ? hooks.realpath(root) : root;
  const components = split(value.slice(root.length)).map((component) => ({ component, links: new Set<string>() }));
  while (components.length > 0) {
    const { component, links } = components.shift()!;
    if (!component || component === ".") continue;
    if (component === "..") {
      resolved = pathApi.dirname(resolved);
      continue;
    }
    const candidate = pathApi.join(resolved, component);
    const metadata = hooks.lstat(candidate);
    if (!metadata?.isSymbolicLink()) {
      resolved = metadata ? hooks.realpath(candidate) : candidate;
      continue;
    }
    if (links.has(candidate)) {
      resolved = candidate;
      continue;
    }
    const nestedLinks = new Set(links).add(candidate);
    const target = hooks.readlink(candidate);
    if (pathApi.isAbsolute(target)) {
      const targetRoot = pathApi.parse(target).root;
      resolved = hooks.lstat(targetRoot) ? hooks.realpath(targetRoot) : targetRoot;
      components.unshift(
        ...split(target.slice(targetRoot.length)).map((nested) => ({ component: nested, links: nestedLinks })),
      );
    } else {
      components.unshift(...split(target).map((nested) => ({ component: nested, links: nestedLinks })));
    }
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
