import { describe, expect, it } from 'vitest';

import { buildCsp } from './proxy';

describe('site CSP proxy', () => {
  it('allows React development eval support only in development', () => {
    expect(buildCsp('test-nonce', null, 'development')).toContain("'unsafe-eval'");
    expect(buildCsp('test-nonce', null, 'production')).not.toContain("'unsafe-eval'");
  });
});
