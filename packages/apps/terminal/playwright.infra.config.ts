import { defineConfig, devices } from "@playwright/test";

/**
 * Network-independent configuration for the fail-closed infrastructure tests.
 * Every HTTP request in the spec is intercepted by the synthetic registry, so
 * this configuration intentionally has no webServer or external service.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "infra-self-tests.spec.ts",
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
