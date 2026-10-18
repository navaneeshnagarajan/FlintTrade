import path from "node:path";
import { fileURLToPath } from "node:url";
import base from "./playwright.config.ts";

const terminal = path.dirname(fileURLToPath(import.meta.url));
// Exact positive selection: the default carrier reconciles this with its full
// inventory, then releases Vite before starting each installed normal factory.
export default {
  ...base, webServer: undefined,
  testDir: path.join(terminal, "e2e"),
  testMatch: [path.join(terminal, "e2e/schema-csp.spec.ts")],
  fullyParallel: false, forbidOnly: true, workers: 1, retries: 0,
  outputDir: "/run/test/artifacts/playwright",
  reporter: [["list"], ["json", { outputFile: "/run/test/artifacts/csp-results.json" }], ["junit", { outputFile: "/run/test/artifacts/csp-results.xml" }]],
  use: { ...base.use, baseURL: "http://127.0.0.1:5173", serviceWorkers: "block", trace: "on", screenshot: "on", actionTimeout: 8000, ignoreHTTPSErrors: false, bypassCSP: false },
};
