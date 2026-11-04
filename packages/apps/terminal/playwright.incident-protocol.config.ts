import { defineConfig, devices } from "@playwright/test";

// Requires the maintained isolated normal-Core controller, never default/Vite.
export default defineConfig({
  testDir: "./e2e", testMatch: "incident-delivery-protocol.control.ts",
  fullyParallel: false, workers: 1, retries: 0, forbidOnly: true, timeout: 60000,
  outputDir: "/run/test/artifacts/playwright/incident-protocol-controls",
  reporter: [["list"], ["json", { outputFile: "/run/test/artifacts/incident-protocol-results.json" }], ["junit", { outputFile: "/run/test/artifacts/incident-protocol-results.xml" }]],
  use: { headless: true, serviceWorkers: "block", trace: "on" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
