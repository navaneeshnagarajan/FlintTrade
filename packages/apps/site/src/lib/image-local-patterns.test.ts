import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { beforeAll, expect, it } from 'vitest';

type LocalPattern = { pathname?: string; search?: string };

// Every local image passed to next/image must be allowed by
// images.localPatterns, or the optimizer answers 400 in production builds.
const srcRoot = resolve(__dirname, '..');
let patterns: LocalPattern[] = [];

beforeAll(async () => {
  const configUrl = pathToFileURL(resolve(__dirname, '../../next.config.mjs')).href;
  const config = (await import(configUrl)) as { default: { images?: { localPatterns?: LocalPattern[] } } };
  patterns = config.default.images?.localPatterns ?? [];
});

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [path] : [];
  });
}

function allowed(pathname: string): boolean {
  return patterns.some((pattern) => {
    if (pattern.search !== undefined || !pattern.pathname) return false;
    if (pattern.pathname.endsWith('/**')) return pathname.startsWith(pattern.pathname.slice(0, -2));
    return pathname === pattern.pathname;
  });
}

it('allows every local next/image source through the image optimizer', () => {
  const sources = new Set<string>();
  for (const file of sourceFiles(srcRoot)) {
    const text = readFileSync(file, 'utf8');
    if (!/from ['"]next\/image['"]/.test(text)) continue;
    for (const match of text.matchAll(/<Image[^>]*?\ssrc=["'](\/[^"'?]+)["']/gs)) sources.add(match[1]);
  }
  expect(sources.size).toBeGreaterThan(0);
  for (const source of sources) {
    expect(allowed(source), `${source} is allowed by images.localPatterns`).toBe(true);
  }
});

it('serves the product screenshots through the image optimizer', () => {
  for (const asset of ['trading.webp', 'studio.webp', 'review.webp']) {
    expect(allowed(`/product/${asset}`)).toBe(true);
  }
});
