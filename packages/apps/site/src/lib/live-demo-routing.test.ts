import { spawn, type ChildProcess } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:net';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

import { describe, expect, it } from 'vitest';

function readSiteFile(relativePath: string): string {
  return readFileSync(path.resolve(process.cwd(), relativePath), 'utf8');
}

function freePort(): Promise<number> {
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

function runProcess(command: string, args: string[], cwd: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    child.stdout?.on('data', (chunk: Buffer) => { output += chunk.toString(); });
    child.stderr?.on('data', (chunk: Buffer) => { output += chunk.toString(); });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} ${args.join(' ')} exited ${code}\n${output}`));
    });
  });
}

describe('site sandbox demo routing', () => {
  it('opens the generated terminal app directly instead of embedding it in an iframe', () => {
    const homePage = readSiteFile('src/app/page.tsx');
    const siteHeader = readSiteFile('src/components/site-header.tsx');
    const demoPage = readSiteFile('src/app/demo/page.tsx');
    const explorePage = readSiteFile('src/app/explore/page.tsx');

    expect(homePage).toContain('href="/demo-app/welcome"');
    expect(homePage).toContain('target="_blank"');
    expect(siteHeader).toContain("href: '/demo-app/welcome'");
    expect(siteHeader).toContain("target={item.newWindow ? '_blank' : undefined}");
    expect(demoPage).not.toContain('<iframe');
    expect(explorePage).not.toContain('<iframe');
  });

  it('redirects /demo and /explore with HTTP 308 from next start', async () => {
    const siteRoot = process.cwd();
    const nextBin = path.join(siteRoot, 'node_modules', 'next', 'dist', 'bin', 'next');
    await runProcess(process.execPath, [nextBin, 'build', '--webpack'], siteRoot);

    const port = await freePort();
    let output = '';
    const child: ChildProcess = spawn(process.execPath, [
      nextBin, 'start', '--hostname', '127.0.0.1', '--port', String(port),
    ], { cwd: siteRoot, stdio: ['ignore', 'pipe', 'pipe'] });
    child.stdout?.on('data', (chunk: Buffer) => { output += chunk.toString(); });
    child.stderr?.on('data', (chunk: Buffer) => { output += chunk.toString(); });

    try {
      const deadline = Date.now() + 30_000;
      let ready = false;
      while (Date.now() < deadline) {
        if (child.exitCode !== null) throw new Error(`next start exited\n${output}`);
        try {
          const home = await fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(1000) });
          if (home.status === 200) {
            ready = true;
            break;
          }
        } catch {
          // The production server is not accepting connections yet.
        }
        await delay(200);
      }
      if (!ready) throw new Error(`next start did not become ready\n${output}`);

      for (const route of ['/demo', '/explore']) {
        const response = await fetch(`http://127.0.0.1:${port}${route}`, {
          method: 'HEAD',
          redirect: 'manual',
        });
        expect(response.status, route).toBe(308);
        const location = response.headers.get('location') ?? '';
        expect(new URL(location, `http://127.0.0.1:${port}`).pathname, route).toBe('/demo-app/welcome');
      }
    } finally {
      child.kill('SIGTERM');
    }
  }, 240_000);

  it('keeps the demo app out of frames now that it launches as its own page', () => {
    const nextConfig = readSiteFile('next.config.mjs');

    expect(nextConfig).toContain("source: '/demo-app/:path*'");
    expect(nextConfig).toContain('"frame-ancestors \'none\'"');
  });
});
