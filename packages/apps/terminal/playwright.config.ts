import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for FlintTrade terminal.
 *
 * Tests run against the Vite dev server at localhost:5173.
 * Explore mode is used so no broker connection is required.
 * webServer.reuseExistingServer=true lets you run `pnpm run dev` separately
 * and skip the 10-second Vite startup on each test run.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  forbidOnly: Boolean(process.env['CI']),
  // Each test gets a fresh context (no shared cookies / localStorage)
  fullyParallel: true,
  retries: process.env['CI'] ? 1 : 0,
  reporter: process.env['CI'] ? 'github' : 'list',

  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    // Viewport large enough to avoid the SmallScreenOverlay (< 768 px)
    viewport: { width: 1280, height: 800 },
    // Short trace only on CI failures
    trace: process.env['CI'] ? 'on-first-retry' : 'off',
    // Route interception is the fail-closed API boundary; service workers must
    // not be able to satisfy requests before Playwright sees them.
    serviceWorkers: 'block',
    // Dismiss most dialogs automatically (window.confirm in kill-switch, etc.)
    ignoreHTTPSErrors: true,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'pnpm run dev',
    port: 5173,
    reuseExistingServer: !process.env['CI'],
    timeout: 60_000,
  },
});
