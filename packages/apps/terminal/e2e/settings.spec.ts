/**
 * settings.spec.ts — Settings full-page route (/settings).
 *
 * SettingsRoute renders:
 *   - A slim header with a "Settings" label and back button
 *   - A left sidebar <nav aria-label="Settings sections"> listing all sections
 *   - A scrollable content area for the active section
 *
 * Section IDs are defined in settingsConfig.ts. The sidebar buttons are
 * vertical tabs using aria-selected for the active entry.
 *
 * Verifies:
 *   - /settings loads and shows the settings sidebar
 *   - Clicking "Appearance" activates that section
 *   - Clicking "Skill & Experience" activates that section
 *   - Deep-link via hash (/settings#api) activates the correct section
 */

import { test, expect } from '@playwright/test';

test.describe('Settings page', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem('flinttrade:dailyWelcomeDismissed', 'true');
      localStorage.setItem('flinttrade:tourComplete', 'true');
    });
    await page.goto('/settings');
    // Wait for the sidebar nav to appear — signals SettingsRoute has mounted
    await page
      .getByRole('navigation', { name: 'Settings sections' })
      .waitFor({ timeout: 15_000 });
  });

  test('settings sidebar is visible', async ({ page }) => {
    const sidebar = page.getByRole('navigation', { name: 'Settings sections' });
    await expect(sidebar).toBeVisible();
  });

  test('sidebar contains expected sections', async ({ page }) => {
    const sidebar = page.getByRole('navigation', { name: 'Settings sections' });
    // A representative subset — defined in SECTIONS array
    for (const label of ['General', 'Appearance', 'Broker Gateway', 'Skill & Experience', 'About']) {
      await expect(sidebar.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test('clicking "Appearance" section activates it', async ({ page }) => {
    const sidebar = page.getByRole('navigation', { name: 'Settings sections' });
    await sidebar.getByText('Appearance', { exact: true }).click();

    const activeTab = sidebar.getByRole('tab', { name: 'Appearance' });
    await expect(activeTab).toHaveAttribute('aria-selected', 'true');
  });

  test('clicking "Skill & Experience" section activates it', async ({ page }) => {
    const sidebar = page.getByRole('navigation', { name: 'Settings sections' });
    await sidebar.getByText('Skill & Experience', { exact: true }).click();

    const activeTab = sidebar.getByRole('tab', { name: 'Skill & Experience' });
    await expect(activeTab).toHaveAttribute('aria-selected', 'true');
  });

  test('back button is present in settings header', async ({ page }) => {
    // The slim header has a back button with aria-label="Go back"
    const backBtn = page.getByRole('button', { name: 'Go back' });
    await expect(backBtn).toBeVisible();
  });

  test('deep-link /settings#api activates Broker Gateway section', async ({ page }) => {
    await page.goto('/settings#api');
    await page
      .getByRole('navigation', { name: 'Settings sections' })
      .waitFor({ timeout: 15_000 });

    const sidebar = page.getByRole('navigation', { name: 'Settings sections' });
    const activeTab = sidebar.getByRole('tab', { name: 'Broker Gateway' });
    await expect(activeTab).toHaveAttribute('aria-selected', 'true');
  });
});
