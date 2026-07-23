#!/usr/bin/env node

import { rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = path.join(packageRoot, "release", "electron");

if (path.dirname(outputDirectory) !== path.join(packageRoot, "release")) {
  throw new Error("Refusing to clean an unexpected Electron output path.");
}
rmSync(outputDirectory, { force: true, recursive: true });
