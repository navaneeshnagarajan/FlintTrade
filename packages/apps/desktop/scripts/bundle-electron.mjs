#!/usr/bin/env node
// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).

import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distDirectory = resolve(packageRoot, "dist");
const development = process.argv.includes("--dev");

mkdirSync(distDirectory, { recursive: true });

await build({
  entryPoints: [resolve(packageRoot, "electron/main.ts")],
  outfile: resolve(distDirectory, "electron-main.mjs"),
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  external: ["electron"],
  banner: {
    js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
  },
  define: {
    "process.env.FLINTTRADE_DESKTOP_DEVELOPMENT": JSON.stringify(development ? "1" : ""),
  },
  logLevel: "info",
});

await build({
  entryPoints: [resolve(packageRoot, "electron/preload.ts")],
  outfile: resolve(distDirectory, "electron-preload.js"),
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  external: ["electron"],
  define: {
    "process.env.FLINTTRADE_DESKTOP_DEVELOPMENT": JSON.stringify(development ? "1" : ""),
  },
  logLevel: "info",
});
