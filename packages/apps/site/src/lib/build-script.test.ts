import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

const packageJsonPath = path.resolve(process.cwd(), 'package.json');

describe('site production build script', () => {
  it('uses the webpack builder while the Fumadocs/Turbopack production build hangs', () => {
    const pkg = JSON.parse(readFileSync(packageJsonPath, 'utf8')) as {
      scripts?: Record<string, string>;
    };

    expect(pkg.scripts?.build).toContain('--webpack');
  });
});
