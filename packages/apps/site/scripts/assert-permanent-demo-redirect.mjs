/**
 * Production check for the public demo entry redirects.
 * Runs after `next build` and fails the build when `next start` does not
 * answer HTTP 308 with Location /demo-app/welcome.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

const siteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const nextBin = path.join(siteRoot, 'node_modules', 'next', 'dist', 'bin', 'next');

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
    server.on('error', reject);
  });
}

async function waitForReady(child, port, logs) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`next start exited before it was ready\n${logs()}`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(1000) });
      if (response.status === 200) return;
    } catch {
      // The listener is not accepting connections yet.
    }
    await delay(200);
  }
  throw new Error(`next start did not become ready\n${logs()}`);
}

const port = await freePort();
let output = '';
const child = spawn(process.execPath, [
  nextBin, 'start', '--hostname', '127.0.0.1', '--port', String(port),
], { cwd: siteRoot, stdio: ['ignore', 'pipe', 'pipe'] });
child.stdout.on('data', (chunk) => { output += chunk; });
child.stderr.on('data', (chunk) => { output += chunk; });

try {
  await waitForReady(child, port, () => output);
  for (const route of ['/demo', '/explore']) {
    const response = await fetch(`http://127.0.0.1:${port}${route}`, {
      method: 'HEAD',
      redirect: 'manual',
    });
    const location = response.headers.get('location');
    assert.equal(response.status, 308, `${route} returned ${response.status}`);
    assert.equal(
      new URL(location ?? '', `http://127.0.0.1:${port}`).pathname,
      '/demo-app/welcome',
      `${route} location ${location}`,
    );
  }
} finally {
  child.kill('SIGTERM');
}
