import path from "node:path";

export const FLINTTRADE_SCHEME = "flinttrade";
export const SPLASH_URL = `${FLINTTRADE_SCHEME}://splash/index.html`;

const SPLASH_ASSETS = new Map([
  ["/index.html", "index.html"],
  ["/splash.css", "splash.css"],
  ["/splash.js", "splash.js"],
]);

/**
 * Restrictive Content-Security-Policy for the local splash document. The splash
 * loads only its own same-origin assets (index.html, splash.css, splash.js) over
 * the flinttrade:// scheme and takes no remote content or user input, so 'self'
 * (plus data: images for inline icons) is sufficient and everything else is
 * denied. This is an Electron-layer backstop: the renderer is already confined to
 * the splash origin and the terminal is served its own policy by the backend.
 */
export const SPLASH_CONTENT_SECURITY_POLICY = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join("; ");

/**
 * Security headers attached to every splash response served over the scheme.
 * Only the CSP is added: it governs script/style/frame sources by origin, not by
 * MIME, so it cannot be defeated by content sniffing and does not make the file
 * loader's content-type load-bearing for the three static same-origin assets.
 */
export function splashSecurityHeaders(base?: Headers): Headers {
  const headers = new Headers(base);
  headers.set("Content-Security-Policy", SPLASH_CONTENT_SECURITY_POLICY);
  return headers;
}

export function resolveSplashRequest(requestUrl: string, splashDirectory: string): string | null {
  let url: URL;
  try {
    url = new URL(requestUrl);
  } catch {
    return null;
  }

  if (
    url.protocol !== `${FLINTTRADE_SCHEME}:` ||
    url.hostname !== "splash" ||
    url.username !== "" ||
    url.password !== "" ||
    url.port !== "" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    return null;
  }

  const asset = SPLASH_ASSETS.get(url.pathname);
  return asset ? path.join(splashDirectory, asset) : null;
}
