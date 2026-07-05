/**
 * settings.spec.ts — Settings full-page route (/settings).
 *
 * SettingsRoute renders:
 *   - A slim header with a "Settings" label and back button
 *   - A left section tablist labelled "Settings sections"
 *   - A scrollable content area for the active section
 *
 * Section IDs are defined in settingsConfig.ts. The section controls are
 * vertical tabs using aria-selected for the active entry.
 *
 * Verifies:
 *   - /settings loads and shows the settings sidebar
 *   - Clicking "Appearance" activates that section
 *   - Clicking "Skill & Experience" activates that section
 *   - Deep-link via hash (/settings#api) activates the correct section
 */

import { test, expect } from '@playwright/test';
import { seedExploreDemoSession } from './helpers';

test.describe('Settings page', () => {
  test.beforeEach(async ({ page }) => {
    await seedExploreDemoSession(page);
    await page.goto('/settings');
    // Wait for the section tabs to appear — signals SettingsRoute has mounted
    await page
      .getByRole('tablist', { name: 'Settings sections' })
      .waitFor({ timeout: 15_000 });
  });

  test('settings section tabs are visible', async ({ page }) => {
    const sectionTabs = page.getByRole('tablist', { name: 'Settings sections' });
    await expect(sectionTabs).toBeVisible();
  });

  test('section tabs contain expected sections', async ({ page }) => {
    const sectionTabs = page.getByRole('tablist', { name: 'Settings sections' });
    // A representative subset — defined in SECTIONS array
    for (const label of ['General', 'Appearance', 'Broker Gateway', 'Skill & Experience', 'About']) {
      await expect(sectionTabs.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test('clicking "Appearance" section activates it', async ({ page }) => {
    const sectionTabs = page.getByRole('tablist', { name: 'Settings sections' });
    await sectionTabs.getByText('Appearance', { exact: true }).click();

    const activeTab = sectionTabs.getByRole('tab', { name: 'Appearance' });
    await expect(activeTab).toHaveAttribute('aria-selected', 'true');
  });

  test('clicking "Skill & Experience" section activates it', async ({ page }) => {
    const sectionTabs = page.getByRole('tablist', { name: 'Settings sections' });
    await sectionTabs.getByText('Skill & Experience', { exact: true }).click();

    const activeTab = sectionTabs.getByRole('tab', { name: 'Skill & Experience' });
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
      .getByRole('tablist', { name: 'Settings sections' })
      .waitFor({ timeout: 15_000 });

    const sectionTabs = page.getByRole('tablist', { name: 'Settings sections' });
    const activeTab = sectionTabs.getByRole('tab', { name: 'Broker Gateway' });
    await expect(activeTab).toHaveAttribute('aria-selected', 'true');
  });
});
