/**
 * generate-demo.mjs — build the terminal in Explore mode for the public site.
 *
 * Runs `vite build --base=/demo-app/` in packages/apps/terminal and copies
 * the bundle into public/demo-app/ (gitignored). The Next.js rewrites in
 * next.config.mjs give the SPA its deep-route fallback.
 *
 * Skip with FLINTTRADE_SKIP_DEMO=1 (e.g. docs-only local work).
 */

import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const siteDir = join(here, '..');
const terminalDir = join(siteDir, '..', 'terminal');
const outDir = join(siteDir, 'public', 'demo-app');

if (process.env.FLINTTRADE_SKIP_DEMO === '1') {
  console.log('[generate-demo] FLINTTRADE_SKIP_DEMO=1 — skipping terminal demo build.');
  console.log('[generate-demo] note: without public/demo-app the /demo page will 404 its iframe.');
  process.exit(0);
}

if (!existsSync(join(terminalDir, 'package.json'))) {
  console.error(`[generate-demo] terminal package not found at ${terminalDir}`);
  process.exit(1);
}

if (!existsSync(join(terminalDir, 'node_modules', '.bin', 'vite'))) {
  console.error(
    '[generate-demo] vite not installed in packages/apps/terminal — run a workspace ' +
      'install with devDependencies (NODE_ENV=production installs skip them).',
  );
  process.exit(1);
}

// Strip VITE_* vars so deployment-only secrets/DSNs are never baked into
// the public demo bundle.
const buildEnv = Object.fromEntries(
  Object.entries(process.env).filter(([key]) => !key.startsWith('VITE_')),
);

console.log('[generate-demo] building terminal (vite build --base=/demo-app/)…');
execFileSync(join(terminalDir, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite'), [
  'build',
  '--base=/demo-app/',
], {
  cwd: terminalDir,
  stdio: 'inherit',
  env: buildEnv,
});

const distDir = join(terminalDir, 'dist');
if (!existsSync(join(distDir, 'index.html'))) {
  console.error('[generate-demo] vite build produced no dist/index.html');
  process.exit(1);
}

rmSync(outDir, { recursive: true, force: true });
cpSync(distDir, outDir, { recursive: true });
console.log(`[generate-demo] demo copied to ${outDir}`);
