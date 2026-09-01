import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

const generateDemoSource = readFileSync(
  path.resolve(process.cwd(), 'scripts/generate-demo.mjs'),
  'utf8',
);

describe('public-demo generate-demo isolation', () => {
  it('sets FLINTTRADE_PUBLIC_DEMO_BUILD=1 for the terminal public-demo build', () => {
    expect(generateDemoSource).toMatch(
      /buildEnv\.FLINTTRADE_PUBLIC_DEMO_BUILD\s*=\s*['"]1['"]/,
    );
  });

  it('strips inherited VITE_* values before launching the public-demo build', () => {
    expect(generateDemoSource).toMatch(/!key\.startsWith\(['"]VITE_['"]\)/);
  });

  it('launches Vite through portable Node when the current Vite layout supports it', () => {
    expect(generateDemoSource).toContain('process.execPath');
    expect(generateDemoSource).toMatch(/join\([^;]*'vite',\s*'bin',\s*'vite\.js'/);
  });

  it('does not read a real terminal .env file or secrets path', () => {
    expect(generateDemoSource).not.toMatch(/readFileSync\([^)]*\.env/i);
    expect(generateDemoSource).not.toMatch(/['"][^'"]*\.env(?:\.[A-Za-z0-9]+)?['"]/);
  });
});
