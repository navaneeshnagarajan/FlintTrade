/**
 * Marketing-only copy must not sell native brokers as a working path.
 * After #170, OpenAlgo is the operator path; native HTTP is frozen until
 * Task 9D (mutations) and Task 7C.2 (read-port cutover). Generated docs
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
    expect(marketing).not.toContain('OpenAlgo bridge plus verified native brokers');
    expect(marketing).not.toContain('connect OpenAlgo or verified native brokers');
    expect(marketing).not.toContain('verified native brokers');
    expect(marketing).not.toContain('currently verified native');
    expect(marketing).not.toContain('Native and OpenAlgo broker integrations documented');
  });

  it('presents OpenAlgo as the working broker path on the homepage', () => {
    expect(homepage).toMatch(/OpenAlgo-compatible bridge is the working broker path/);
    expect(homepage).toContain('connect the OpenAlgo-compatible bridge');
  });

  it('mentions native only as evidence-gated and frozen until Task 9D and Task 7C.2', () => {
    expect(homepage).toContain('Task 9D');
    expect(homepage).toContain('Task 7C.2');
    expect(homepage).toMatch(/frozen until Task 9D and Task 7C\.2/);
    expect(homepage).toMatch(/evidence-gated/);
  });
});
