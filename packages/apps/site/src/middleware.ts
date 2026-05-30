import { NextResponse, type NextRequest } from "next/server";
import { randomBytes } from "node:crypto";

import { INLINE_STYLE_HASHES } from "@/lib/csp-style-hashes.generated";

/**
 * Build the enforced CSP for a single request. Threads the nonce into `script-src` so
 * Next 16's inline bootstrap scripts execute, while forbidding any other inline script
 * (XSS containment, C2). `'unsafe-inline'` appears nowhere in `script-src` — ever.
 */
function buildCsp(nonce: string, glitchtipUrl: string | null): string {
  const styleHashes = INLINE_STYLE_HASHES.join(" ");
  const connectSrc = [
    "'self'",
    "https://vitals.vercel-analytics.com",
    "https://vercel.live",
    "wss://vercel.live", // L6: scoped to vercel.live only — no unconstrained wss:
    glitchtipUrl ?? "", // X9: operator's GlitchTip endpoint (may be empty)
  ]
    .filter(Boolean)
    .join(" ");

  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' https://vercel.live`, // C2: no inline allowance ever
    `style-src 'self' ${styleHashes}`, // hashes only; no inline allowance
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    "report-uri /api/csp-report",
    "report-to csp-endpoint",
  ].join("; ");
}

export function middleware(req: NextRequest) {
  // 16 random bytes → 24-char base64 nonce; cryptographic randomness is mandatory.
  const nonce = randomBytes(16).toString("base64");

  // X9: read the GlitchTip URL at runtime; null when the operator hasn't configured
  // observability (single-developer install) — no policy weakening, no broken fetches.
  const glitchtipUrl = process.env.FLINTTRADE_GLITCHTIP_URL ?? null;

  // Build the request Headers object first, mutate, THEN pass it — Headers.set() returns
  // void, so a chained `new Headers(...).set(...) ?? req.headers` would always fall back
  // to req.headers and the nonce would never reach layout's headers() read (R2/NH5).
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set("x-csp-nonce", nonce);

  const res = NextResponse.next({ request: { headers: requestHeaders } });
  res.headers.set("Content-Security-Policy", buildCsp(nonce, glitchtipUrl));
  res.headers.set("x-csp-nonce", nonce);
  return res;
}

export const config = {
  matcher: "/((?!api/|_next/static|_next/image|favicon).*)",
};
