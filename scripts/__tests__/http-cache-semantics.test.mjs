// Offline contract tests for every installed copy, including transitive consumers.
// No requests are sent; fixtures contain only synthetic metadata.
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const store = new URL('../../node_modules/.pnpm/', import.meta.url);
const copies = readdirSync(store).filter((name) => name.startsWith('http-cache-semantics@'));
assert.ok(copies.length > 0, 'Install the frozen pnpm workspace before running these tests');

for (const copy of copies) {
  const CachePolicy = require(fileURLToPath(new URL(`${copy}/node_modules/http-cache-semantics`, store)));
  const request = { url: '/fixture.txt', method: 'GET', headers: { host: 'fixture.invalid' } };
  const withRequestCC = (value) => ({ ...request, headers: { ...request.headers, 'cache-control': value } });
  const policy = (cc, { shared = true, headers = {}, age = '10', ...options } = {}) => {
    const result = new CachePolicy(request, {
      status: 200,
      headers: { age, etag: '"fixture-v1"', 'cache-control': cc, ...headers },
    }, { shared, ...options });
    result.now = () => result._responseTime;
    return result;
  };
  const restore = (original) => {
    const restored = CachePolicy.fromObject(JSON.parse(JSON.stringify(original.toObject())));
    restored.now = () => restored._responseTime;
    return restored;
  };

  const prohibited = [
    ['no-cache', {}],
    ['No-Cache', {}],
    ['no-cache=""', {}],
    ['no-cache="etag"', {}],
    ['no-store', {}],
    ['No-Store', {}],
    ['private', {}],
    ['Private', {}],
    ['must-revalidate', {}],
    ['Must-Revalidate', {}],
    ['proxy-revalidate', {}],
    ['Proxy-Revalidate', {}],
    ['s-maxage=1', {}],
    ['S-Maxage=1', {}],
    // An existing library safeguard, not an RFC prohibition on Set-Cookie.
    ['', { headers: { 'set-cookie': 'preference=a' } }],
    ['no-cache', { shared: false }],
    ['no-store', { shared: false }],
    ['must-revalidate', { shared: false }],
  ];
  for (const [directive, options] of prohibited) {
    for (const serialised of [false, true]) {
      test(`${copy}: ${directive || 'shared cookie safeguard'} (${options.shared === false ? 'private' : 'shared'}, serialised=${serialised}) requires validation on every stale route`, () => {
        let p = policy(`max-age=1, stale-while-revalidate=30, stale-if-error=30, ${directive}`, options);
        if (serialised) p = restore(p);
        for (const incoming of [request, withRequestCC('max-stale'), withRequestCC('max-stale=30')]) {
          assert.equal(p.satisfiesWithoutRevalidation(incoming), false);
          const result = p.evaluateRequest(incoming);
          assert.equal(result.response, undefined);
          assert.equal(result.revalidation.synchronous, true);
        }
        assert.equal(p.useStaleWhileRevalidate(), false);
        for (const status of [500, 502, 503, 504]) {
          const result = p.revalidatedPolicy(request, { status, headers: {} });
          assert.equal(result.modified, true);
          assert.equal(result.matches, false);
          assert.notEqual(result.policy, p);
        }
        assert.throws(() => p.revalidatedPolicy(request, undefined), /Response headers missing/);
      });
    }
  }

  const permitted = [
    ['max-age=0', {}],
    ['public, max-age=1', { headers: { 'set-cookie': 'preference=a' } }],
    ['immutable, max-age=1', { headers: { 'set-cookie': 'preference=a' } }],
    ['private, max-age=1', { shared: false }],
    ['proxy-revalidate, max-age=1', { shared: false }],
    ['s-maxage=1, max-age=1', { shared: false }],
    ['max-age=1', { shared: false, headers: { 'set-cookie': 'preference=a' } }],
    ['max-age=1, pre-check=0, post-check=0, no-cache, no-store, must-revalidate', { ignoreCargoCult: true }],
  ];
  for (const [directives, options] of permitted) {
    test(`${copy}: permitted stale reuse survives (${directives}, shared=${options.shared !== false})`, () => {
      const p = restore(policy(`${directives}, stale-while-revalidate=30, stale-if-error=30`, options));
      assert.equal(p.storable(), true);
      assert.equal(p.satisfiesWithoutRevalidation(withRequestCC('max-stale')), true);
      assert.equal(p.satisfiesWithoutRevalidation(withRequestCC('max-stale=30')), true);
      const background = p.evaluateRequest(request);
      assert.ok(background.response);
      assert.equal(background.revalidation.synchronous, false);
      assert.equal(p.useStaleWhileRevalidate(), true);
      for (const status of [500, 502, 503, 504]) {
        assert.deepEqual(p.revalidatedPolicy(request, { status, headers: {} }), {
          policy: p, modified: false, matches: true,
        });
      }
    });
  }

  test(`${copy}: max-stale limits and fresh shared s-maxage remain useful`, () => {
    const p = policy('public, max-age=0');
    assert.equal(p.satisfiesWithoutRevalidation(withRequestCC('max-stale=5')), false);
    assert.equal(p.satisfiesWithoutRevalidation(withRequestCC('max-stale=20')), true);
    assert.equal(policy('public, s-maxage=60').satisfiesWithoutRevalidation(request), true);
    assert.equal(policy('private, max-age=60', { shared: false }).satisfiesWithoutRevalidation(request), true);
    assert.equal(policy('private, max-age=60').storable(), false);
    assert.equal(policy('no-store, max-age=60').storable(), false);
  });

  test(`${copy}: no-cache always validates, while fresh mandatory-stale directives keep error fallback`, () => {
    const noCache = policy('no-cache, max-age=60, stale-if-error=30');
    assert.equal(noCache.revalidatedPolicy(request, { status: 503, headers: {} }).modified, true);
    for (const directives of ['must-revalidate, max-age=60', 's-maxage=60']) {
      const fresh = policy(`${directives}, stale-if-error=30`);
      assert.equal(fresh.stale(), false);
      assert.equal(fresh.revalidatedPolicy(request, { status: 503, headers: {} }).modified, false);
    }
  });

  test(`${copy}: fresh-looking forbidden entries and stored request no-store are never reused`, () => {
    for (const directive of ['no-cache', 'no-store', 'private']) {
      const p = policy(`max-age=60, ${directive}`, { age: '-1' });
      assert.equal(p.satisfiesWithoutRevalidation(request), false);
      assert.equal(p.revalidatedPolicy(request, { status: 503, headers: {} }).modified, true);
    }
    const p = new CachePolicy(withRequestCC('No-Store'), {
      status: 200, headers: { 'cache-control': 'public, max-age=0, stale-if-error=30' },
    });
    assert.equal(p.storable(), false);
    assert.equal(restore(p).satisfiesWithoutRevalidation(withRequestCC('max-stale')), false);
  });

  test(`${copy}: successful conditional validation can still reuse the original body`, () => {
    for (const directives of ['no-cache', 'proxy-revalidate', 's-maxage=1']) {
      const p = policy(`max-age=1, ${directives}`);
      assert.equal(p.revalidationHeaders(request)['if-none-match'], '"fixture-v1"');
      const result = p.revalidatedPolicy(request, {
        status: 304, headers: { etag: '"fixture-v1"', 'cache-control': 'public, max-age=60' },
      });
      assert.equal(result.modified, false);
      assert.equal(result.matches, true);
      assert.equal(result.policy.satisfiesWithoutRevalidation(request), true);
    }
  });

  test(`${copy}: legacy serialised directive names are normalised`, () => {
    const encoded = policy('no-cache, max-age=1, stale-if-error=30').toObject();
    encoded.rescc['No-Cache'] = encoded.rescc['no-cache'];
    delete encoded.rescc['no-cache'];
    const p = CachePolicy.fromObject(encoded);
    p.now = () => p._responseTime;
    assert.equal(p.satisfiesWithoutRevalidation(withRequestCC('max-stale')), false);
    assert.equal(p.revalidatedPolicy(request, { status: 503, headers: {} }).modified, true);
  });

  test(`${copy}: stale-if-error still requires the same URL, host, method and Vary fields`, () => {
    const p = policy('public, max-age=1, stale-if-error=30', { headers: { vary: 'accept-language' } });
    const mismatches = [
      { ...request, url: '/other.txt' },
      { ...request, method: 'POST' },
      { ...request, headers: { host: 'other.invalid' } },
      { ...request, headers: { ...request.headers, 'accept-language': 'fr' } },
    ];
    for (const incoming of mismatches) {
      assert.equal(p.revalidatedPolicy(incoming, { status: 503, headers: {} }).modified, true);
    }
    assert.equal(p.revalidatedPolicy({ ...request, method: 'HEAD' }, { status: 503, headers: {} }).modified, false);
  });
}
