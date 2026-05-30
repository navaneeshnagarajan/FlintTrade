import { INLINE_STYLE_HASHES } from '@/lib/csp-style-hashes.generated';
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
function buildCsp(nonce: string, glitchtipUrl: string | null): string {
  const styleHashes = INLINE_STYLE_HASHES.join(' ');
  const connectSrc = [
    "'self'",
    'https://vitals.vercel-analytics.com',
    'https://vercel.live',
    'wss://vercel.live',
    glitchtipUrl ?? '',
  ]
    .filter(Boolean)
    .join(' ');

  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' https://vercel.live`,
    `style-src 'self' ${styleHashes}`,
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
      source: '/((?!api/|_next/static|_next/image|favicon.ico).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};
