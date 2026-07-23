import { describe, expect, it } from 'vitest';

import {
  installScriptRedirect,
  installScriptUrl,
  siteSourceSha,
} from './install-script-routes';

const SOURCE_SHA = '0123456789abcdef0123456789abcdef01234567';

describe('install script routes', () => {
  it('redirects /install.sh to the raw GitHub script at the exact deployment commit', () => {
    const res = installScriptRedirect('sh', SOURCE_SHA);
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe(
      `https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/${SOURCE_SHA}/scripts/install/flinttrade-install.sh`,
    );
    expect(res.headers.get('location')).not.toContain('/main/');
  });

  it('redirects /install.ps1 to the same immutable deployment commit', () => {
    const res = installScriptRedirect('ps1', SOURCE_SHA);
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe(installScriptUrl('ps1', SOURCE_SHA));
    expect(res.headers.get('location')).toMatch(/flinttrade-install\.ps1$/);
  });

  it('redirects /uninstall.sh to the same immutable deployment commit', () => {
    const res = installScriptRedirect('uninstall-sh', SOURCE_SHA);
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe(installScriptUrl('uninstall-sh', SOURCE_SHA));
  });

  it('redirects /uninstall.ps1 to the same immutable deployment commit', () => {
    const res = installScriptRedirect('uninstall-ps1', SOURCE_SHA);
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe(installScriptUrl('uninstall-ps1', SOURCE_SHA));
    expect(res.headers.get('location')).toMatch(/flinttrade-uninstall\.ps1$/);
  });

  it('uses an explicit self-hosted SHA before the Vercel deployment SHA', () => {
    expect(siteSourceSha({
      FLINTTRADE_SITE_SOURCE_SHA: SOURCE_SHA.toUpperCase(),
      VERCEL_GIT_COMMIT_SHA: 'f'.repeat(40),
    })).toBe(SOURCE_SHA);
  });

  it('fails closed when no exact immutable source SHA is available', async () => {
    const missing = installScriptRedirect('sh', null);
    const malformed = installScriptUrl('sh', 'main');

    expect(missing.status).toBe(503);
    expect(missing.headers.get('cache-control')).toBe('no-store');
    await expect(missing.text()).resolves.toContain('immutable FlintTrade install-script source is unavailable');
    expect(malformed).toBeNull();
  });
});
