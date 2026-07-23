#!/usr/bin/env node

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform === "darwin" || process.platform === "linux") {
  const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const source = path.join(desktop, "native", "posix-atomic-promoter", "promote-absent.c");
  const nodeInclude = path.resolve(path.dirname(process.execPath), "..", "include", "node");
  const nodeApiHeader = path.join(nodeInclude, "node_api.h");
  const target = process.platform === "darwin" ? "darwin-universal" : `linux-${process.arch}`;
  assert.ok(
    process.platform === "darwin" || process.arch === "x64" || process.arch === "arm64",
    `Unsupported Linux atomic-promoter architecture: ${process.arch}`,
  );
  const outputDirectory = path.join(desktop, "dist", "native", target);
  const output = path.join(outputDirectory, "flinttrade-fs-promoter.node");
  const temporary = `${output}.tmp-${process.pid}-${randomUUID()}`;
  const requestedCompiler = process.platform === "darwin" ? "/usr/bin/clang" : "/usr/bin/cc";
  const compiler = realpathSync.native(requestedCompiler);
  for (const [label, file] of [
    ["atomic-promoter source", source],
    ["Node N-API header", nodeApiHeader],
    ["trusted C compiler", compiler],
  ]) {
    const metadata = lstatSync(file);
    assert.ok(metadata.isFile() && !metadata.isSymbolicLink(), `${label} must be a no-follow regular file: ${file}`);
  }
  assert.equal(
    path.dirname(outputDirectory),
    path.join(desktop, "dist", "native"),
    "Refusing to clean an unexpected atomic-promoter output directory.",
  );
  rmSync(outputDirectory, { force: true, recursive: true });
  mkdirSync(outputDirectory, { recursive: true });
  const common = [
    "-std=c11",
    "-O2",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-fno-common",
    "-fstack-protector-strong",
    "-I",
    nodeInclude,
    source,
    "-o",
    temporary,
  ];
  const flags = process.platform === "darwin"
    ? ["-bundle", "-undefined", "dynamic_lookup", "-mmacosx-version-min=12.0", "-arch", "arm64", "-arch", "x86_64", ...common]
    : ["-shared", "-fPIC", "-D_FORTIFY_SOURCE=2", "-Wl,-z,relro,-z,now", ...common];
  try {
    execFileSync(compiler, flags, { stdio: "inherit" });
    chmodSync(temporary, 0o555);
    renameSync(temporary, output);
  } finally {
    rmSync(temporary, { force: true });
  }
  if (process.platform === "darwin") {
    const codesign = "/usr/bin/codesign";
    const identity = process.env.FLINTTRADE_NATIVE_MAC_IDENTITY || "-";
    const keychain = process.env.FLINTTRADE_NATIVE_MAC_KEYCHAIN;
    const signingArguments = ["--force", "--sign", identity];
    if (identity === "-") signingArguments.push("--timestamp=none");
    else signingArguments.push("--options", "runtime", "--timestamp");
    if (keychain) {
      assert.ok(path.isAbsolute(keychain), "The native-helper signing keychain must be absolute.");
      signingArguments.push("--keychain", keychain);
    }
    signingArguments.push(output);
    execFileSync(codesign, signingArguments, { stdio: "inherit" });
    execFileSync(codesign, ["--verify", "--strict", output], { stdio: "inherit" });
  }
  const sha256 = createHash("sha256").update(readFileSync(output)).digest("hex");
  writeFileSync(
    path.join(outputDirectory, "flinttrade-fs-promoter.sha256.json"),
    `${JSON.stringify({ executable: "flinttrade-fs-promoter.node", schemaVersion: 1, sha256, target })}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
}
