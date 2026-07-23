#!/usr/bin/env node

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstatSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform === "win32") {
  const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const windowsDirectory = process.env.WINDIR;
  assert.ok(windowsDirectory && path.win32.isAbsolute(windowsDirectory), "WINDIR must identify an absolute trusted Windows directory.");
  const compiler = path.win32.join(windowsDirectory, "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe");
  const programs = [
    {
      label: "Windows Job supervisor",
      output: path.join(desktop, "dist", "native", "win32-x64", "flinttrade-job-supervisor.exe"),
      source: path.join(desktop, "native", "windows-job-supervisor", "Program.cs"),
    },
    {
      label: "Windows source filesystem helper",
      output: path.join(desktop, "dist", "native", "win32-x64", "flinttrade-source-fs.exe"),
      source: path.join(desktop, "native", "windows-source-filesystem", "Program.cs"),
    },
  ];
  for (const [label, target] of [
    ...programs.map((program) => [`${program.label} source`, program.source]),
    ["trusted .NET Framework x64 compiler", compiler],
  ]) {
    const metadata = lstatSync(target);
    assert.ok(metadata.isFile() && !metadata.isSymbolicLink(), `${label} must be a no-follow regular file: ${target}`);
  }
  for (const program of programs) {
    mkdirSync(path.dirname(program.output), { recursive: true });
    execFileSync(
      compiler,
      [
        "/nologo",
        "/target:exe",
        "/platform:x64",
        "/optimize+",
        "/checked+",
        "/warn:4",
        "/warnaserror+",
        `/out:${program.output}`,
        program.source,
      ],
      { stdio: "inherit", windowsHide: true },
    );
    if (program.output.endsWith("flinttrade-source-fs.exe")) {
      const sha256 = createHash("sha256").update(readFileSync(program.output)).digest("hex");
      writeFileSync(
        path.join(path.dirname(program.output), "flinttrade-source-fs.sha256.json"),
        `${JSON.stringify({ executable: "flinttrade-source-fs.exe", schemaVersion: 1, sha256 })}\n`,
        { encoding: "utf8", mode: 0o600 },
      );
    }
  }
}
