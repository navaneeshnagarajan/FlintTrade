import { defineConfig, devices } from "@playwright/test";

// The offline runtime runner clears inherited environment variables. Keep the
// browser diagnostics in explicit CI mode even under that allowlisted runner.
process.env["CI"] = "true";

/**
 * Network-independent configuration for the fail-closed infrastructure tests.
 * Registry controls intercept their requests; native decoded-read controls own
 * a test-scoped loopback listener. Neither needs a Vite application server.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: ["infra-self-tests.spec.ts", "run-policy-negative-seams.spec.ts"],
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: true,
  retries: 0,
  reporter: "list",

  use: {
    baseURL: "https://synthetic.flinttrade.invalid",
    headless: true,
    viewport: { width: 1280, height: 800 },
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
