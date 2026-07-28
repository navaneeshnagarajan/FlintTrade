/**
 * Brand parity guard — the site hero must render the same wordmark and
 * six-word slogan as the terminal WelcomeRoute, sourced from the
 * design-system brand copy (the single source of truth).
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  BRAND_SLOGAN_SENTENCE,
  BRAND_SLOGAN_WORDS,
  BRAND_WORDMARK,
} from '@flinttrade/design-system/brand';

const pageSource = readFileSync(resolve(process.cwd(), 'src/app/page.tsx'), 'utf8');

describe('brand parity (site hero vs design-system brand copy)', () => {
  it('pins the canonical wordmark and six-word slogan', () => {
    expect(BRAND_WORDMARK).toBe('FlintTrade');
    expect([...BRAND_SLOGAN_WORDS]).toEqual([
      'Learn',
      'Invest',
      'Trade',
      'Automate',
      'Analyse',
      'Evolve',
    ]);
    expect(BRAND_SLOGAN_SENTENCE).toBe('Learn. Invest. Trade. Automate. Analyse. Evolve.');
  });

  it('renders the hero from the shared brand constants', () => {
    expect(pageSource).toContain('const sloganWords = BRAND_SLOGAN_WORDS');
    expect(pageSource).toContain('{BRAND_SLOGAN_SENTENCE}');
    expect(pageSource).toContain('BRAND_WORDMARK.split(');
  });

  it('carries no stale hard-coded slogan words', () => {
    // The pre-parity hero rendered 'Inspect', 'Build', 'Test' instead of the
    // brand's Learn / Invest / Trade. Any literal slogan array is a
    // regression back to drift.
    expect(pageSource).not.toContain("'Inspect'");
    expect(pageSource).not.toMatch(/sloganWords\s*=\s*\[/);
    expect(pageSource).not.toContain('Inspect. Build. Test.');
  });
});
