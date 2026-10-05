import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Match the public site's launcher: discard inherited VITE_* values and let
// the terminal config disable dotenv before producing the public-demo bundle.
const demoEnv = Object.fromEntries(
  Object.entries(process.env).filter(([key]) => !key.startsWith("VITE_")),
);
demoEnv.FLINTTRADE_PUBLIC_DEMO_BUILD = "1";
demoEnv.RETICLE_CONNECT = "0";

const outputDir = mkdtempSync(join(tmpdir(), "flinttrade-public-demo-e2e-"));
process.on("exit", () => { rmSync(outputDir, { recursive: true, force: true }); });
const processOptions = { env: demoEnv, stdio: "inherit", shell: process.platform === "win32" } as const;
const build = spawnSync(
  "pnpm",
  ["exec", "vite", "build", "--base=/demo-app/", "--outDir", outputDir, "--emptyOutDir"],
  processOptions,
);
if (build.error) throw build.error;
if (build.status !== 0) process.exit(build.status ?? 1);

const server = spawn(
  "pnpm",
  ["run", "preview", "--base=/demo-app/", "--outDir", outputDir, "--host=127.0.0.1", "--port=5173", "--strictPort"],
  processOptions,
);
server.on("error", (error: Error) => {
  console.error(error.message);
  process.exitCode = 1;
});
server.on("exit", (code) => {
  process.exitCode = code ?? 1;
});
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => { server.kill(signal); });
}
