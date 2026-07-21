import path from "node:path";

export const FLINTTRADE_SCHEME = "flinttrade";
export const SPLASH_URL = `${FLINTTRADE_SCHEME}://splash/index.html`;

const SPLASH_ASSETS = new Map([
  ["/index.html", "index.html"],
  ["/splash.css", "splash.css"],
  ["/splash.js", "splash.js"],
]);

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
