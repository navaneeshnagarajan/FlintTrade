import { defineConfig, devices } from "@playwright/test";

/**
 * Advisory visual and axe project.
 *
 * Screenshot mismatches and new axe violations fail the Playwright process.
 * `e2e/visual/run-advisory.mjs` turns that into a green job while
 * `VISUAL_AXE_GATE` is "0". Pixel baselines belong to ubuntu-latest only.
 */
const advisory = process.env["VISUAL_AXE_ADVISORY"] === "1";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "visual-a11y.spec.ts",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env["CI"]),
  retries: 0,
  reporter: advisory
    ? [["list"], ["json", { outputFile: "test-results/visual-a11y.json" }]]
    : "list",

  expect: {
    timeout: 15_000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      scale: "css",
    },
  },

  snapshotPathTemplate: "{testDir}/visual/baselines/{arg}-{projectName}-{platform}.png",

  use: {
    baseURL: "http://localhost:5173",
    headless: true,
    viewport: { width: 1440, height: 900 },
    timezoneId: "UTC",
    locale: "en-IN",
    serviceWorkers: "block",
    trace: "off",
    colorScheme: "dark",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    command: "pnpm run dev",
    port: 5173,
    reuseExistingServer: !process.env["CI"],
    timeout: 120_000,
    env: {
      ...process.env,
      RETICLE_CONNECT: "0",
    },
  },
});
