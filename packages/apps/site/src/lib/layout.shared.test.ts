import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

function readSite(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8');
}

describe('shared Fumadocs layout options', () => {
  it('keeps exactly one GitHub control via githubUrl, not a duplicate icon link', () => {
    const shared = readSite('src/lib/layout.shared.tsx');
    const docsLayout = readSite('src/app/docs/layout.tsx');

    expect(docsLayout).toContain('baseOptions()');
    expect(shared).toContain("githubUrl: 'https://github.com/navaneeshnagarajan/FlintTrade'");
    expect(shared).not.toMatch(/type:\s*'icon'[\s\S]*GitHub/);
    expect(shared).not.toContain("text: 'GitHub'");
    expect(shared).not.toContain('GithubIcon');
  });

  it('keeps a single GitHub control on the marketing header', () => {
    const header = readSite('src/components/site-header.tsx');
    const matches = header.match(/github-link/g) ?? [];

    expect(matches).toHaveLength(1);
    expect(header).toContain('https://github.com/navaneeshnagarajan/FlintTrade');
  });
});
