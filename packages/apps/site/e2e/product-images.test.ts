import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// Run with Node's test runner against an already-built, running local site.
// This intentionally exercises HTTP routing, not Next's private match helpers.
const origin = new URL(process.env.SITE_IMAGE_TEST_ORIGIN ?? 'http://127.0.0.1:3000');
assert.equal(origin.protocol, 'http:');
assert.ok(['127.0.0.1', '[::1]'].includes(origin.hostname), 'Use an owned loopback server');
const sha256 = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const optimiser = (url: string, width = 640) => {
  const endpoint = new URL('/_next/image', origin);
  endpoint.search = new URLSearchParams({ url, w: String(width), q: '75' }).toString();
  return endpoint;
};

test('the conventional favicon serves the exact canonical SVG without a redirect', async () => {
  const response = await fetch(new URL('/favicon.ico', origin), { redirect: 'manual' });
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type') ?? '', /^image\/svg\+xml\b/);
  assert.deepEqual(
    Buffer.from(await response.arrayBuffer()),
    await readFile(new URL('../../../../docs/assets/logo.svg', import.meta.url)),
  );
});

for (const name of ['trading', 'studio', 'review']) {
  test(`homepage ${name} image is served unchanged at its public asset URL`, async () => {
    const response = await fetch(new URL(`/product/${name}.webp`, origin));
    assert.equal(response.status, 200);
    assert.match(response.headers.get('content-type') ?? '', /^image\/webp\b/);
    assert.equal(
      sha256(new Uint8Array(await response.arrayBuffer())),
      sha256(await readFile(new URL(`../public/product/${name}.webp`, import.meta.url))),
    );
  });

  for (const width of [640, 1920]) {
    test(`homepage ${name} image loads through the Next optimiser at width ${width}`, async () => {
      const response = await fetch(optimiser(`/product/${name}.webp`, width), {
        headers: { Accept: 'image/webp' },
      });
      const bytes = Buffer.from(await response.arrayBuffer());
      assert.equal(response.status, 200, bytes.toString('utf8', 0, 200));
      assert.match(response.headers.get('content-type') ?? '', /^image\/webp\b/);
      assert.match(response.headers.get('vary') ?? '', /Accept/i);
      assert.match(response.headers.get('x-nextjs-cache') ?? '', /^(MISS|HIT|STALE)$/);
      assert.ok(bytes.length > 12);
      assert.equal(bytes.toString('ascii', 0, 4), 'RIFF');
      assert.equal(bytes.toString('ascii', 8, 12), 'WEBP');
    });
  }
}

for (const url of [
  '/favicon.ico',
  '/demo-app/favicon.svg',
  '/product/unapproved.webp',
  '/product/nested/trading.webp',
  '/product/trading.webp?unexpected=1',
  '/product/../favicon.ico',
  'https://example.com/product/trading.webp',
  'http://127.0.0.1:3000/product/trading.webp',
]) {
  test(`the optimiser still refuses unapproved image URL ${url}`, async () => {
    const response = await fetch(optimiser(url));
    assert.equal(response.status, 400);
    assert.equal(await response.text(), '"url" parameter is not allowed');
  });
}
