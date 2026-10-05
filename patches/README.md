# Dependency patches

## http-cache-semantics 4.3.0

This is a local defensive patch, not a claim that upstream 4.3.0 fixes
GHSA-ch52-4w7c-c8xp. The upstream maintainer disputes the advisory's claim that
`Set-Cookie` by itself prohibits cache sharing. RFC 9111 section 7.3 supports
that distinction. The advisory still has no published fixed-version event.

Sources:

- [Maintainer's response](https://github.com/kornelski/http-cache-semantics/issues/56#issuecomment-5975759591)
- [Advisory database review request](https://github.com/github/advisory-database/issues/10139)
- [RFC 9111 stale-response restrictions](https://www.rfc-editor.org/rfc/rfc9111.html#section-4.2.4)
- [Upstream 4.3.0 source](https://github.com/kornelski/http-cache-semantics/tree/b1d4bd682fbab0252985de45219f4e7497c0067c)

The concrete contract enforced here is that client `max-stale`,
`stale-while-revalidate`, and `stale-if-error` cannot override storage
restrictions or mandatory validation (`no-cache`, `must-revalidate`, and,
for shared caches, `proxy-revalidate` and `s-maxage`). Error fallback must
also match the original URL, host, method and `Vary` fields. Directive names
are normalised for both new and already-serialised policies.

Separately, the patch consistently preserves upstream's conservative
shared-cookie opt-in safeguard. That is a library policy, not an RFC ban on
caching every response with `Set-Cookie`. Explicit `public`/`immutable` opt-ins,
private caches, ordinary zero freshness and valid conditional revalidation
remain supported. A zero freshness lifetime alone is never used as a
prohibition on stale reuse.

The registry tarball and its BSD-2-Clause licence are unchanged. Before
publication, verify the generated lockfile retains the upstream SHA-512
integrity and records the patch hash, then check a frozen install. No package
is renamed or republished, and no advisory is suppressed. The upstream 4.3.0
tarball integrity is:

`sha512-M5t5LlJpS1UHMjvwRQVdFHvPISGeLAxNcrWuJkeGh0KxsqCHZ1O3NXZU/8x7cD0BDcGW8kapxMKTvwlqrNkHkA==`

After a frozen workspace install, run the offline regression contract:

```sh
node --test scripts/__tests__/http-cache-semantics.test.mjs
```

The Node audit workflow runs this against every installed pnpm copy. Keep the
patch until an upstream version passes the same behavioural contract and the
consumer suites; an empty audit report alone is insufficient evidence to
remove it. Do not enable unused-patch or patch-failure allowances.
