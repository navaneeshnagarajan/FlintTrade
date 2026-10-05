import { defineConfig, devices } from "@playwright/test";

/** Exercise the public-demo production bundle with no backend or preset fixtures. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "public-demo-presets.spec.ts",
  outputDir: "./test-results/public-demo-presets",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  reporter: process.env["CI"] ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:5173/demo-app/",
    headless: true,
    viewport: { width: 1440, height: 900 },
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "node --experimental-strip-types e2e/start-public-demo.ts",
    url: "http://127.0.0.1:5173/demo-app/",
    // An installed-mode or development server must never satisfy this journey.
    reuseExistingServer: false,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    timeout: 180_000,
  },
});
