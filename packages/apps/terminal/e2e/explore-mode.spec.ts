/**
 * explore-mode.spec.ts — Explore mode with hardcoded sample data.
 *
 * Verifies:
 *   - /explore loads and shows the "Explore Mode" banner (sample-data disclaimer)
 *   - The six module cards are all rendered
 *   - The TickerBar (Market indices region) is present on app routes
 *   - Navigating into /trade renders the Dockview workspace shell
 *
 * No broker connection is needed — all data is hardcoded in ExploreRoute.tsx.
 */

import { test, expect } from '@playwright/test';

test.describe('Explore mode', () => {
  test.beforeEach(async ({ page }) => {
    // Suppress the DemoChoice overlay by seeding the localStorage flag that
    // hasMadeDemoChoice() checks. Key: "flinttrade:demoChoice"
    await page.addInitScript(() => {
      localStorage.setItem('flinttrade:demoChoice', 'explore');
    });
  });

  test('/explore shows sample-data disclaimer banner', async ({ page }) => {
    await page.goto('/explore');
    // ExploreRoute renders: <strong>Explore Mode</strong> — All data shown is sample only.
    const banner = page.locator('text=Explore Mode').first();
    await expect(banner).toBeVisible({ timeout: 10_000 });
  });

  test('/explore shows all six module cards', async ({ page }) => {
    await page.goto('/explore');
    // Each ModuleCard has an aria-label "Explore <Title> module"
    const modules = ['Trade', 'Invest', 'Learn', 'Strategy Lab', 'Automate', 'AI'];
    for (const name of modules) {
      await expect(
        page.getByRole('button', { name: new RegExp(`Explore ${name}`, 'i') }),
      ).toBeVisible({ timeout: 10_000 });
    }
  });

  test('/explore renders stats section', async ({ page }) => {
    await page.goto('/explore');
    // The stats row contains "Brokers supported", "Modules", "Strategies", "Indicators"
    await expect(page.getByText('Brokers supported', { exact: false })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText('Modules', { exact: false })).toBeVisible({ timeout: 10_000 });
  });

  test('TickerBar region is present on /trade', async ({ page }) => {
    await page.goto('/trade');
    // TickerBar has role="region" aria-label="Market indices"
    const tickerBar = page.getByRole('region', { name: 'Market indices' });
    await expect(tickerBar).toBeVisible({ timeout: 10_000 });
  });

  test('TickerBar shows "Connect OpenAlgo" prompt when disconnected', async ({ page }) => {
    await page.goto('/trade');
    // When no live data: TickerBar renders a button to navigate to settings
    const prompt = page.getByText('Connect OpenAlgo for live prices', { exact: false });
    await expect(prompt).toBeVisible({ timeout: 10_000 });
  });

  test('/trade renders the Dockview workspace shell', async ({ page }) => {
    await page.goto('/trade');
    // The TerminalRoute wraps Dockview inside a <main aria-label="Trading Workspace">
    // Wait for the main landmark — it is always present once AppLayout mounts
    const main = page.getByRole('main', { name: /Trading Workspace/i });
    await expect(main).toBeVisible({ timeout: 10_000 });
  });
});
