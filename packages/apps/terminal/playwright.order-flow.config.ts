import { defineConfig } from "@playwright/test";
import baseConfig from "./playwright.config";

// The secure runtime runner deliberately clears inherited environment variables.
// This acceptance config owns its Vite process: never reuse a host/other run's
// listener or silently fall forward from the verified loopback port.
process.env["CI"] = "true";

export default defineConfig({
  ...baseConfig,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    ...baseConfig.use,
    trace: "on",
    screenshot: "only-on-failure",
  },
  webServer: {
    ...baseConfig.webServer,
    command: "pnpm run dev --strictPort",
    port: 5173,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { ...process.env, CI: "true", RETICLE_CONNECT: "0" },
  },
});
