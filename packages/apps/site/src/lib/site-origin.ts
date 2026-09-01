/**
 * Public site origin for copy-paste snippets (MCP URL, and similar).
 *
 * Prefer the current request host so preview deployments stay copy-pasteable.
 * Fall back to VERCEL_URL, then the canonical production origin.
 */

export const CANONICAL_SITE_ORIGIN = 'https://flinttrade.vercel.app';

export interface SiteOriginRequestHints {
  host?: string | null;
  forwardedHost?: string | null;
  forwardedProto?: string | null;
}

export interface SiteOriginEnvHints {
  VERCEL_URL?: string;
}

function originFromHost(host: string, protoHint?: string | null): string {
  const proto =
    protoHint === 'http' || protoHint === 'https'
      ? protoHint
      : host.startsWith('localhost') || host.startsWith('127.')
        ? 'http'
        : 'https';
  return `${proto}://${host}`;
}

export function siteOriginFrom(
  request?: SiteOriginRequestHints,
  env?: SiteOriginEnvHints,
): string {
  const host = request?.forwardedHost?.trim() || request?.host?.trim();
  if (host) {
    return originFromHost(host, request?.forwardedProto);
  }
  const vercelHost = env?.VERCEL_URL?.replace(/^https?:\/\//, '').trim();
  if (vercelHost) {
    return originFromHost(vercelHost, 'https');
  }
  return CANONICAL_SITE_ORIGIN;
}

export function hostedMcpUrl(origin: string): string {
  return `${origin.replace(/\/$/, '')}/api/mcp`;
}

export async function resolveSiteOrigin(): Promise<string> {
  try {
    const { headers } = await import('next/headers');
    const requestHeaders = await headers();
    return siteOriginFrom(
      {
        host: requestHeaders.get('host'),
        forwardedHost: requestHeaders.get('x-forwarded-host'),
        forwardedProto: requestHeaders.get('x-forwarded-proto'),
      },
      { VERCEL_URL: process.env.VERCEL_URL },
    );
  } catch {
    return siteOriginFrom(undefined, { VERCEL_URL: process.env.VERCEL_URL });
  }
}
