import {
  DESKTOP_RELEASE_REVALIDATE_SECONDS,
  GITHUB_RELEASES_URL,
  type DesktopReleaseChannel,
  type GitHubRelease,
  selectDesktopRelease,
} from '@/lib/desktop-release';

export const revalidate = 300;

export async function OPTIONS(): Promise<Response> {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const tag = url.searchParams.get('tag') ?? undefined;
  const channel = channelParam(url.searchParams.get('channel'));

  try {
    const response = await fetch(GITHUB_RELEASES_URL, {
      headers: {
        Accept: 'application/vnd.github+json',
        'User-Agent': 'flinttrade-site/desktop-release',
      },
      next: { revalidate: DESKTOP_RELEASE_REVALIDATE_SECONDS },
    });
    if (!response.ok) {
      return errorResponse(`GitHub responded with HTTP ${response.status}`, 503);
    }
    const releases = (await response.json()) as GitHubRelease[];
    const manifest = selectDesktopRelease(releases, { channel, tag });
    if (!manifest) return errorResponse('No desktop installer release found.', 404);
    return Response.json(manifest, { headers: cacheHeaders() });
  } catch {
    return errorResponse('Could not reach GitHub releases.', 503);
  }
}

function channelParam(value: string | null): DesktopReleaseChannel {
  return value === 'stable' ? 'stable' : 'beta';
}

function errorResponse(message: string, status: number): Response {
  return Response.json({ error: message }, { status, headers: cacheHeaders() });
}

function cacheHeaders(): HeadersInit {
  return {
    'Cache-Control': `public, s-maxage=${DESKTOP_RELEASE_REVALIDATE_SECONDS}, stale-while-revalidate=86400`,
    ...corsHeaders(),
  };
}

function corsHeaders(): HeadersInit {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Accept, Content-Type',
  };
}
