/** Build-only metadata: never send package paths, environment or manifest assets to the renderer. */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const primaryDependencies = [
  "react", "react-dom", "flexlayout-react", "@tanstack/react-query", "@tanstack/react-table",
  "lightweight-charts", "plotly.js-dist-min", "@finos/perspective", "zustand", "framer-motion", "react-router",
] as const;
const buildTools = ["vite", "typescript", "tailwindcss"] as const;

function readJson(file: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(fs.readFileSync(file, "utf8"));
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? value as Record<string, unknown> : {};
  } catch { return {}; }
}
function versionString(value: unknown): string | null {
  return typeof value === "string" && /^[v~^<>=0-9][0-9A-Za-z.+<>=~^| -]{0,79}$/.test(value) ? value : null;
}

export function readVersionInventory(terminalRoot: string) {
  const repoRoot = path.resolve(terminalRoot, "../../..");
  const manifest = readJson(path.join(terminalRoot, "package.json"));
  const dependencies = { ...manifest.dependencies as Record<string, string>, ...manifest.devDependencies as Record<string, string> };
  const require = createRequire(path.join(terminalRoot, "package.json"));
  function installedVersion(name: string): string | null {
    try {
      // Some packages hide package.json with exports. Resolve their entry and
      // walk to the matching package instead; do not execute package code.
      let directory: string;
      try { directory = path.dirname(require.resolve(`${name}/package.json`)); }
      catch { directory = path.dirname(require.resolve(name)); }
      while (directory !== path.dirname(directory)) {
        const candidate = readJson(path.join(directory, "package.json"));
        if (candidate.name === name) return versionString(candidate.version);
        directory = path.dirname(directory);
      }
    } catch { /* Missing build dependency: report unavailable. */ }
    return null;
  }
  const tools = readJson(path.join(repoRoot, "packages/apps/desktop/resources/bootstrap/tool-manifest.json"));
  const desktop = readJson(path.join(repoRoot, "packages/apps/desktop/package.json"));
  const root = readJson(path.join(repoRoot, "package.json"));
  const pin = (name: string) => versionString((tools[name] as Record<string, unknown> | undefined)?.version);
  // This identity is supplied by the existing deployment environment only.
  const commit = process.env.VERCEL_GIT_COMMIT_SHA;
  return {
    commit: commit && /^[a-f0-9]{40}$/i.test(commit) ? commit : null,
    libraries: primaryDependencies.map((name) => ({ name, installed: installedVersion(name), declared: versionString(dependencies[name]) })),
    buildTools: [
      { name: "Node.js (build)", installed: versionString(process.versions.node), declared: null },
      ...buildTools.map((name) => ({ name, installed: installedVersion(name), declared: versionString(dependencies[name]) })),
    ],
    pins: [
      { name: "Node.js bootstrap", version: pin("node") },
      { name: "uv bootstrap", version: pin("uv") },
      { name: "pnpm", version: versionString(typeof root.packageManager === "string" ? root.packageManager.split("@")[1]?.split("+")[0] : null) },
      { name: "Electron shell", version: versionString((desktop.devDependencies as Record<string, unknown> | undefined)?.electron) },
    ],
  };
}
