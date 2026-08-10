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

  it('declares explicit portable repository-root turbopack.root (three levels above site config)', () => {
    const configSource = readFileSync(
      path.resolve(process.cwd(), 'next.config.mjs'),
      'utf8'
    );
    expect(configSource).toContain("turbopack: {");
    expect(configSource).toContain("root: repoRoot");
    expect(configSource).toContain("fileURLToPath(import.meta.url)");
    expect(configSource).toContain("resolve(__dirname, '../../..')");
  });
});

describe('generate-demo portable launcher (Windows cross-platform)', () => {
  it('uses process.execPath + Vite JS entrypoint (no .cmd shim, no shell:true)', () => {
    const demoScriptPath = path.resolve(
      process.cwd(),
      'scripts',
      'generate-demo.mjs'
    );
    const source = readFileSync(demoScriptPath, 'utf8');
    // RED target: proves must not directly exec .cmd shim on Windows
    expect(source).not.toMatch(/vite\.cmd/);
    // must invoke via portable Node execPath
    expect(source).toContain('process.execPath');
    // must target the .js entrypoint (not bin shim)
    expect(source).toContain('vite.js');
    // no shell:true anywhere
    expect(source).not.toContain('shell: true');
    // uses argv array only (no command string)
    expect(source).not.toMatch(/execFileSync\([^,]+, [^[]/);
  });
});
