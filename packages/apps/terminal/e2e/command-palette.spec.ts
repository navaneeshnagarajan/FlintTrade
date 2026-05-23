/**
 * command-palette.spec.ts — Command palette keyboard interaction.
 *
 * The CommandPalette is wired only inside TerminalRoute (/trade).
 * useGlobalKeys fires `onCommandPalette` on Ctrl+K when no input is focused.
 * The palette renders a [role="dialog"] with [aria-label="Command palette"].
 *
 * Verifies:
 *   - Ctrl+K opens the palette on /trade
 *   - Typing a query filters results (section label "Results" appears)
 *   - Escape closes the palette
 */

import { test, expect } from '@playwright/test';

test.describe('Command palette', () => {
  test.beforeEach(async ({ page }) => {
    // Skip DemoChoice / daily-welcome overlays
    await page.addInitScript(() => {
      localStorage.setItem('flinttrade:demoChoice', 'explore');
      sessionStorage.setItem('flinttrade:dailyWelcomeDismissed', 'true');
      // Mark tour complete so InteractiveTour doesn't steal focus
      localStorage.setItem('flinttrade:tourComplete', 'true');
    });
    await page.goto('/trade');
    // Wait for the main workspace shell to be ready
    await page.getByRole('main', { name: /Trading Workspace/i }).waitFor({ timeout: 15_000 });
  });

  test('Ctrl+K opens the command palette', async ({ page }) => {
    // Ensure no input is focused (useGlobalKeys skips when INPUT is active)
    await page.locator('body').click();
    await page.keyboard.press('Control+k');

    const palette = page.getByRole('dialog', { name: 'Command palette' });
    await expect(palette).toBeVisible({ timeout: 5_000 });
  });

  test('command palette input is auto-focused on open', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('Control+k');

    // The combobox input should be focused
    const input = page.getByRole('combobox', { name: /Search commands/i });
    await expect(input).toBeVisible({ timeout: 5_000 });
    await expect(input).toBeFocused();
  });

  test('typing filters results and shows "Results" section label', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('Control+k');

    const input = page.getByRole('combobox', { name: /Search commands/i });
    await input.fill('chart');

    // When query is non-empty, the results list renders a "Results" section label
    await expect(page.getByText('Results', { exact: true })).toBeVisible({ timeout: 3_000 });
  });

  test('Escape closes the command palette', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('Control+k');

    const palette = page.getByRole('dialog', { name: 'Command palette' });
    await expect(palette).toBeVisible({ timeout: 5_000 });

    // Escape is handled in the onKeyDown of the palette input
    await page.keyboard.press('Escape');
    await expect(palette).not.toBeVisible({ timeout: 3_000 });
  });

  test('clicking the overlay backdrop closes the palette', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('Control+k');

    const palette = page.getByRole('dialog', { name: 'Command palette' });
    await expect(palette).toBeVisible({ timeout: 5_000 });

    // The overlay is the fixed inset-0 backdrop — click outside the palette card
    await page.mouse.click(20, 20);
    await expect(palette).not.toBeVisible({ timeout: 3_000 });
  });

  test('no-match query shows empty state message', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('Control+k');

    const input = page.getByRole('combobox', { name: /Search commands/i });
    await input.fill('xyzxyzxyz_nonexistent_query');

    // Empty state: "No commands match"
    await expect(page.getByText(/No commands match/i)).toBeVisible({ timeout: 3_000 });
  });
});
