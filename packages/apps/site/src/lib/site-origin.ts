/**
 * Public site origin for copy-paste snippets (MCP URL, install commands).
 *
 * Precedence:
 *   1. Request Host / X-Forwarded-Host, only when the host is allow-listed
 *   2. FLINTTRADE_SITE_URL, then NEXT_PUBLIC_SITE_URL (primary public origin)
 *   3. VERCEL_URL
 *   4. The canonical production origin (https://flinttrade.vercel.app)
 *
 * Request hosts are trusted when they are loopback, the canonical host, the
 * exact VERCEL_URL host, or a host from FLINTTRADE_SITE_URL /
 * NEXT_PUBLIC_SITE_URL / FLINTTRADE_SITE_ORIGINS. The last of those is an
 * extra allow-list only — it never becomes the fallback origin.
 */

export const CANONICAL_SITE_ORIGIN = 'https://flinttrade.vercel.app';

export const SITE_URL_ENV_KEYS = ['FLINTTRADE_SITE_URL', 'NEXT_PUBLIC_SITE_URL'] as const;

export interface SiteOriginRequestHints {
  host?: string | null;
  forwardedHost?: string | null;
  forwardedProto?: string | null;
}

export interface SiteOriginEnvHints {
  VERCEL_URL?: string;
  FLINTTRADE_SITE_URL?: string;
  NEXT_PUBLIC_SITE_URL?: string;
  FLINTTRADE_SITE_ORIGINS?: string;
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
  return parseRequestHost(raw.replace(/^https?:\/\//i, ''));
}

function isLoopback(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[(.*)\]$/, '$1');
  return host === 'localhost' || host === '127.0.0.1' || host === '::1';
}

/**
 * Parse an operator-configured public origin.
 *
 * Accepts a bare `https://host` (optional trailing slash). HTTP is allowed only
 * for loopback. Paths, query strings, credentials, and hashes are rejected so a
 * mistyped env var cannot leak into copy-paste install or MCP URLs.
 */
function parseConfiguredOrigin(raw?: string): string | null {
  const trimmed = raw?.trim();
  if (!trimmed) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return null;
  }
  if (url.username || url.password) {
    return null;
  }
  if (url.search !== '' || url.hash !== '') {
    return null;
  }
  if (url.pathname !== '/' && url.pathname !== '') {
    return null;
  }
  if (!url.hostname) {
    return null;
  }
  const loopback = isLoopback(url.hostname);
  if (loopback) {
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return null;
    }
  } else if (url.protocol !== 'https:') {
    return null;
  }
  return url.origin;
}

export function configuredSiteOriginFromEnv(env?: SiteOriginEnvHints): string | null {
  for (const key of SITE_URL_ENV_KEYS) {
    const parsed = parseConfiguredOrigin(env?.[key]);
    if (parsed) {
      return parsed;
    }
  }
  return null;
}

/**
 * Extra Hostinger / custom-domain hosts that may appear on the request.
 *
 * `FLINTTRADE_SITE_ORIGINS` is a comma-separated list of bare https origins.
 * It extends the request allow-list only; the fallback origin stays
 * `FLINTTRADE_SITE_URL` / `NEXT_PUBLIC_SITE_URL`.
 */
export function configuredAllowlistedOrigins(env?: SiteOriginEnvHints): string[] {
  const origins: string[] = [];
  const seen = new Set<string>();
  const add = (origin: string | null): void => {
    if (!origin) {
      return;
    }
    const key = origin.toLowerCase();
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    origins.push(origin);
  };
  for (const key of SITE_URL_ENV_KEYS) {
    add(parseConfiguredOrigin(env?.[key]));
  }
  for (const part of (env?.FLINTTRADE_SITE_ORIGINS ?? '').split(',')) {
    add(parseConfiguredOrigin(part));
  }
  return origins;
}

function isAllowedHost(hostname: string, env?: SiteOriginEnvHints): boolean {
  const host = hostname.toLowerCase();
  if (isLoopback(host)) {
    return true;
  }
  if (host === canonicalHostname()) {
    return true;
  }
  for (const origin of configuredAllowlistedOrigins(env)) {
    if (new URL(origin).hostname.toLowerCase() === host) {
      return true;
    }
  }
  const vercelHost = vercelEnvHost(env)?.hostname.toLowerCase();
  if (vercelHost && host === vercelHost) {
    return true;
  }
  return false;
}

function originFromParsed(parsed: ParsedHost, protoHint?: string | null): string {
  if (isLoopback(parsed.hostname)) {
    const protoHop = firstHop(protoHint);
    const proto = protoHop === 'https' ? 'https' : 'http';
    return `${proto}://${parsed.authority}`;
  }
  return `https://${parsed.authority}`;
}

export function processEnvSiteHints(
  environment: NodeJS.ProcessEnv = process.env,
): SiteOriginEnvHints {
  return {
    VERCEL_URL: environment.VERCEL_URL,
    FLINTTRADE_SITE_URL: environment.FLINTTRADE_SITE_URL,
    NEXT_PUBLIC_SITE_URL: environment.NEXT_PUBLIC_SITE_URL,
    FLINTTRADE_SITE_ORIGINS: environment.FLINTTRADE_SITE_ORIGINS,
  };
}

/**
 * Build-time / metadata origin: env override, then the canonical fallback.
 *
 * There is no request at `metadataBase` evaluation, so this never consults Host.
 */
export function siteMetadataOrigin(env?: SiteOriginEnvHints): string {
  return configuredSiteOriginFromEnv(env ?? processEnvSiteHints()) ?? CANONICAL_SITE_ORIGIN;
}

export function siteOriginFrom(
  request?: SiteOriginRequestHints,
  env?: SiteOriginEnvHints,
): string {
  const directHop = firstHop(request?.host);
  const directHost = directHop ? parseRequestHost(directHop) : null;
  const forwardedHop = firstHop(request?.forwardedHost);
  const forwardedHost = forwardedHop ? parseRequestHost(forwardedHop) : null;

  if (
    forwardedHost &&
    isAllowedHost(forwardedHost.hostname, env) &&
    (!isLoopback(forwardedHost.hostname) || (directHost !== null && isLoopback(directHost.hostname)))
  ) {
    return originFromParsed(forwardedHost, request?.forwardedProto);
  }
  if (directHost && isAllowedHost(directHost.hostname, env)) {
    return originFromParsed(directHost, request?.forwardedProto);
  }

  const configured = configuredSiteOriginFromEnv(env);
  if (configured) {
    return configured;
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
  const env = processEnvSiteHints();
  try {
    const { headers } = await import('next/headers');
    const requestHeaders = await headers();
    return siteOriginFrom(
      {
        host: requestHeaders.get('host'),
        forwardedHost: requestHeaders.get('x-forwarded-host'),
        forwardedProto: requestHeaders.get('x-forwarded-proto'),
      },
      env,
    );
  } catch {
    return siteOriginFrom(undefined, env);
  }
}
