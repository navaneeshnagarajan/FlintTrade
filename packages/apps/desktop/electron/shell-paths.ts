import path from "node:path";

import { canonicalisePathComponents } from "./paths";

export const SHELL_PROFILE_NAME = "flinttrade-shell";

function isWithin(parent: string, child: string, platform: NodeJS.Platform): boolean {
  const caseInsensitive = platform === "win32" || platform === "darwin";
  const left = caseInsensitive ? parent.toLowerCase() : parent;
  const right = caseInsensitive ? child.toLowerCase() : child;
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  const relative = pathApi.relative(left, right);
  return relative === "" ||
    (!relative.startsWith(`..${pathApi.sep}`) && relative !== ".." && !pathApi.isAbsolute(relative));
}

export function resolveShellUserDataPath(appData: string, platform: NodeJS.Platform): string {
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  if (!pathApi.isAbsolute(appData)) throw new Error("Electron appData must be an absolute path.");
  return pathApi.join(pathApi.resolve(appData), SHELL_PROFILE_NAME);
}

export function assertShellUserDataSeparated(
  shellUserData: string,
  workspace: string,
  platform: NodeJS.Platform,
): void {
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  if (!pathApi.isAbsolute(shellUserData) || !pathApi.isAbsolute(workspace)) {
    throw new Error("Electron shell profile and FlintTrade workspace paths must be absolute.");
  }
  const canonicalise = platform === process.platform
    ? (value: string) => canonicalisePathComponents(value, pathApi)
    : (value: string) => pathApi.resolve(value);
  const profile = canonicalise(pathApi.resolve(shellUserData));
  const data = canonicalise(pathApi.resolve(workspace));
  if (isWithin(profile, data, platform) || isWithin(data, profile, platform)) {
    throw new Error("Electron shell profile must be separate from the FlintTrade workspace.");
  }
}
