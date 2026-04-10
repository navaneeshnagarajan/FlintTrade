/**
 * smoke.spec.ts — Basic app health checks.
 *
 * Verifies:
 *   - The app loads without crashing
 *   - Root "/" redirects to a known FlintTrade route
 *   - The document title contains "FlintTrade"
 *   - The TopBar (chrome header) is visible with route navigation links
 *
 * No broker connection is needed. These tests work in explore / unauthenticated state.
 */

import { test, expect } from '@playwright/test';

test.describe('Smoke — app loads', () => {
  test('root "/" redirects to a known route', async ({ page }) => {
    await page.goto('/');
    // The app should land on /welcome, /explore, /trade, or /login — never stay on bare "/"
    await page.waitForURL(
      (url) => ['welcome', 'explore', 'trade', 'login'].some((seg) => url.pathname.includes(seg)),
      { timeout: 10_000 },
    );
    expect(['welcome', 'explore', 'trade', 'login'].some((seg) =>
      page.url().includes(seg),
    )).toBe(true);
  });

  test('document title contains "FlintTrade"', async ({ page }) => {
    await page.goto('/explore');
    // DemoChoice overlay may appear on first visit — dismiss it if present
    const exploreSelf = page.getByText('Explore Freely', { exact: false });
    if (await exploreSelf.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await exploreSelf.click();
    }
    await expect(page).toHaveTitle(/FlintTrade/i);
  });

  test('TopBar is present on app routes', async ({ page }) => {
    // Navigate directly to /trade — AppLayout renders TopBar
    await page.goto('/trade');
    // TopBar is inside a <header> element
    const header = page.locator('header').first();
    await expect(header).toBeVisible({ timeout: 10_000 });
  });

  test('TopBar contains route navigation links', async ({ page }) => {
    await page.goto('/trade');
    // BASE_ROUTE_TABS: Learn, Invest, Trade — always visible regardless of skill level
    await expect(page.getByRole('link', { name: 'Learn' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: 'Invest' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: 'Trade' })).toBeVisible({ timeout: 10_000 });
  });

  test('/welcome renders without errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await page.goto('/welcome');
    await page.waitForLoadState('networkidle', { timeout: 15_000 });
    // Filter out expected network errors (no broker) and focus on JS errors
    const jsErrors = errors.filter(
      (e) => !e.includes('Failed to fetch') && !e.includes('NetworkError'),
    );
    expect(jsErrors).toHaveLength(0);
  });
});
