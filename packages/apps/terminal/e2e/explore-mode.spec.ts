/**
 * explore-mode.spec.ts — installed-app Explore execution-mode journeys.
 *
 * The hosted `/demo-app/` build owns the standalone Explore preview. The
 * installed root build must redirect bare `/explore` to safe onboarding while
 * still supporting a deliberately seeded, local Explore demo session on app
 * routes. No broker connection is needed.
 */

import { test, expect } from '@playwright/test';
import { seedExploreDemoSession } from './helpers';

test.describe('Explore mode', () => {
  test.beforeEach(async ({ page }) => {
    // Suppress the DemoChoice overlay by seeding the localStorage flag that
    // hasMadeDemoChoice() checks. Key: "flinttrade:demoChoice"
    await page.addInitScript(() => {
      localStorage.setItem('flinttrade:demoChoice', 'explore');
    });
  });

  test('installed /explore redirects to safe onboarding', async ({ page }) => {
    await page.goto('/explore');
    await expect(page).toHaveURL(/\/welcome$/);
    await expect(page.getByRole('main', { name: /welcome/i })).toBeVisible({ timeout: 10_000 });
  });

  test('installed /explore query and hash cannot expose hosted public-demo markers', async ({ page }) => {
    await page.goto('/explore?mode=live#modules');
    await expect(page).toHaveURL(/\/welcome$/);
    await expect(page.getByRole('main', { name: /welcome/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: /Explore Trade/i })).toHaveCount(0);
    await expect(page.getByText('Brokers supported', { exact: false })).toHaveCount(0);
  });

  test('TickerBar region is present on /trade', async ({ page }) => {
    await seedExploreDemoSession(page);
    await page.goto('/trade');
    // TickerBar has role="region" aria-label="Market indices"
    const tickerBar = page.getByRole('region', { name: 'Market indices' });
    await expect(tickerBar).toBeVisible({ timeout: 10_000 });
  });

  test('/home shows sample orders and positions without disabled-query spinners', async ({ page }) => {
    await seedExploreDemoSession(page);
    await page.goto('/home');

    const orders = page.getByTestId('orders-card');
    const positions = page.getByTestId('positions-card');
    await expect(orders.getByText('BANKNIFTY')).toBeVisible({ timeout: 10_000 });
    await expect(positions.getByText('RELIANCE')).toBeVisible({ timeout: 10_000 });
    await expect(orders.getByLabel('Loading orders')).toHaveCount(0);
    await expect(positions.getByLabel('Loading positions')).toHaveCount(0);
  });

  test('TickerBar shows broker-connect prompt when disconnected', async ({ page }) => {
    await seedExploreDemoSession(page);
    await page.goto('/trade');
    // When no live data: TickerBar renders a button to navigate to settings
    const prompt = page.getByText('Connect broker for live prices', { exact: false });
    await expect(prompt).toBeVisible({ timeout: 10_000 });
  });

  test('/trade renders the Dockview workspace shell', async ({ page }) => {
    await seedExploreDemoSession(page);
    await page.goto('/trade');
    // The TerminalRoute wraps Dockview inside a <main aria-label="Trading Workspace">
    // Wait for the main landmark — it is always present once AppLayout mounts
    const main = page.getByRole('main', { name: /Trading Workspace/i });
    await expect(main).toBeVisible({ timeout: 10_000 });
  });

  test('/trade keeps execution mode, broker connectivity, and market session distinct', async ({ page }) => {
    await seedExploreDemoSession(page);
    await page.goto('/trade');

    await expect(page.getByText('EXPLORE', { exact: true })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('No broker connected', { exact: true })).toBeVisible();
    await expect(page.getByTestId('market-session-status')).toHaveText(/^Market (open|closed|unavailable)$/);
    await expect(page.getByTestId('market-session-status')).not.toContainText('Live');
  });
});
