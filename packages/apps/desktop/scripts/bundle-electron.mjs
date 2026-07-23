#!/usr/bin/env node
// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).

import { mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distDirectory = resolve(packageRoot, "dist");
const development = process.argv.includes("--dev");

function windowsSourceFilesystemDigest() {
  if (process.platform !== "win32") return "0".repeat(64);
  const manifestPath = resolve(
    packageRoot,
    "dist/native/win32-x64/flinttrade-source-fs.sha256.json",
  );
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (
    !manifest ||
    typeof manifest !== "object" ||
    Array.isArray(manifest) ||
    Object.keys(manifest).sort().join(",") !== "executable,schemaVersion,sha256" ||
    manifest.executable !== "flinttrade-source-fs.exe" ||
    manifest.schemaVersion !== 1 ||
    typeof manifest.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(manifest.sha256)
  ) {
    throw new Error("Windows source filesystem helper digest manifest is invalid.");
  }
  return manifest.sha256;
}

const sourceFilesystemSha256 = windowsSourceFilesystemDigest();

function posixAtomicPromoterIdentity() {
  if (process.platform === "win32") {
    return { sha256: "0".repeat(64), target: "windows-unused" };
  }
  const target = process.platform === "darwin" ? "darwin-universal" : `linux-${process.arch}`;
  const manifestPath = resolve(
    packageRoot,
    "dist",
    "native",
    target,
    "flinttrade-fs-promoter.sha256.json",
  );
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (
    !manifest ||
    typeof manifest !== "object" ||
    Array.isArray(manifest) ||
    Object.keys(manifest).sort().join(",") !== "executable,schemaVersion,sha256,target" ||
    manifest.executable !== "flinttrade-fs-promoter.node" ||
    manifest.schemaVersion !== 1 ||
    manifest.target !== target ||
    typeof manifest.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(manifest.sha256)
  ) {
    throw new Error("POSIX atomic-promoter digest manifest is invalid.");
  }
  return { sha256: manifest.sha256, target };
}

const atomicPromoter = posixAtomicPromoterIdentity();

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
    __FLINTTRADE_POSIX_ATOMIC_PROMOTER_SHA256__: JSON.stringify(atomicPromoter.sha256),
    __FLINTTRADE_POSIX_ATOMIC_PROMOTER_TARGET__: JSON.stringify(atomicPromoter.target),
    __FLINTTRADE_WINDOWS_SOURCE_FS_SHA256__: JSON.stringify(sourceFilesystemSha256),
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
