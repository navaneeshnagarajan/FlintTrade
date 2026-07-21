#!/usr/bin/env node

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { extractFile } from "@electron/asar";
import { FuseV1Options, FuseVersion, getCurrentFuseWire } from "@electron/fuses";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(packageRoot, "..", "..", "..");
const outputDirectory = path.join(packageRoot, "release", "electron");
const FUSE_DISABLED = 48;
const FUSE_ENABLED = 49;

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

const packagedNotice = readFileSync(path.join(resourcesDirectory, "NOTICE"));
const sourceNotice = readFileSync(path.join(repositoryRoot, "notice"));
assert.deepEqual(packagedNotice, sourceNotice, "The packaged NOTICE differs from the tracked repository NOTICE.");
assert.match(packagedNotice.toString("utf8"), /hermes-agent[\s\S]*commit 7651764ce[\s\S]*MIT License/);

const asarPath = path.join(resourcesDirectory, "app.asar");
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

console.log(`Verified packaged Electron security contract: ${target}`);
console.log("Fuse policy, exact Hermes licence/NOTICE, and restrictive splash CSP are present.");
