/**
 * Signature and availability source contracts. Mounted public journeys live
 * in app/page.test.ts. Product sections are static; the protected hero and
 * default-off Spark Path keep their existing implementation and fallback.
 */

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

function readSite(relativePath: string): string {
  const fullPath = resolve(process.cwd(), relativePath);
  return existsSync(fullPath) ? readFileSync(fullPath, 'utf8') : '';
}

const pageSource = readSite('src/app/page.tsx');
const productSource = readSite('src/components/product-overview.tsx');
const cssSource = readSite('src/app/globals.css');
const nextConfigSource = readSite('next.config.mjs');
const controllerSource = readSite('src/components/section-enter-controller.tsx');
const wrapperSource = readSite('src/components/site-scroll-world.tsx');
const webglSource = readSite('src/components/site-scroll-world-webgl.tsx');
const capabilitySource = readSite('src/lib/site-scroll-world-capability.ts');
const chapterSource = readSite('src/lib/site-scroll-world-chapters.ts');
const sitePackage = JSON.parse(readSite('package.json') || '{}') as {
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
};

describe('product-led homepage with the preserved signature', () => {
  it('keeps product navigation separate from unavailable desktop-install claims', () => {
    expect(pageSource).toContain('section className="section hero"');
    expect(pageSource).toContain('<ProductOverview />');
    expect(pageSource).toContain('MCP for development, not trading.');
    expect(pageSource).not.toContain('Evaluate and install');
    expect(pageSource).not.toContain('Start exploring — no install needed');
    expect(pageSource).not.toContain('Download desktop app');
    expect(pageSource).not.toContain('<your-site>');
    const sectionMatches = `${pageSource}\n${productSource}`.match(/<section className="section/g) || [];
    expect(sectionMatches.length).toBeGreaterThanOrEqual(5);
  });

  it('preserves exactly one global primary CTA: install the self-hosted web app', () => {
    const primaryMatches = pageSource.match(/className="button primary"/g) || [];
    expect(primaryMatches.length).toBe(1);
    expect(pageSource).toContain('Install the web app');
    expect(pageSource).toContain('href="/download"');
    expect(pageSource).toContain('Demo (example data)');
    expect(pageSource).toContain('/demo-app/welcome');
  });

  it('advertises only the shared web-install commands and an explicit pending Electron note', () => {
    expect(pageSource).toContain('WEB_INSTALL_COMMANDS');
    expect(pageSource).toContain('className="install-commands"');
    expect(pageSource).toContain('Electron installer pending');
    expect(pageSource).toContain('href="/docs/desktop"');
    expect(pageSource).toContain('hostedMcpUrl');
    expect(pageSource).toContain('resolveSiteOrigin');
    expect(pageSource).toContain('export default async function HomePage');
    expect(pageSource).not.toContain('The install script downloads and verifies');
    expect(pageSource).not.toContain('One native app for macOS, Windows, and Linux');
    expect(pageSource).not.toContain('desktopInstallOptions');
  });

  it('keeps truthful copy and Practice / example-data vocabulary', () => {
    expect(pageSource).toContain('v0.0.1 is not production ready');
    expect(pageSource).toContain('Use Practice and example data first');
    expect(pageSource).toContain('/demo-app/welcome');
  });

  it('has reduced-motion static path that disables continuous/entrance animation', () => {
    expect(cssSource).toContain('@media (prefers-reduced-motion: reduce)');
    expect(cssSource).toContain('animation: none');
    expect(cssSource).toContain('transition: none');
    expect(cssSource).toMatch(/prefers-reduced-motion[\s\S]*hero-install/);
    expect(cssSource).toMatch(/prefers-reduced-motion[\s\S]*hero-electron-note/);
  });

  it('adds no animation dependency to the static product composition', () => {
    expect(pageSource).not.toContain('framer-motion');
    expect(pageSource).not.toContain("from 'three'");
    expect(pageSource).not.toContain('from "three"');
    expect(pageSource).not.toContain('@react-three');
    expect(productSource).not.toMatch(/framer-motion|motion\/react|useEffect|section-enter/);
  });

  it('preserves Canvas2D HeroCinematic, /demo-app rewrite, CSP, target blank', () => {
    expect(pageSource).toContain('HeroCinematic');
    expect(pageSource).toContain('/demo-app/welcome');
    expect(pageSource).toContain('target="_blank"');
  });

  it('reads turbopack.root from next.config.mjs (portable root, not in page.tsx)', () => {
    expect(nextConfigSource).toContain('turbopack: {');
    expect(nextConfigSource).toContain('root: repoRoot');
  });

  it('puts shared web install commands after the compact hero, never desktop commands', () => {
    const installIdx = pageSource.indexOf('className="install-commands"');
    const actionsIdx = pageSource.indexOf('className="hero-actions"');
    expect(installIdx).toBeGreaterThan(-1);
    expect(actionsIdx).toBeGreaterThan(-1);
    expect(installIdx).toBeGreaterThan(actionsIdx);
    expect(pageSource).not.toContain('desktopInstallCommands');
  });

  it('keeps page.tsx a pure server component with no top-level use client, hooks, or observer logic', () => {
    expect(pageSource).not.toMatch(/^\s*['"]use client['"]\s*;/m);
    expect(pageSource).not.toContain('useSectionEnterObserver');
    expect(pageSource).not.toContain('useEffect');
    expect(pageSource).not.toContain('IntersectionObserver');
    expect(pageSource).not.toContain('matchMedia');
  });

  it('leaves the legacy section controller intact but does not hide the new product sections', () => {
    expect(pageSource).not.toContain('<SectionEnterController');
    expect(productSource).not.toContain('section-enter');
    expect(controllerSource).toContain('SectionEnterController');
    expect(controllerSource).toContain('useEffect');
    expect(controllerSource).toContain('js-motion-enabled');
    expect(controllerSource).toContain('visible');
  });

  it('controller implements correct order and cleanup', () => {
    const markIdx = controllerSource.indexOf('Mark initially visible sections BEFORE adding root activation class');
    const addClassIdx = controllerSource.indexOf("html.classList.add('js-motion-enabled')");
    expect(markIdx).toBeGreaterThan(-1);
    expect(addClassIdx).toBeGreaterThan(-1);
    expect(markIdx).toBeLessThan(addClassIdx);
    expect(controllerSource).toContain('new IntersectionObserver');
    const disconnectIdx = controllerSource.indexOf('observer.disconnect()');
    const cleanupIdx = controllerSource.indexOf("html.classList.remove('js-motion-enabled')");
    expect(disconnectIdx).toBeGreaterThan(-1);
    expect(cleanupIdx).toBeGreaterThan(-1);
    expect(disconnectIdx).toBeLessThan(cleanupIdx);
    expect(controllerSource).toContain('return () => {');
  });

  it('CSS has real fail-open observed reveal contract', () => {
    expect(cssSource).toMatch(/\.section-enter\s*\{[^}]*opacity:\s*1/);
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*opacity:\s*0/);
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*transition:/);
    expect(cssSource).not.toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*animation:/);
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\.visible\s*\{[^}]*opacity:\s*1/);
    expect(controllerSource).toContain('js-motion-enabled');
  });

  it('mobile (max-width: 620px) freezes essential hero content including the honest install block', () => {
    const mediaIdx = cssSource.indexOf('@media (max-width: 620px)');
    expect(mediaIdx).toBeGreaterThan(-1);
    const mobileCss = cssSource.slice(mediaIdx);
    expect(mobileCss).toContain('.hero-title-char');
    expect(mobileCss).toContain('.hero-actions');
    expect(mobileCss).toContain('.hero-install');
    expect(mobileCss).toContain('.hero-electron-note');
    expect(mobileCss).toMatch(/opacity:\s*1\s*!important/);
    expect(mobileCss).toMatch(/animation:\s*none\s*!important/);
    expect(mobileCss).toMatch(/transition:\s*none\s*!important/);
  });
});

describe('homepage Spark Path scroll-world (default-off decorative enhancement)', () => {
  it('switches every animated semantic hero child to a stable paint layer only after the first WebGL frame', () => {
    const activeHeroRule = cssSource.match(
      /html\.ft-scroll-world-on \.hero-title-char,[\s\S]*?\{([^}]*)\}/,
    );

    expect(activeHeroRule).not.toBeNull();
    const selector = activeHeroRule?.[0] ?? '';
    const declarations = activeHeroRule?.[1] ?? '';
    expect(selector).toContain('html.ft-scroll-world-on .hero-install');
    expect(selector).toContain('html.ft-scroll-world-on .hero-electron-note');
    expect(declarations).toMatch(/animation:\s*none\s*!important/);
    expect(declarations).toMatch(/opacity:\s*1\s*!important/);
    expect(declarations).toMatch(/filter:\s*none\s*!important/);
    expect(declarations).toMatch(/transform:\s*none\s*!important/);

    expect(cssSource).toMatch(/\.hero-title-char\s*\{[^}]*opacity:\s*0;[^}]*animation:\s*siteTypeChar/);
    expect(cssSource).toMatch(/\.hero-actions\s*\{[^}]*opacity:\s*0;[^}]*animation:\s*siteRiseInBlur/);
    expect(cssSource).toMatch(/\.hero-install\s*\{[^}]*opacity:\s*0;[^}]*animation:\s*siteRiseInBlur/);
    expect(cssSource).toMatch(/\.hero-electron-note\s*\{[^}]*opacity:\s*0;[^}]*animation:\s*siteRiseInBlur/);

    expect(wrapperSource.match(/classList\.add\('ft-scroll-world-on'\)/g)).toHaveLength(1);
    const firstSuccessfulRender = webglSource.indexOf('renderer.render(scene, camera)');
    const readySignal = webglSource.indexOf('onReady();', firstSuccessfulRender);
    expect(firstSuccessfulRender).toBeGreaterThan(-1);
    expect(readySignal).toBeGreaterThan(firstSuccessfulRender);
  });

  it('keeps every semantic hero child stable after an activated WebGL renderer falls back', () => {
    const fallbackHeroRule = cssSource.match(
      /html\.ft-scroll-world-fallback \.hero-title-char,[\s\S]*?\{([^}]*)\}/,
    );

    expect(fallbackHeroRule).not.toBeNull();
    const selector = fallbackHeroRule?.[0] ?? '';
    const declarations = fallbackHeroRule?.[1] ?? '';
    expect(selector).toContain('html.ft-scroll-world-fallback .hero-install');
    expect(selector).toContain('html.ft-scroll-world-fallback .hero-electron-note');
    expect(declarations).toMatch(/animation:\s*none\s*!important/);
    expect(declarations).toMatch(/opacity:\s*1\s*!important/);
    expect(declarations).toMatch(/filter:\s*none\s*!important/);
    expect(declarations).toMatch(/transform:\s*none\s*!important/);
  });

  it('keeps the pilot isolated behind a default-off, client-only dynamic boundary', () => {
    expect(pageSource).toContain("import SiteScrollWorld from '@/components/site-scroll-world'");
    expect(pageSource).toContain('<SiteScrollWorld />');
    expect(pageSource).not.toContain("from 'three'");
    expect(pageSource).not.toContain('@react-three');
    expect(wrapperSource).toContain("'use client'");
    expect(wrapperSource).toContain("import('./site-scroll-world-webgl')");
    expect(wrapperSource).toContain('ssr: false');
    expect(capabilitySource).toContain("NEXT_PUBLIC_FLINTTRADE_SITE_SCROLL_WORLD === '1'");
    expect(webglSource).toContain("from 'three'");
    expect(sitePackage.dependencies?.three).toMatch(/^\d+\.\d+\.\d+$/);
    expect(sitePackage.devDependencies?.['@types/three']).toMatch(/^\d+\.\d+\.\d+$/);
    // DefinitelyTyped publishes @types/three on the three major.minor line, not every patch.
    const releaseLine = (version: string | undefined) => version?.split('.').slice(0, 2).join('.');
    expect(releaseLine(sitePackage.devDependencies?.['@types/three'])).toBe(
      releaseLine(sitePackage.dependencies?.three),
    );
  });

  it('re-evaluates live capability changes and fails open after sustained slow rendering', () => {
    expect(wrapperSource).toContain("window.addEventListener('resize', onCapabilityChange)");
    expect(wrapperSource).toContain("connection?.addEventListener?.('change', onCapabilityChange)");
    expect(wrapperSource).toContain("connection?.removeEventListener?.('change', onCapabilityChange)");
    expect(webglSource).toContain("fail('performance-budget')");
    expect(webglSource).toContain('slowFloorWindows');
  });

  it('preserves semantic CTA continuity and keeps the WebGL surface decorative', () => {
    const primaryMatches = pageSource.match(/className="button primary"/g) || [];
    expect(primaryMatches).toHaveLength(1);
    expect(pageSource).toContain('Install the web app');
    expect(pageSource).toContain('href="/demo-app/welcome"');
    expect(pageSource).toContain('target="_blank"');
    expect(webglSource).toContain('aria-hidden="true"');
    expect(webglSource).toContain('role="presentation"');
    expect(cssSource).toMatch(/\.site-scroll-world-canvas\s*\{[^}]*pointer-events:\s*none/);
  });

  it('retains every Spark Path chapter exactly once across the page and its static product sections', () => {
    const chapterIds = [...`${pageSource}\n${productSource}`.matchAll(/data-scroll-chapter="([0-5])"/g)]
      .map((match) => Number(match[1])).sort((a, b) => a - b);
    expect(chapterIds).toEqual([0, 1, 2, 3, 4, 5]);
    expect(chapterSource).toContain("anchor: 'hero'");
    expect(chapterSource).toContain("anchor: 'source'");
    expect(chapterSource).toContain("anchor: 'docs'");
    expect(chapterSource).toContain("anchor: 'mcp'");
    expect(chapterSource).toContain("anchor: 'packages'");
    expect(chapterSource).toContain("anchor: 'footer'");
    expect(chapterSource).toContain('Source / built for people who read the source');
    expect(chapterSource).toContain('Docs, API, and contribution paths');
    expect(chapterSource).toContain('MCP for development, not trading');
    expect(chapterSource).toContain('Package map at contributor speed');
    expect(pageSource).toContain('data-scroll-chapter="0"');
    expect(productSource).toContain('className="section product-section"');
  });

  it('uses procedural/local scene data only and contains no network, trading, broker, terminal or demo integration', () => {
    const pilotSource = [wrapperSource, webglSource, capabilitySource, chapterSource].join('\n');
    expect(pilotSource).not.toMatch(/https?:\/\//);
    expect(pilotSource).not.toMatch(/TextureLoader|CubeTextureLoader|FontLoader|fetch\(|XMLHttpRequest|WebSocket/);
    expect(pilotSource).not.toMatch(/place_order|placeOrder|BrokerRouter|gate_order/);
    expect(pilotSource).not.toMatch(/packages\/apps\/terminal|demo-app/);
    expect(pilotSource).not.toContain('@react-three');
  });
});
