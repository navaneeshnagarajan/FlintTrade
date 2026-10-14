// Test source: GNU AGPL v3, as licensed in the repository LICENSE.
import path from 'node:path';
import { defineConfig } from '@playwright/test';
const output = process.env.INCIDENT_PROBE_OUTPUT ?? 'test-results/incidents';
export default defineConfig({
  testDir: './e2e/incidents',
  testMatch: 'SystemIncidents.spec.ts',
  outputDir: path.join(output, 'cases'),
  forbidOnly: true,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  reporter: [['list'], ['json', {outputFile: path.join(output, 'report.json')}], ['junit', {outputFile: path.join(output, 'report.xml')}]],
  use: { headless: true, serviceWorkers: 'block', trace: 'on', viewport: {width: 1280, height: 800} },
});
