import path from "node:path";
import { fileURLToPath } from "node:url";
import base from "./playwright.order-flow.config.ts";
const terminal = path.dirname(fileURLToPath(import.meta.url));
export default {
  ...base, testIgnore: [], webServer: undefined,
  testDir: path.join(terminal, "e2e"),
  testMatch: [path.join(terminal, "e2e/run-policy-integrated.spec.ts"), path.join(terminal, "e2e/run-policy-remaining.spec.ts")],
  fullyParallel: false, workers: 1, retries: 0, timeout: 120000,
  outputDir: "/run/test/artifacts/playwright",
  reporter: [["list"], ["json", { outputFile: "/run/test/artifacts/results.json" }], ["junit", { outputFile: "/run/test/artifacts/results.xml" }]],
  use: { ...base.use, baseURL: "http://127.0.0.1:5173", serviceWorkers: "block", trace: "on", screenshot: "on", actionTimeout: 8000 },
};
