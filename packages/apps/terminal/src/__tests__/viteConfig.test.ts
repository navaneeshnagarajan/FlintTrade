import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";
import { loadConfigFromFile, loadEnv } from "vite";

const SENTINEL_KEY = "VITE_FT_PUBLIC_DEMO_SENTINEL";
const SENTINEL_VALUE = "synthetic-not-a-secret";

const terminalRoot = path.resolve(import.meta.dirname, "../..");

async function loadTerminalViteConfig() {
  return loadConfigFromFile(
    { command: "build", mode: "test", isSsrBuild: false, isPreview: false },
    path.join(terminalRoot, "vite.config.ts"),
    terminalRoot,
    "info",
    undefined,
    "native",
  );
}

function loadEnvDirInChild(publicDemoBuild: boolean): unknown {
  const script = `
    import { loadConfigFromFile } from "vite";
    import path from "node:path";
    const terminalRoot = ${JSON.stringify(terminalRoot)};
    if (process.env.FLINTTRADE_PUBLIC_DEMO_BUILD !== "1") {
      delete process.env.FLINTTRADE_PUBLIC_DEMO_BUILD;
    }
    const loaded = await loadConfigFromFile(
      { command: "build", mode: "production", isSsrBuild: false, isPreview: false },
      path.join(terminalRoot, "vite.config.ts"),
      terminalRoot,
      "silent",
      undefined,
      "native",
    );
    const envDir = loaded?.config.envDir;
    process.stdout.write(JSON.stringify(envDir === undefined ? null : envDir));
  `;
  const env = { ...process.env };
  if (publicDemoBuild) {
    env.FLINTTRADE_PUBLIC_DEMO_BUILD = "1";
  } else {
    delete env.FLINTTRADE_PUBLIC_DEMO_BUILD;
  }
  const stdout = execFileSync(process.execPath, ["--input-type=module", "-e", script], {
    encoding: "utf8",
    cwd: terminalRoot,
    env,
  });
  return JSON.parse(stdout) as unknown;
}

describe("Vite configuration", () => {
  it("loads through Vite's native config loader", async () => {
    const loaded = await loadTerminalViteConfig();

    expect(loaded?.path).toBe(path.join(terminalRoot, "vite.config.ts"));
    expect(loaded?.config.resolve?.alias).toMatchObject({
      "@": path.join(terminalRoot, "src"),
    });
  });

  it("ordinary terminal builds keep Vite's current dotenv loading behaviour", () => {
    expect(loadEnvDirInChild(false)).not.toBe(false);
  });

  it("public-demo builds set envDir false so Vite cannot load dotenv files", () => {
    expect(loadEnvDirInChild(true)).toBe(false);
  });

  it("proves dotenv isolation with a synthetic sentinel rather than a real .env", () => {
    const sentinelDir = fs.mkdtempSync(path.join(os.tmpdir(), "ft-public-demo-env-"));
    try {
      fs.writeFileSync(path.join(sentinelDir, ".env"), `${SENTINEL_KEY}=${SENTINEL_VALUE}\n`);
      const fromSentinel = loadEnv("production", sentinelDir, "VITE_");
      expect(fromSentinel[SENTINEL_KEY]).toBe(SENTINEL_VALUE);

      // Public-demo config must disable Vite dotenv loading entirely. The
      // sentinel above is synthetic; this assertion never opens a real .env.
      expect(loadEnvDirInChild(true)).toBe(false);
      expect(loadEnvDirInChild(false)).not.toBe(false);
    } finally {
      fs.rmSync(sentinelDir, { recursive: true, force: true });
    }
  });
});
