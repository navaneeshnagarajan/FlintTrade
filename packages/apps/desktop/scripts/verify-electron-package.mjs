#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, lstatSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { extractFile, listPackage } from "@electron/asar";
import { FuseV1Options, FuseVersion, getCurrentFuseWire } from "@electron/fuses";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(packageRoot, "..", "..", "..");
const outputDirectory = path.join(packageRoot, "release", "electron");
const FUSE_DISABLED = 48;
const FUSE_ENABLED = 49;
const SOURCE_BOOTSTRAP_FILES = [
  "checksums/node-release-rafael-gonzaga.asc",
  "checksums/node-v22.23.1-SHASUMS256.txt",
  "checksums/node-v22.23.1-SHASUMS256.txt.sig",
  "checksums/uv-0.11.16-sha256.sum",
  "flinttrade-bootstrap.ps1",
  "flinttrade-bootstrap.sh",
  "flinttrade-safe-rmtree.py",
  "git-common/objects/.flinttrade-empty",
  "git-common/refs/.flinttrade-empty",
  "tool-manifest.json",
].sort();
const expectedBootstrapFiles = [
  ...SOURCE_BOOTSTRAP_FILES,
  ...(process.platform === "win32" ? ["flinttrade-job-supervisor.exe"] : []),
].sort();

function walkManagedFiles(directory, root = directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    const metadata = lstatSync(target);
    assert.equal(metadata.isSymbolicLink(), false, `Packaged managed resource must not be a symlink: ${target}.`);
    if (entry.isDirectory()) files.push(...walkManagedFiles(target, root));
    else if (entry.isFile()) files.push(path.relative(root, target).split(path.sep).join("/"));
    else assert.fail(`Packaged managed resource has an unsupported filesystem type: ${target}.`);
  }
  return files;
}

function walkForPackagedTarget(directory, platform) {
  if (!existsSync(directory)) return [];
  const matches = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (platform === "darwin" && entry.isDirectory() && entry.name === "FlintTrade.app") {
      matches.push(candidate);
      continue;
    }
    if (platform === "win32" && entry.isFile() && entry.name === "FlintTrade.exe") {
      matches.push(candidate);
      continue;
    }
    if (platform === "linux" && entry.isFile() && entry.name === "FlintTrade") {
      matches.push(candidate);
      continue;
    }
    if (entry.isDirectory() && !entry.name.endsWith(".app")) {
      matches.push(...walkForPackagedTarget(candidate, platform));
    }
  }
  return matches;
}

function resolvePackagedTarget() {
  const explicit = process.argv[2];
  if (explicit) return path.resolve(explicit);

  const matches = walkForPackagedTarget(outputDirectory, process.platform);
  assert.equal(
    matches.length,
    1,
    `Expected one packaged ${process.platform} Electron target under ${outputDirectory}, found ${matches.length}.`,
  );
  return matches[0];
}

function resourcesDirectoryFor(target) {
  if (target.endsWith(".app") && statSync(target).isDirectory()) {
    return path.join(target, "Contents", "Resources");
  }
  return path.join(path.dirname(target), "resources");
}

const target = resolvePackagedTarget();
const fuseWire = await getCurrentFuseWire(target);
assert.equal(fuseWire.version, FuseVersion.V1);

const expectedFuses = new Map([
  [FuseV1Options.RunAsNode, FUSE_DISABLED],
  [FuseV1Options.EnableNodeOptionsEnvironmentVariable, FUSE_DISABLED],
  [FuseV1Options.EnableNodeCliInspectArguments, FUSE_DISABLED],
  [FuseV1Options.EnableEmbeddedAsarIntegrityValidation, FUSE_ENABLED],
  [FuseV1Options.OnlyLoadAppFromAsar, FUSE_ENABLED],
  [FuseV1Options.GrantFileProtocolExtraPrivileges, FUSE_DISABLED],
]);
for (const [fuse, expected] of expectedFuses) {
  assert.equal(fuseWire[fuse], expected, `${FuseV1Options[fuse]} has an unsafe packaged state.`);
}

const resourcesDirectory = resourcesDirectoryFor(target);
const packagedLicence = readFileSync(path.join(resourcesDirectory, "licenses", "hermes-agent-LICENSE"));
const sourceLicence = readFileSync(path.join(packageRoot, "resources", "licenses", "hermes-agent-LICENSE"));
assert.deepEqual(packagedLicence, sourceLicence, "The packaged Hermes MIT licence differs from the tracked upstream text.");

const packagedBootstrapFiles = walkManagedFiles(path.join(resourcesDirectory, "bootstrap")).sort();
assert.deepEqual(
  packagedBootstrapFiles,
  expectedBootstrapFiles,
  "The packaged bootstrap contains missing, generated, or unexpected files.",
);
for (const resource of SOURCE_BOOTSTRAP_FILES) {
  const packaged = readFileSync(path.join(resourcesDirectory, "bootstrap", resource));
  const source = readFileSync(path.join(packageRoot, "resources", "bootstrap", resource));
  assert.deepEqual(packaged, source, `The packaged bootstrap resource differs from tracked source: ${resource}.`);
}

for (const installer of ["flinttrade-install.sh", "flinttrade-install.ps1"]) {
  const packaged = readFileSync(path.join(resourcesDirectory, "install", installer));
  const source = readFileSync(path.join(repositoryRoot, "scripts", "install", installer));
  assert.deepEqual(packaged, source, `The packaged shell installer differs from tracked source: ${installer}.`);
}
assert.deepEqual(
  walkManagedFiles(path.join(resourcesDirectory, "install")).sort(),
  ["flinttrade-install.ps1", "flinttrade-install.sh"],
  "The packaged install resource directory contains unexpected files.",
);
if (process.platform !== "win32") {
  const installerMode = statSync(path.join(resourcesDirectory, "install", "flinttrade-install.sh")).mode;
  assert.notEqual(installerMode & 0o111, 0, "The packaged POSIX installer handoff is not executable.");
}

const packagedTrayIcon = readFileSync(path.join(resourcesDirectory, "icons", "tray.png"));
const sourceTrayIcon = readFileSync(path.join(packageRoot, "resources", "icons", "32x32.png"));
assert.deepEqual(packagedTrayIcon, sourceTrayIcon, "The packaged tray icon differs from its tracked source.");
assert.deepEqual(walkManagedFiles(path.join(resourcesDirectory, "icons")), ["tray.png"]);
if (process.platform !== "win32") {
  const bootstrapMode = statSync(path.join(resourcesDirectory, "bootstrap", "flinttrade-bootstrap.sh")).mode;
  assert.notEqual(bootstrapMode & 0o111, 0, "The packaged POSIX bootstrap entrypoint is not executable.");
} else {
  const packagedSupervisor = readFileSync(
    path.join(resourcesDirectory, "bootstrap", "flinttrade-job-supervisor.exe"),
  );
  const builtSupervisor = readFileSync(
    path.join(packageRoot, "dist", "native", "win32-x64", "flinttrade-job-supervisor.exe"),
  );
  assert.deepEqual(
    packagedSupervisor,
    builtSupervisor,
    "The packaged Windows Job supervisor differs from the helper built in this job.",
  );
}

const packagedNotice = readFileSync(path.join(resourcesDirectory, "NOTICE"));
const sourceNotice = readFileSync(path.join(repositoryRoot, "notice"));
assert.deepEqual(packagedNotice, sourceNotice, "The packaged NOTICE differs from the tracked repository NOTICE.");
assert.match(packagedNotice.toString("utf8"), /hermes-agent[\s\S]*commit 7651764ce[\s\S]*MIT License/);

const asarPath = path.join(resourcesDirectory, "app.asar");
const asarEntries = listPackage(asarPath);
for (const entry of asarEntries) {
  assert.doesNotMatch(
    entry,
    /(?:^|\/)(?:src-tauri|payload|__pycache__|\.venv)(?:\/|$)|\.pyc$|flinttrade-backend(?:\.exe)?$/i,
    `The Electron application archive contains a retired desktop artefact: ${entry}.`,
  );
}
for (const required of ["/dist/electron-main.mjs", "/dist/electron-preload.js", "/package.json", "/splash/index.html"]) {
  assert.ok(asarEntries.includes(required), `Required Electron application archive entry is missing: ${required}.`);
}
const packagedMetadata = JSON.parse(extractFile(asarPath, "package.json").toString("utf8"));
const sourceMetadata = JSON.parse(readFileSync(path.join(packageRoot, "package.json"), "utf8"));
assert.equal(packagedMetadata.name, "@flinttrade/desktop");
assert.equal(packagedMetadata.main, "dist/electron-main.mjs");
assert.equal(packagedMetadata.version, sourceMetadata.version);
const packagedSplashHtml = extractFile(asarPath, "splash/index.html").toString("utf8");
const sourceSplashHtml = readFileSync(path.join(packageRoot, "splash", "index.html"), "utf8");
assert.equal(packagedSplashHtml, sourceSplashHtml, "The packaged splash HTML differs from its tracked source.");
assert.match(packagedSplashHtml, /Content-Security-Policy/);
assert.doesNotMatch(packagedSplashHtml, /unsafe-inline/);
assert.doesNotMatch(packagedSplashHtml, /<style(?:\s|>)/i);
assert.doesNotMatch(packagedSplashHtml, /<script(?![^>]*\bsrc=)[^>]*>/i);
for (const asset of ["splash/splash.css", "splash/splash.js"]) {
  assert.ok(extractFile(asarPath, asset).length > 0, `${asset} is missing from app.asar.`);
}

if (process.platform === "darwin") {
  const plist = path.join(target, "Contents", "Info.plist");
  const identifier = spawnSync(
    "/usr/bin/plutil",
    ["-extract", "CFBundleIdentifier", "raw", "-o", "-", plist],
    { encoding: "utf8" },
  );
  assert.equal(identifier.status, 0, identifier.stderr);
  assert.equal(identifier.stdout.trim(), "com.flinttrade.app", "The packaged app identity changed.");

  const signature = spawnSync(
    "/usr/bin/codesign",
    ["--verify", "--deep", "--strict", "--verbose=2", target],
    { encoding: "utf8" },
  );
  assert.equal(signature.status, 0, `The packaged macOS code signature is invalid: ${signature.stderr.trim()}`);

  const architectures = spawnSync(
    "/usr/bin/lipo",
    ["-archs", path.join(target, "Contents", "MacOS", "FlintTrade")],
    { encoding: "utf8" },
  );
  assert.equal(architectures.status, 0, architectures.stderr);
  assert.deepEqual(
    new Set(architectures.stdout.trim().split(/\s+/)),
    new Set(["arm64", "x86_64"]),
    "The macOS Electron package must contain both universal architectures.",
  );
}

console.log(`Verified packaged Electron security contract: ${target}`);
console.log("Fuse, identity/signature, resource, licence/NOTICE, and restrictive splash CSP contracts are present.");
