/**
 * Marketing-only copy must not sell native brokers as a working path.
 * Broker sessions are not available in the terminal today. Generated docs
 * are out of scope here.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

function readSite(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8');
}

const marketingSources = [
  'src/app/page.tsx',
  'src/app/contribute/page.tsx',
  'src/app/download/page.tsx',
  'src/app/mcp/page.tsx',
  'src/app/api-reference/page.tsx',
  'src/components/site-header.tsx',
  'src/components/site-footer.tsx',
] as const;

describe('site marketing copy after the native HTTP freeze', () => {
  const marketing = marketingSources.map((path) => readSite(path)).join('\n');
  const homepage = readSite('src/app/page.tsx');

  it('does not market native brokers as a working connect path', () => {
    expect(marketing).not.toContain('verified native brokers');
    expect(marketing).not.toContain('currently verified native');
  });

  it('presents native adapters as evidence-gated, with no working session', () => {
    expect(homepage).toMatch(/Supported native brokers/);
    expect(homepage).toContain('Broker sessions are not available in the terminal yet.');
    expect(homepage).toMatch(/evidence-gated/);
  });

  it('states that a broker session cannot be started from the terminal today', () => {
    expect(homepage).toContain('A broker session cannot be started from the terminal today');
    expect(homepage).toContain('Practice mode works without a broker');
    expect(homepage).not.toContain('Task 9D');
    expect(homepage).not.toContain('Task 7C.2');
    expect(homepage).toMatch(/evidence-gated/);
  });
});
