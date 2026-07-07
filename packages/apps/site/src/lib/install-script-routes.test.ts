import { describe, expect, it } from 'vitest';

import { INSTALL_SCRIPTS, installScriptRedirect } from './install-script-routes';

describe('install script routes', () => {
  it('redirects /install.sh to the raw GitHub script on main', () => {
    const res = installScriptRedirect('sh');
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe(INSTALL_SCRIPTS.sh);
    expect(INSTALL_SCRIPTS.sh).toMatch(
      /^https:\/\/raw\.githubusercontent\.com\/.+\/main\/scripts\/install\/flinttrade-install\.sh$/,
    );
  });

  it('redirects /install.ps1 to the raw GitHub script on main', () => {
    const res = installScriptRedirect('ps1');
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe(INSTALL_SCRIPTS.ps1);
    expect(INSTALL_SCRIPTS.ps1).toMatch(/flinttrade-install\.ps1$/);
  });
});
