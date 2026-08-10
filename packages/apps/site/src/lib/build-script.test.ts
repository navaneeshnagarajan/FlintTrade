import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

const siteDir = process.cwd();
const terminalDir = path.resolve(siteDir, '..', 'terminal');
const viteJs = path.join(terminalDir, 'node_modules', 'vite', 'bin', 'vite.js');
const demoGenerator = path.join(siteDir, 'scripts', 'generate-demo.mjs');
const demoOutDir = path.join(siteDir, 'public', 'demo-app');
const terminalDistDir = path.join(terminalDir, 'dist');
const terminalProductionEnv = path.join(terminalDir, '.env.production');

function copyForRestore(source: string, backup: string): boolean {
  if (!fs.existsSync(source)) return false;
  fs.cpSync(source, backup, { recursive: true });
  return true;
}

function restorePath(source: string, backup: string, hadOriginal: boolean): void {
  fs.rmSync(source, { recursive: true, force: true });
  if (hadOriginal) fs.cpSync(backup, source, { recursive: true });
}

function emittedJavaScript(directory: string): string[] {
  if (!fs.existsSync(directory)) return [];
  return fs
    .readdirSync(directory, { recursive: true })
    .filter((entry): entry is string => typeof entry === 'string' && entry.endsWith('.js'))
    .map((entry) => path.join(directory, entry));
}

describe('generate-demo portable launcher', () => {
  it('executes Vite through the active Node executable and JavaScript entry point', () => {
    const result = execFileSync(process.execPath, [viteJs, '--version'], {
      cwd: terminalDir,
      encoding: 'utf8',
      stdio: 'pipe',
    });

    expect(result.trim()).toMatch(/^vite\/\d+\.\d+\.\d+/i);
  });

  it('builds through the real generator without loading terminal dotenv files', () => {
    const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'flinttrade-demo-test-'));
    const envBackup = path.join(temporaryRoot, 'env.production');
    const demoBackup = path.join(temporaryRoot, 'demo-app');
    const distBackup = path.join(temporaryRoot, 'terminal-dist');
    const hadEnv = copyForRestore(terminalProductionEnv, envBackup);
    const hadDemo = copyForRestore(demoOutDir, demoBackup);
    const hadDist = copyForRestore(terminalDistDir, distBackup);
    const sentinel = 'https://synthetic-glitchtip.invalid/demo-env-sentinel';

    try {
      fs.writeFileSync(terminalProductionEnv, `VITE_GLITCHTIP_DSN=${sentinel}\n`, 'utf8');
      const childEnv = { ...process.env, VITE_GLITCHTIP_DSN: sentinel };
      const result = spawnSync(process.execPath, [demoGenerator], {
        cwd: siteDir,
        env: childEnv,
        encoding: 'utf8',
        maxBuffer: 64 * 1024 * 1024,
      });

      if (result.status !== 0) {
        throw new Error(`demo generator failed:\n${result.stderr.slice(-2_000)}`);
      }
      expect(result.error).toBeUndefined();
      expect(result.signal).toBeNull();
      expect(fs.existsSync(path.join(demoOutDir, 'index.html'))).toBe(true);

      const jsFiles = emittedJavaScript(demoOutDir);
      expect(jsFiles.length).toBeGreaterThan(0);
      for (const jsFile of jsFiles) {
        expect(fs.readFileSync(jsFile, 'utf8')).not.toContain(sentinel);
      }
    } finally {
      restorePath(terminalProductionEnv, envBackup, hadEnv);
      restorePath(demoOutDir, demoBackup, hadDemo);
      restorePath(terminalDistDir, distBackup, hadDist);
      fs.rmSync(temporaryRoot, { recursive: true, force: true });
    }
  });
});
