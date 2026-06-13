import { NextResponse, type NextRequest } from 'next/server';

function createNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

/**
 * Build the enforced CSP for a single request. The nonce lives in both the
 * request CSP and x-nonce header so Next can apply it to framework scripts.
 */
export function buildCsp(
  nonce: string,
  glitchtipUrl: string | null,
  nodeEnv = process.env.NODE_ENV,
): string {
  const connectSrc = [
    "'self'",
    'https://vitals.vercel-analytics.com',
    'https://vercel.live',
    'wss://vercel.live',
    glitchtipUrl ?? '',
  ]
    .filter(Boolean)
    .join(' ');
  const scriptSrc = [
    "'self'",
    `'nonce-${nonce}'`,
    nodeEnv === 'development' ? "'unsafe-eval'" : '',
    'https://vercel.live',
  ]
    .filter(Boolean)
    .join(' ');

  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    // Inline styles must be allowed: fumadocs' DocsLayout computes the whole
    // #nd-docs-layout grid (grid-template + --fd-sidebar-col/--fd-docs-row-*)
    // as a runtime inline style attribute, and radix floating-ui sets runtime
    // positions the same way. CSP style hashes don't cover style *attributes*,
    // and style-src-attr isn't cross-browser — so a public docs site needs
    // 'unsafe-inline' here. script-src stays strict (nonce-based).
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    'report-uri /api/csp-report',
    'report-to csp-endpoint',
  ].join('; ');
}

export function proxy(req: NextRequest) {
  const nonce = createNonce();
  const glitchtipUrl = process.env.FLINTTRADE_GLITCHTIP_URL ?? null;
  const csp = buildCsp(nonce, glitchtipUrl);

  const requestHeaders = new Headers(req.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', csp);

  const res = NextResponse.next({ request: { headers: requestHeaders } });
  res.headers.set('Content-Security-Policy', csp);
  res.headers.set('x-nonce', nonce);
  return res;
}

export const config = {
  matcher: [
    {
      // demo-app is the static Explore-mode terminal bundle; it gets its own
      // scoped CSP from next.config.mjs headers() instead of the site CSP.
      source: '/((?!api/|_next/static|_next/image|favicon.ico|demo-app(?:/|$)).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};
