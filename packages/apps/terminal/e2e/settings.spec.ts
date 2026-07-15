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

import { test, expect, type Page, type Request } from '@playwright/test';
import { seedExploreDemoSession } from './helpers';

const ADMISSION_ID_PATTERN = /^adm_[0-9a-f]{32}$/;
const UPDATE_OPERATION_ID = `op_${'1'.repeat(32)}`;
const ROLLBACK_OPERATION_ID = `op_${'2'.repeat(32)}`;
const UNINSTALL_OPERATION_ID = `op_${'3'.repeat(32)}`;
const INSTALL_OPERATION_ID = `op_${'4'.repeat(32)}`;

function mutationAdmission(request: Request): string {
  const body = request.postDataJSON() as Record<string, unknown>;
  const admissionId = body.admission_id;
  expect(typeof admissionId).toBe('string');
  expect(admissionId as string).toMatch(ADMISSION_ID_PATTERN);
  return admissionId as string;
}

async function mockManagedOllamaConfig(page: Page, model = 'qwen3:8b') {
  await page.route('**/ft-api/v1/config/llm', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        data: { provider: 'ollama', host: '', model, api_key_configured: false },
      }),
    });
  });
}

function managedOllamaStatus(overrides: Record<string, unknown> = {}) {
  return {
    version: 'v0.32.0',
    active_version: 'v0.32.0',
    target_version: 'v0.32.0',
    previous_version: null,
    update_available: false,
    rollback_available: false,
    rollback_allowed: false,
    rollback_blocked_reason: null,
    repair_allowed: false,
    repair_blocked_reason: 'Runtime repair is not required.',
    supported: true,
    installed: true,
    state: 'installed',
    ready: false,
    managed_process: false,
    external_process: false,
    downloaded_bytes: 0,
    download_total_bytes: 0,
    install_required_bytes: 1_000_000_000,
    operation: null,
    model_pull: null,
    ...overrides,
  };
}

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
    for (const label of ['General', 'Appearance', 'Broker Gateway', 'Skill & Experience', 'Report Bug', 'About']) {
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

  test('Broker Gateway edits stay local until one explicit complete save', async ({ page }) => {
    const posts: Array<Record<string, unknown>> = [];
    await page.route('**/ft-api/v1/config/openalgo', async (route) => {
      if (route.request().method() === 'POST') {
        posts.push(route.request().postDataJSON() as Record<string, unknown>);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'ok', message: 'saved' }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          data: {
            api_key: 'browser-existing-key',
            api_key_configured: true,
            api_key_last4: '-key',
            host: 'http://127.0.0.1:5000',
            port: 5000,
            ws_port: 8765,
          },
        }),
      });
    });
    // The shared beforeEach has already loaded /settings. Use a distinct query
    // so this is a full document navigation after the route mock is installed,
    // rather than a hash-only navigation that reuses the failed initial read.
    await page.goto('/settings?openalgo-mock=1#api');

    const host = page.getByLabel('OpenAlgo-compatible URL');
    const apiKey = page.getByLabel('OpenAlgo-compatible API key');
    await expect(host).toHaveValue('http://127.0.0.1:5000');
    await expect(apiKey).toHaveValue('');
    await expect(page.getByText(/A key is saved ending in -key/i)).toBeVisible();

    await host.fill('https://openalgo.local');
    await page.getByLabel('REST port').fill('5010');
    expect(posts).toHaveLength(0);

    await page.getByRole('button', { name: 'Save Connection' }).click();
    await expect.poll(() => posts.length).toBe(1);
    expect(posts[0]).toEqual({
      host: 'https://openalgo.local',
      port: '5010',
      ws_port: '8765',
    });
    await expect(page.getByText('Connection settings saved.', { exact: true })).toBeVisible();
  });

  test('managed Ollama update, rollback, uninstall, and reinstall preserve the model inventory', async ({ page }) => {
    const operations: Array<{ path: string; admissionId: string; responseStatus: number }> = [];
    const retainedModels = [
      {
        name: 'qwen3:8b',
        inference_model: `flinttrade/sha256-${'a'.repeat(64)}:locked`,
        digest: 'a'.repeat(64),
        accepted_digest: 'a'.repeat(64),
        digest_drift: false,
      },
    ];
    let runtime = managedOllamaStatus({
      active_version: 'v0.31.2',
      update_available: true,
    });
    let terminalAfterPoll: Record<string, unknown> | null = null;
    await mockManagedOllamaConfig(page);
    await page.route('**/ft-api/v1/ai/local-runtime/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/models') && route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'success', data: retainedModels }),
        });
        return;
      }
      if (path.endsWith('/status')) {
        if (terminalAfterPoll) {
          runtime = terminalAfterPoll;
          terminalAfterPoll = null;
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'success', data: runtime }),
        });
        return;
      }

      const admissionId = mutationAdmission(route.request());
      let responseStatus = 200;
      if (path.endsWith('/update')) {
        responseStatus = 202;
        runtime = managedOllamaStatus({
          active_version: 'v0.31.2',
          update_available: true,
          state: 'downloading',
          operation: {
            id: UPDATE_OPERATION_ID,
            admission_id: admissionId,
            kind: 'update',
            state: 'running',
          },
        });
        terminalAfterPoll = managedOllamaStatus({
          active_version: 'v0.32.0',
          previous_version: 'v0.31.2',
          rollback_available: true,
          rollback_allowed: true,
          operation: {
            id: UPDATE_OPERATION_ID,
            admission_id: admissionId,
            kind: 'update',
            state: 'succeeded',
          },
        });
      } else if (path.endsWith('/rollback')) {
        runtime = managedOllamaStatus({
          active_version: 'v0.31.2',
          operation: {
            id: ROLLBACK_OPERATION_ID,
            admission_id: admissionId,
            kind: 'rollback',
            state: 'succeeded',
          },
        });
      } else if (path.endsWith('/uninstall')) {
        runtime = managedOllamaStatus({
          active_version: '',
          installed: false,
          state: 'not_installed',
          operation: {
            id: UNINSTALL_OPERATION_ID,
            admission_id: admissionId,
            kind: 'uninstall',
            state: 'succeeded',
          },
        });
      } else if (path.endsWith('/install')) {
        responseStatus = 202;
        runtime = managedOllamaStatus({
          active_version: '',
          installed: false,
          state: 'downloading',
          operation: {
            id: INSTALL_OPERATION_ID,
            admission_id: admissionId,
            kind: 'install',
            state: 'running',
          },
        });
        terminalAfterPoll = managedOllamaStatus({
          state: 'ready',
          ready: true,
          managed_process: true,
          operation: {
            id: INSTALL_OPERATION_ID,
            admission_id: admissionId,
            kind: 'install',
            state: 'succeeded',
          },
        });
      }
      operations.push({ path, admissionId, responseStatus });
      await route.fulfill({
        status: responseStatus,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success', data: runtime }),
      });
    });

    await page.goto('/settings?e2e=ollama-lifecycle#llm');

    await expect(page.getByRole('tab', { name: 'LLM Config' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('Runtime v0.31.2')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Update runtime' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Stop runtime' })).toHaveCount(0);

    await page.getByRole('button', { name: 'Update runtime' }).click();
    await page.getByRole('button', { name: 'Download and update' }).click();
    await expect(page.getByText('Runtime v0.32.0')).toBeVisible();

    await page.getByRole('button', { name: 'Rollback runtime' }).click();
    await page.getByRole('button', { name: 'Switch to v0.31.2' }).click();
    await expect(page.getByText('Runtime v0.31.2')).toBeVisible();

    await page.getByRole('button', { name: 'Uninstall runtime' }).click();
    await expect(page.getByText(/Models and accepted-digest metadata will remain/i)).toBeVisible();
    await page.getByRole('button', { name: 'Remove runtime' }).click();
    await expect(page.getByText('Not installed')).toBeVisible();
    expect(retainedModels).toHaveLength(1);

    await page.getByRole('button', { name: 'Install runtime' }).click();
    await page.getByRole('button', { name: 'Download and install' }).click();
    await expect(page.getByText('Model installed')).toBeVisible();

    expect(operations.map(({ path, responseStatus }) => ({ path, responseStatus }))).toEqual([
      { path: '/ft-api/v1/ai/local-runtime/update', responseStatus: 202 },
      { path: '/ft-api/v1/ai/local-runtime/rollback', responseStatus: 200 },
      { path: '/ft-api/v1/ai/local-runtime/uninstall', responseStatus: 200 },
      { path: '/ft-api/v1/ai/local-runtime/install', responseStatus: 202 },
    ]);
    expect(new Set(operations.map(({ admissionId }) => admissionId)).size).toBe(4);
    expect(retainedModels).toHaveLength(1);
  });

  test('managed Ollama protects an alias-equivalent selected model at a narrow viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.route('**/ft-api/v1/config/llm', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          data: { provider: 'ollama', host: '', model: 'qwen3', api_key_configured: false },
        }),
      });
    });
    await page.route('**/ft-api/v1/ai/local-runtime/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          data: managedOllamaStatus({
            previous_version: 'v0.31.2',
            rollback_available: true,
            rollback_allowed: false,
            rollback_blocked_reason: 'Stop the runtime before rollback',
            state: 'ready',
            ready: true,
            managed_process: true,
            server_version: '0.32.0',
          }),
        }),
      });
    });
    await page.route('**/ft-api/v1/ai/local-runtime/models', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          data: [
            { name: 'qwen3:latest', digest: 'a'.repeat(64), size: 5_000_000_000 },
            { name: 'other:latest', digest: 'b'.repeat(64), size: 2_000_000_000 },
          ],
        }),
      });
    });

    await page.goto('/settings?e2e=ollama-models#llm');

    await expect(page.getByText('other:latest')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Delete qwen3:latest' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Delete other:latest' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Prune unused model aliases' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test('managed Ollama recovers from a failed operation poll and waits for terminal server state', async ({ page }) => {
    let statusRequests = 0;
    const admissionId = `adm_${'6'.repeat(32)}`;
    await mockManagedOllamaConfig(page);
    await page.route('**/ft-api/v1/ai/local-runtime/status', async (route) => {
      statusRequests += 1;
      // Development StrictMode can consume two initial status reads. Fail the
      // first actual poll after both mounts have observed the running job.
      if (statusRequests === 3) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'error', message: 'transient status failure' }),
        });
        return;
      }
      const running = statusRequests < 4;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          data: managedOllamaStatus(running
            ? {
              state: 'downloading',
              operation: {
                id: UPDATE_OPERATION_ID,
                admission_id: admissionId,
                kind: 'update',
                state: 'running',
              },
            }
            : {
              state: 'ready',
              ready: true,
              managed_process: true,
              operation: {
                id: UPDATE_OPERATION_ID,
                admission_id: admissionId,
                kind: 'update',
                state: 'succeeded',
              },
            }),
        }),
      });
    });
    await page.route('**/ft-api/v1/ai/local-runtime/models', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"success","data":[]}' });
    });

    await page.goto('/settings?e2e=ollama-poll-recovery#llm');

    await expect(page.getByRole('button', { name: 'Cancel local AI operation' })).toBeVisible();
    await expect(page.getByRole('alert')).toContainText('transient status failure', { timeout: 7_000 });
    await expect(page.getByRole('button', { name: 'Cancel local AI operation' })).toBeVisible();
    await expect(page.getByText('Ready')).toBeVisible({ timeout: 8_000 });
    await expect(page.getByRole('button', { name: 'Cancel local AI operation' })).toHaveCount(0);
    expect(statusRequests).toBeGreaterThanOrEqual(3);
  });

  test('managed Ollama reconciles a timed-out install with the same late admission receipt', async ({ page }) => {
    const admissions: string[] = [];
    let installRequests = 0;
    let installExecutions = 0;
    let runningStatusReads = 0;
    let admittedRuntime: ReturnType<typeof managedOllamaStatus> | null = null;
    let runtime = managedOllamaStatus({
      active_version: '',
      installed: false,
      state: 'not_installed',
    });
    await mockManagedOllamaConfig(page);
    await page.route('**/ft-api/v1/ai/local-runtime/models', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"success","data":[]}' });
    });
    await page.route('**/ft-api/v1/ai/local-runtime/install', async (route) => {
      installRequests += 1;
      const admissionId = mutationAdmission(route.request());
      admissions.push(admissionId);
      if (installRequests === 1) {
        installExecutions += 1;
        admittedRuntime = managedOllamaStatus({
          active_version: '',
          installed: false,
          state: 'downloading',
          operation: {
            id: INSTALL_OPERATION_ID,
            admission_id: admissionId,
            kind: 'install',
            state: 'running',
          },
        });
        runtime = managedOllamaStatus({
          active_version: '',
          installed: false,
          state: 'not_installed',
        });
        await route.abort('timedout');
        return;
      }

      expect(admissionId).toBe(admissions[0]);
      expect(admittedRuntime).not.toBeNull();
      runtime = admittedRuntime as ReturnType<typeof managedOllamaStatus>;
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success', data: runtime }),
      });
    });
    await page.route('**/ft-api/v1/ai/local-runtime/status', async (route) => {
      if (installRequests >= 2) {
        runningStatusReads += 1;
        if (runningStatusReads >= 2) {
          runtime = managedOllamaStatus({
            state: 'ready',
            ready: true,
            managed_process: true,
            operation: {
              id: INSTALL_OPERATION_ID,
              admission_id: admissions[0],
              kind: 'install',
              state: 'succeeded',
            },
          });
        }
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success', data: runtime }),
      });
    });

    await page.goto('/settings?e2e=ollama-late-admission#llm');

    const installButton = page.getByRole('button', { name: 'Install runtime' });
    await installButton.click();
    await page.getByRole('button', { name: 'Download and install' }).click();
    await expect(page.getByText('Reconciling operation')).toBeVisible();
    await expect(installButton).toBeDisabled();
    await expect.poll(() => installRequests, { timeout: 6_000 }).toBe(2);
    expect(admissions).toHaveLength(2);
    expect(admissions[1]).toBe(admissions[0]);
    expect(installExecutions).toBe(1);
    await expect(page.getByText('Ready')).toBeVisible({ timeout: 8_000 });
    await expect(page.getByRole('button', { name: 'Cancel local AI operation' })).toHaveCount(0);
  });

  test('managed Ollama disables mutations while retained status is stale and keeps polling', async ({ page }) => {
    let statusRequests = 0;
    let failStatus = false;
    await mockManagedOllamaConfig(page);
    await page.route('**/ft-api/v1/ai/local-runtime/status', async (route) => {
      statusRequests += 1;
      if (failStatus) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'error', message: 'runtime status is stale' }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          data: managedOllamaStatus({ active_version: '', installed: false, state: 'not_installed' }),
        }),
      });
    });

    await page.goto('/settings?e2e=ollama-stale-status#llm');

    const installButton = page.getByRole('button', { name: 'Install runtime' });
    const provider = page.getByRole('combobox', { name: 'LLM provider' });
    const refresh = page.getByRole('button', { name: 'Refresh runtime status' });
    await expect(installButton).toBeEnabled();
    await expect(page.getByText('Not installed')).toBeVisible();
    const freshRequestCount = statusRequests;
    failStatus = true;
    await refresh.click();

    await expect(page.getByRole('alert')).toContainText('runtime status is stale');
    await expect(page.getByText('Not installed')).toBeVisible();
    await expect(installButton).toBeDisabled();
    await expect(page.getByLabel('LLM model name')).toBeDisabled();
    await expect(provider).toBeEnabled();
    await expect(refresh).toBeEnabled();
    await expect.poll(() => statusRequests, { timeout: 6_000 }).toBeGreaterThan(freshRequestCount + 1);
  });

  test('managed Ollama does not render terminal operation bytes as live progress', async ({ page }) => {
    const admissionId = `adm_${'7'.repeat(32)}`;
    await mockManagedOllamaConfig(page);
    await page.route('**/ft-api/v1/ai/local-runtime/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          data: managedOllamaStatus({
            state: 'ready',
            ready: true,
            managed_process: true,
            downloaded_bytes: 1_000,
            download_total_bytes: 1_000,
            operation: {
              id: UPDATE_OPERATION_ID,
              admission_id: admissionId,
              kind: 'update',
              state: 'succeeded',
            },
          }),
        }),
      });
    });
    await page.route('**/ft-api/v1/ai/local-runtime/models', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"success","data":[]}' });
    });

    await page.goto('/settings?e2e=ollama-terminal-progress#llm');

    await expect(page.getByText('Ready')).toBeVisible();
    await expect(page.getByRole('progressbar', { name: 'Local AI operation progress' })).toHaveCount(0);
  });

  test('Report Bug deep link stays honest and unobscured in Explore demo', async ({ page }) => {
    let diagnosticsRequested = false;
    await page.route('**/ft-api/v1/support/diagnostics', async (route) => {
      diagnosticsRequested = true;
      await route.abort();
    });
    await page.setViewportSize({ width: 960, height: 640 });
    await page.goto('/settings#support');

    const sectionTabs = page.getByRole('tablist', { name: 'Settings sections' });
    await expect(sectionTabs.getByRole('tab', { name: 'Report Bug' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('switch', { name: 'Include diagnostic summary in GitHub draft' })).not.toBeChecked();
    await expect(page.getByLabel('GitHub draft preview')).toContainText('Not included in this GitHub draft.');
    await expect(page.getByText(/Diagnostics are unavailable in Explore demo/i)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Download diagnostics' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Open AI Tutor' })).toHaveCount(0);
    expect(diagnosticsRequested).toBe(false);
  });
});
