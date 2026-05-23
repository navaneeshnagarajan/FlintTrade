#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHA="$(git -C "$ROOT" rev-parse --short HEAD)"
OUT="${1:-$ROOT/flinttrade-design/baselines/visual-regression/$SHA}"
TERM_PORT="${FLINTTRADE_TERMINAL_PORT:-5173}"
SITE_PORT="${FLINTTRADE_SITE_PORT:-3000}"
export OUT TERM_PORT SITE_PORT
mkdir -p "$OUT"

cleanup() {
  if [[ -n "${TERM_PID:-}" ]]; then kill "$TERM_PID" 2>/dev/null || true; fi
  if [[ -n "${SITE_PID:-}" ]]; then kill "$SITE_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT

(
  cd "$ROOT/packages/terminal"
  npm run dev -- --host 127.0.0.1 --port "$TERM_PORT"
) >/tmp/flinttrade-terminal-visual-baseline.log 2>&1 &
TERM_PID=$!

(
  cd "$ROOT/apps/site"
  npm run dev -- --hostname 127.0.0.1 --port "$SITE_PORT"
) >/tmp/flinttrade-site-visual-baseline.log 2>&1 &
SITE_PID=$!

node <<'NODE'
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("./packages/terminal/node_modules/playwright");

const root = process.cwd();
const out = process.env.OUT;
const termPort = process.env.TERM_PORT;
const sitePort = process.env.SITE_PORT;
const terminalRoutes = [
  "/", "/welcome", "/explore", "/setup", "/setup-account", "/home",
  "/trade", "/terminal", "/invest", "/learn", "/lab", "/automate",
  "/ai", "/ditto", "/settings", "/admin", "/login", "/missing-route-for-404"
];
const siteRoutes = ["/", "/docs", "/api-reference", "/mcp", "/contribute", "/api/mcp", "/api/search", "/missing-route-for-404"];
const viewports = [
  { name: "1920x1080", width: 1920, height: 1080 },
  { name: "1366x768", width: 1366, height: 768 },
  { name: "768x1024", width: 768, height: 1024 },
];
const themes = ["dark", "light"];
const densities = ["compact", "comfortable"];

async function waitFor(url) {
  const started = Date.now();
  while (Date.now() - started < 90000) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error(`timed out waiting for ${url}`);
}

function slug(route) {
  if (route === "/") return "root";
  return route.replace(/^\//, "").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "") || "root";
}

async function capture(browser, app, baseUrl, route) {
  for (const viewport of viewports) {
    for (const theme of themes) {
      for (const density of densities) {
        const page = await browser.newPage({ viewport });
        await page.addInitScript(({ theme, density }) => {
          localStorage.setItem("flinttrade.theme", theme);
          localStorage.setItem("flinttrade.density", density);
          document.documentElement.dataset.theme = theme;
          document.documentElement.dataset.density = density;
        }, { theme, density });
        await page.goto(`${baseUrl}${route}`, { waitUntil: "networkidle", timeout: 30000 });
        const dir = path.join(out, app, slug(route), viewport.name, theme);
        fs.mkdirSync(dir, { recursive: true });
        await page.screenshot({ path: path.join(dir, `${density}.png`), fullPage: false });
        await page.close();
      }
    }
  }
}

(async () => {
  await waitFor(`http://127.0.0.1:${termPort}`);
  await waitFor(`http://127.0.0.1:${sitePort}`);
  const browser = await chromium.launch();
  try {
    for (const route of terminalRoutes) {
      await capture(browser, "terminal", `http://127.0.0.1:${termPort}`, route);
    }
    for (const route of siteRoutes) {
      await capture(browser, "site", `http://127.0.0.1:${sitePort}`, route);
    }
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
NODE
