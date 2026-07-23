#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (!new Set(["darwin", "linux"]).has(process.platform)) {
  throw new Error(`The POSIX atomic-promoter gate is unsupported on ${process.platform}.`);
}

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const vitest = path.resolve(packageRoot, "node_modules", ".bin", "vitest");
const result = spawnSync(
  vitest,
  [
    "run",
    "--config",
    "vitest.electron.config.ts",
    "electron/atomic-promoter.integration.test.ts",
  ],
  {
    cwd: packageRoot,
    env: { ...process.env, FLINTTRADE_REQUIRE_ATOMIC_PROMOTER: "1" },
    stdio: "inherit",
  },
);

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
