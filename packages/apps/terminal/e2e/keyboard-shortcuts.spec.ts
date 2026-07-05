/**
 * keyboard-shortcuts.spec.ts — Keyboard shortcuts dialog.
 *
 * KeyboardShortcutsDialog lives in AppLayout and is opened by:
 *   - Pressing `?` (when no input is focused) — via useGlobalKeys
 *   - Programmatically by other components
 *
 * The dialog renders with [role="dialog"] via shadcn DialogContent.
 * It has a title "Keyboard Shortcuts" and a search input [role="searchbox"].
 *
 * Verifies:
 *   - Pressing `?` on /trade opens the shortcuts dialog
 *   - The dialog shows shortcut categories (Navigation, Trading, Chart, General)
 *   - Searching filters shortcut entries (highlight mark appears)
 *   - Escape closes the dialog
 */

import { test, expect } from '@playwright/test';
import { seedExploreDemoSession } from './helpers';

test.describe('Keyboard shortcuts dialog', () => {
  test.beforeEach(async ({ page }) => {
    await seedExploreDemoSession(page);
    await page.goto('/trade');
    // Wait for AppLayout to mount (TopBar is inside <header>)
    await page.locator('header').first().waitFor({ timeout: 15_000 });
  });

  test('pressing "?" opens the keyboard shortcuts dialog', async ({ page }) => {
    // Ensure no input/button is focused so useGlobalKeys fires
    await page.locator('body').click();
    await page.keyboard.press('?');

    // KeyboardShortcutsDialog uses shadcn Dialog which renders a [role="dialog"]
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    await expect(dialog.getByRole('heading', { name: 'Keyboard Shortcuts' })).toBeVisible();
  });

  test('dialog shows all shortcut categories', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('?');

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // CATEGORY_ORDER: Navigation, Trading, Chart, General
    for (const category of ['Navigation', 'Trading', 'Chart', 'General']) {
      await expect(dialog.getByText(category, { exact: true })).toBeVisible();
    }
  });

  test('search input is present and auto-focused', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('?');

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    const searchBox = dialog.getByRole('searchbox', { name: /Search shortcuts/i });
    await expect(searchBox).toBeVisible();
    await expect(searchBox).toBeFocused({ timeout: 3_000 });
  });

  test('searching "cancel" filters to relevant shortcuts', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('?');

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    const searchBox = dialog.getByRole('searchbox', { name: /Search shortcuts/i });
    await searchBox.fill('cancel');

    // "Cancel all open orders" shortcut should appear; unrelated entries disappear
    await expect(dialog.getByText(/Cancel all open orders/i)).toBeVisible({ timeout: 3_000 });

    // The dialog should no longer show unrelated categories like "Chart" or "General"
    // (they are filtered out when no entries match)
    await expect(dialog.getByText('Chart', { exact: true })).not.toBeVisible();
  });

  test('Escape closes the shortcuts dialog', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('?');

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible({ timeout: 3_000 });
  });

  test('no-match search shows empty state', async ({ page }) => {
    await page.locator('body').click();
    await page.keyboard.press('?');

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    const searchBox = dialog.getByRole('searchbox', { name: /Search shortcuts/i });
    await searchBox.fill('xyznonexistent');

    await expect(dialog.getByText(/No shortcuts match/i)).toBeVisible({ timeout: 3_000 });
  });
});
