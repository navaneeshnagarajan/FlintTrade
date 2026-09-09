import { describe, expect, it } from 'vitest';

import { CANONICAL_SITE_ORIGIN } from './site-origin';
import {
  desktopInstallCommands,
  uninstallCommands,
  webInstallCommands,
} from './web-install-commands';

describe('origin-aware public install commands', () => {
  it('defaults to the canonical public origin so flint.toml rewrites stay honest', () => {
    const [posix, windows] = webInstallCommands();
    expect(posix.command).toBe(`curl -fsSL ${CANONICAL_SITE_ORIGIN}/web-install.sh | bash`);
    expect(windows.command).toBe(`irm ${CANONICAL_SITE_ORIGIN}/web-install.ps1 | iex`);
  });

  it('rewrites web, uninstall, and desktop commands for a configured origin', () => {
    const origin = 'https://hosted.example';
    const [posix] = webInstallCommands(origin);
    const [uninstallPosix] = uninstallCommands(origin);
    const [desktopPosix] = desktopInstallCommands(origin);

    expect(posix.command).toBe(`curl -fsSL ${origin}/web-install.sh | bash`);
    expect(uninstallPosix.command).toBe(`curl -fsSL ${origin}/uninstall.sh | bash`);
    expect(desktopPosix.command).toBe(`curl -fsSL ${origin}/install.sh | bash`);
    expect(posix.command).not.toContain(CANONICAL_SITE_ORIGIN);
  });
});
