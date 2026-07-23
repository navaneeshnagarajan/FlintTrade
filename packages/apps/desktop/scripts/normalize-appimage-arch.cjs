#!/usr/bin/env node

// electron-builder afterAllArtifactBuild hook.
//
// electron-builder names the 64-bit Intel AppImage
// "FlintTrade-<version>-linux-x86_64.AppImage": its ${arch} artifact-name token
// maps the x64 architecture to "x86_64" for AppImage (and only for AppImage).
// Every FlintTrade consumer instead requires the canonical
// "FlintTrade-<version>-linux-x64.AppImage": the release workflow's canonical
// installer staging, the Sigstore attestation subject set in
// electron/shell-attestation.ts, and scripts/install/flinttrade-install.sh all
// hard-code "linux-x64". Left unnormalised the release build leg cannot stage
// its canonical installer and a from-source install cannot find the AppImage.
//
// Rename the produced artefact in place so one canonical name flows through
// packaging, attestation and installation. arm64 already resolves to "arm64"
// and is untouched. Runs for every electron-builder invocation (the direct CI
// build leg and the pinned-pnpm pack scripts share this build config).

const { renameSync } = require("node:fs");

const X86_64_APPIMAGE_SUFFIX = /-linux-x86_64\.AppImage$/;

function canonicaliseAppImageArch(artifactPaths) {
  const renamed = [];
  for (const artifactPath of artifactPaths) {
    if (!X86_64_APPIMAGE_SUFFIX.test(artifactPath)) continue;
    const canonical = artifactPath.replace(X86_64_APPIMAGE_SUFFIX, "-linux-x64.AppImage");
    renameSync(artifactPath, canonical);
    renamed.push(canonical);
  }
  return renamed;
}

function normalizeAppImageArch(buildResult) {
  return canonicaliseAppImageArch(buildResult.artifactPaths ?? []);
}

normalizeAppImageArch.canonicaliseAppImageArch = canonicaliseAppImageArch;
module.exports = normalizeAppImageArch;
