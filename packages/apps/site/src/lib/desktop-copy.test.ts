import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DownloadPage from '../app/download/page';
import { DEFAULT_DESKTOP_RELEASE } from './desktop-release';
import { FIXTURE_GITHUB_RELEASE } from './desktop-release.fixtures';

function siteSource(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf8');
}

describe('Electron source-bootstrap website copy', () => {
  const home = siteSource('src/app/page.tsx');
  const download = siteSource('src/app/download/page.tsx');
  const installRoutes = siteSource('src/lib/install-script-routes.ts');

  it('describes a small Electron shell and the verified first-run local source build', () => {
    expect(download).toContain('small Electron shell');
    expect(download).toContain('first launch');
    expect(download).toContain('hash-verified');
    expect(download).toContain('integrity-locked local source');
  });

  it('does not sell a downloadable desktop app on the homepage while Electron is pending', () => {
    expect(home).not.toContain('Download desktop app');
    expect(home).not.toContain('One native app for macOS, Windows, and Linux');
    expect(home).not.toContain('Electron shell delivery');
    expect(home).not.toContain('The install script downloads and verifies');
    expect(home).not.toContain('Check installer status');
    expect(home).toContain('Install the web app');
    expect(home).toContain('web-install.sh');
    expect(home).toContain('Electron installer pending');
    expect(home).toContain('href="/docs/desktop"');
  });

  it('removes retired bundled-runtime and pre-install source-build claims', () => {
    const publicCopy = `${home}\n${download}`;
    expect(publicCopy).not.toMatch(/backend sidecar|Tauri|PyInstaller|payload/i);
    expect(publicCopy).not.toContain('--build-from-source');
    expect(publicCopy).not.toContain('builds the native app on your own machine');
    expect(download).not.toContain('current beta release');
    expect(download).not.toContain('Honest beta');
  });

  it('does not imply that browser download links verify their own checksums', () => {
    expect(download).toContain('One-command installs verify SHA-256 automatically');
    expect(download).toContain('Direct downloads must be checked');
    expect(download).toMatch(/browser download button does\s+not perform that check for you/);
    expect(download).toContain('SHA256SUMS.txt');
    expect(download).not.toContain('SHA-256 verification protects the download');
  });

  it('distinguishes manual Finder removal from receipt-proved uninstall', () => {
    expect(download).toContain('copied from a DMG in Finder has no FlintTrade install receipt');
    expect(download).toContain('move <span className="font-mono">FlintTrade.app</span>');
    expect(download).toContain('ordinary uninstall script');
    expect(download).toContain('only receipt-proved shells');
    expect(installRoutes).toContain('remove only receipt-proved shells and integration files');
  });

  it('keeps installer redirects described as shell delivery rather than manifest delivery', () => {
    expect(installRoutes).toContain('small Electron shell');
    expect(installRoutes).toContain('first run');
    expect(installRoutes).not.toContain('desktop-release manifest');
    expect(installRoutes).toContain('VERCEL_GIT_COMMIT_SHA');
    expect(installRoutes).toContain('FLINTTRADE_SITE_SOURCE_SHA');
    expect(installRoutes).not.toContain('/main/scripts/install');
    expect(download).toContain('siteSourceSha');
    expect(download).not.toContain('FlintTrade/blob/main/scripts/install');
  });
});

/**
 * These assertions guard the DESKTOP installer copy only: the page must not
 * advertise a desktop install before a complete, verified Electron release
 * exists. They were originally written as a blanket `not.toContain('curl -fsSL')`
 * because the desktop installer was the only command the page had ever shown.
 * The page now also carries the self-hosted web-app one-liners, which are
 * legitimate in every state (they depend on no release at all), so the checks
 * are narrowed to the exact desktop commands rather than to the shape of a
 * shell one-liner. Anything matching these must stay release-gated.
 */
const DESKTOP_INSTALL_COMMANDS = [
  'curl -fsSL https://flinttrade.vercel.app/install.sh | bash',
  'irm https://flinttrade.vercel.app/install.ps1 | iex',
] as const;

const WEB_INSTALL_COMMANDS = [
  'curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash',
  'irm https://flinttrade.vercel.app/web-install.ps1 | iex',
] as const;

describe('Electron installer availability copy', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    Reflect.deleteProperty(globalThis, 'React');
  });

  it('renders a fail-closed pending state without commands or a stale Electron release claim', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json([])));
    (globalThis as typeof globalThis & { React?: typeof React }).React = React;

    const html = renderToStaticMarkup(await DownloadPage());

    expect(html).toContain('Electron installer release pending');
    expect(html).toContain('does not expose download buttons or one-command install instructions');
    for (const command of DESKTOP_INSTALL_COMMANDS) {
      expect(html).not.toContain(command);
    }
    expect(html).not.toContain('One-command install');
    expect(html).not.toContain(DEFAULT_DESKTOP_RELEASE.tag);
  });

  it('offers the self-hosted web app and its uninstall in the pending state', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json([])));
    (globalThis as typeof globalThis & { React?: typeof React }).React = React;

    const html = renderToStaticMarkup(await DownloadPage());

    // The desktop shell being unavailable must never leave the page with
    // nothing installable — the web app is the primary path.
    expect(html).toContain('Install the self-hosted web app');
    for (const command of WEB_INSTALL_COMMANDS) {
      expect(html).toContain(command);
    }
    expect(html).toContain('Uninstall');
    expect(html).toContain('curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash');
    expect(html).toContain('irm https://flinttrade.vercel.app/uninstall.ps1 | iex');
  });

  it('separates an unreachable release feed from a genuinely unpublished installer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('release feed unreachable');
    }));
    (globalThis as typeof globalThis & { React?: typeof React }).React = React;

    const html = renderToStaticMarkup(await DownloadPage());

    expect(html).toContain('temporarily unavailable');
    expect(html).toContain('could not be reached from this deployment');
    // A failed lookup proves nothing about publication, so it must not claim
    // the release is pending, nor advertise a desktop install.
    expect(html).not.toContain('Electron installer release pending');
    for (const command of DESKTOP_INSTALL_COMMANDS) {
      expect(html).not.toContain(command);
    }
    for (const command of WEB_INSTALL_COMMANDS) {
      expect(html).toContain(command);
    }
  });

  it('shows commands and exact release copy only for a complete verified Electron asset set', async () => {
    vi.stubEnv('FLINTTRADE_SITE_SOURCE_SHA', '0123456789abcdef0123456789abcdef01234567');
    vi.stubGlobal('fetch', vi.fn(async () => Response.json([FIXTURE_GITHUB_RELEASE])));
    (globalThis as typeof globalThis & { React?: typeof React }).React = React;

    const html = renderToStaticMarkup(await DownloadPage());

    expect(html).not.toContain('Electron installer release pending');
    expect(html).toContain('One-command install');
    expect(html).toContain('curl -fsSL https://flinttrade.vercel.app/install.sh | bash');
    expect(html).toContain(FIXTURE_GITHUB_RELEASE.tag_name);
    expect(html).toContain('SHA256SUMS.txt');
    expect(html).toContain('does not perform that check for you');
  });

  it('withholds one-command execution when the deployment has no immutable source identity', async () => {
    vi.stubEnv('FLINTTRADE_SITE_SOURCE_SHA', '');
    vi.stubEnv('VERCEL_GIT_COMMIT_SHA', '');
    vi.stubGlobal('fetch', vi.fn(async () => Response.json([FIXTURE_GITHUB_RELEASE])));
    (globalThis as typeof globalThis & { React?: typeof React }).React = React;

    const html = renderToStaticMarkup(await DownloadPage());

    expect(html).toContain('One-command install is unavailable');
    // Narrowed for the same reason as the pending-state check above: the
    // desktop commands stay withheld, while the web-app commands remain on the
    // page with an explicit note that the bootstrap URLs answer 503 until this
    // deployment has an immutable source identity.
    for (const command of DESKTOP_INSTALL_COMMANDS) {
      expect(html).not.toContain(command);
    }
    expect(html).not.toContain('Read the install script');
    expect(html).toContain('Download');
    expect(html).toContain('no immutable source identity, so those bootstrap URLs answer');
  });
});
