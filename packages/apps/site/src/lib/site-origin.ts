/**
 * Public site origin for copy-paste snippets (MCP URL, and similar).
 *
 * Request Host / X-Forwarded-Host are only used when they are an explicit
 * allow-listed host. Anything else falls back to VERCEL_URL, then the
 * canonical production origin.
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

interface ParsedHost {
  hostname: string;
  authority: string;
}

function firstHop(value?: string | null): string {
  if (!value) {
    return '';
  }
  return value.split(',')[0]?.trim() ?? '';
}

function parseRequestHost(raw: string): ParsedHost | null {
  if (!raw || /[\s/?#\\@]/.test(raw) || raw.includes('://')) {
    return null;
  }

  let url: URL;
  try {
    url = new URL(`http://${raw}`);
  } catch {
    return null;
  }

  if (url.username || url.password) {
    return null;
  }
  if (url.pathname !== '/' || url.search !== '' || url.hash !== '') {
    return null;
  }
  if (!url.hostname) {
    return null;
  }
  if (raw.toLowerCase() !== url.host.toLowerCase()) {
    return null;
  }

  return { hostname: url.hostname, authority: url.host };
}

function canonicalHostname(): string {
  return new URL(CANONICAL_SITE_ORIGIN).hostname.toLowerCase();
}

function vercelEnvHost(env?: SiteOriginEnvHints): ParsedHost | null {
  const raw = env?.VERCEL_URL?.trim();
  if (!raw) {
    return null;
  }
  return parseRequestHost(firstHop(raw.replace(/^https?:\/\//i, '')));
}

function isLoopback(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[(.*)\]$/, '$1');
  return host === 'localhost' || host === '127.0.0.1' || host === '::1';
}

function isVercelAppAlias(hostname: string): boolean {
  const host = hostname.toLowerCase();
  if (!host.endsWith('.vercel.app')) {
    return false;
  }
  const labels = host.split('.');
  if (labels.length < 3) {
    return false;
  }
  return labels.every(
    (label) =>
      label.length > 0 &&
      /^[a-z0-9-]+$/.test(label) &&
      !label.startsWith('-') &&
      !label.endsWith('-'),
  );
}

function isAllowedHost(hostname: string, env?: SiteOriginEnvHints): boolean {
  const host = hostname.toLowerCase();
  if (isLoopback(host)) {
    return true;
  }
  if (host === canonicalHostname()) {
    return true;
  }
  const vercelHost = vercelEnvHost(env)?.hostname.toLowerCase();
  if (vercelHost && host === vercelHost) {
    return true;
  }
  return isVercelAppAlias(host);
}

function originFromParsed(parsed: ParsedHost, protoHint?: string | null): string {
  if (isLoopback(parsed.hostname)) {
    const protoHop = firstHop(protoHint);
    const proto = protoHop === 'https' ? 'https' : 'http';
    return `${proto}://${parsed.authority}`;
  }
  return `https://${parsed.authority}`;
}

export function siteOriginFrom(
  request?: SiteOriginRequestHints,
  env?: SiteOriginEnvHints,
): string {
  for (const raw of [request?.forwardedHost, request?.host]) {
    const hop = firstHop(raw);
    if (!hop) {
      continue;
    }
    const parsed = parseRequestHost(hop);
    if (!parsed || !isAllowedHost(parsed.hostname, env)) {
      continue;
    }
    return originFromParsed(parsed, request?.forwardedProto);
  }

  const vercelHost = vercelEnvHost(env);
  if (vercelHost) {
    return originFromParsed(vercelHost, 'https');
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
