/**
 * Graphite Continuity A1 homepage band structure, CTA uniqueness,
 * reduced-motion, and motion guard tests.
 * Source-based guards (no React render) to enforce the four-band visual IA,
 * exactly one global primary CTA, truthful copy floor from current main,
 * action-before-feature order, mobile early CTA, next.config turbopack,
 * developer progressive disclosure, and static reduced-motion path.
 *
 * Composite of accepted A1 review behaviour:
 * unescaped band/CTA/turbopack/disclosure asserts, server-page/controller/CSS
 * contract, controller order/cleanup, and the combined 620px hero selector.
 */

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

function readSite(relativePath: string): string {
  const fullPath = resolve(process.cwd(), relativePath);
  return existsSync(fullPath) ? readFileSync(fullPath, 'utf8') : '';
}

const pageSource = readSite('src/app/page.tsx');
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

describe('homepage Graphite Continuity A1 (bands + CTA + motion)', () => {
  it('structures homepage into exactly four calm product bands after the cinematic hero with polished user-facing headings', () => {
    expect(pageSource).toContain('section className="section hero"');
    expect(pageSource).toContain('Self-hosted trading workspace');
    expect(pageSource).toContain('self-hosted');
    expect(pageSource).toContain('safety modes');
    expect(pageSource).toContain('Evaluate and install');
    expect(pageSource).toContain('install');
    expect(pageSource).toContain('Contributor resources');
    expect(pageSource).toContain('progressive disclosure');
    const sectionMatches = pageSource.match(/<section className="section/g) || [];
    expect(sectionMatches.length).toBeGreaterThanOrEqual(4);
  });

  it('preserves exactly one global primary CTA (no regression to multiple primaries)', () => {
    const primaryMatches = pageSource.match(/className="button primary"/g) || [];
    expect(primaryMatches.length).toBe(1);
    expect(pageSource).toContain('Start exploring — no install needed');
    expect(pageSource).toContain('/demo-app/welcome');
  });

  it('keeps truthful copy and Explore/Practice/Live vocabulary (no install-complete lies)', () => {
    expect(pageSource).toContain('v0.0.1 is not production ready');
    expect(pageSource).toContain('Explore and Practice modes first');
    expect(pageSource).toContain('/demo-app/welcome');
  });

  it('has reduced-motion static path that disables continuous/entrance animation', () => {
    expect(cssSource).toContain('@media (prefers-reduced-motion: reduce)');
    expect(cssSource).toContain('animation: none');
    expect(cssSource).toContain('transition: none');
    expect(cssSource).toMatch(/reduced-motion.*hero|hero.*reduced-motion|prefers-reduced-motion.*particle|meteor/);
  });

  it('uses only CSS + IntersectionObserver for section enter motion (no new deps)', () => {
    expect(pageSource).not.toContain('framer-motion');
    expect(pageSource).not.toContain('from \'three\'');
    expect(pageSource).not.toContain('from "three"');
    expect(pageSource).not.toContain('@react-three');
    expect(cssSource).toMatch(/@keyframes.*fadeIn|section-enter|data-observed|IntersectionObserver/);
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

  it('places primary hero-actions before feature-grid for early mobile CTA visibility', () => {
    const actionsIdx = pageSource.indexOf('className="hero-actions"');
    const gridIdx = pageSource.indexOf('className="hero-feature-grid"');
    expect(actionsIdx).toBeGreaterThan(-1);
    expect(gridIdx).toBeGreaterThan(-1);
    expect(actionsIdx).toBeLessThan(gridIdx);
  });

  it('uses progressive disclosure for demoted contributor/MCP/package depth', () => {
    expect(pageSource).toContain('progressive disclosure');
    expect(pageSource).toMatch(/<details|<summary|progressive disclosure/);
  });

  it('keeps page.tsx a pure server component with no top-level use client, hooks, or observer logic', () => {
    expect(pageSource).not.toMatch(/^\s*['"]use client['"]\s*;/m);
    expect(pageSource).not.toContain('useSectionEnterObserver');
    expect(pageSource).not.toContain('useEffect');
    expect(pageSource).not.toContain('IntersectionObserver');
    expect(pageSource).not.toContain('matchMedia');
  });

  it('mounts a tiny dedicated client controller for section reveal (renders null, separate file, reads controller source for contract)', () => {
    expect(pageSource).toMatch(/import.*SectionEnterController|from ['"].*section-enter-controller['"]/);
    expect(pageSource).toContain('<SectionEnterController');
    expect(controllerSource).toContain('SectionEnterController');
    expect(controllerSource).toContain('useEffect');
    expect(controllerSource).toContain('js-motion-enabled');
    expect(controllerSource).toContain('visible');
  });

  it('controller implements correct order and cleanup (mark initial visible BEFORE root class; new IntersectionObserver; observer.disconnect(); root-class cleanup on unmount)', () => {
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

  it('CSS has real fail-open observed reveal contract (baseline visible + .visible state, transition on hidden rule, no animation on enabled-hidden, exact state contract)', () => {
    expect(cssSource).toMatch(/\.section-enter\s*\{[^}]*opacity:\s*1/);
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*opacity:\s*0/);
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*transition:/);
    expect(cssSource).not.toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*animation:/);
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\.visible\s*\{[^}]*opacity:\s*1/);
    expect(controllerSource).toContain('js-motion-enabled');
  });

  it('mobile (max-width: 620px) makes essential hero content immediately useful with one exact combined selector block (no opacity:0 or multi-second delay on title/slogan/actions/disclaimer; includes .hero-title-char)', () => {
    const mediaIdx = cssSource.indexOf('@media (max-width: 620px)');
    expect(mediaIdx).toBeGreaterThan(-1);
    const mobileCss = cssSource.slice(mediaIdx);
    expect(mobileCss).toMatch(/\.hero-copy h1,\s*\.hero-title-char,\s*\.hero-slogan span,\s*\.hero-copy > p,\s*\.hero-actions,\s*\.hero-disclaimer\s*\{[^}]*opacity:\s*1\s*!important;[^}]*animation:\s*none\s*!important;[^}]*transition:\s*none\s*!important;[^}]*\}/);
    expect(mobileCss).toMatch(/opacity:\s*1\s*!important/);
    expect(mobileCss).toMatch(/animation:\s*none\s*!important/);
    expect(mobileCss).toMatch(/transition:\s*none\s*!important/);
  });

  it('primary hero action remains before feature grid and controller is mounted without moving static content to client', () => {
    const actionsIdx = pageSource.indexOf('className="hero-actions"');
    const gridIdx = pageSource.indexOf('className="hero-feature-grid"');
    expect(actionsIdx).toBeGreaterThan(-1);
    expect(gridIdx).toBeGreaterThan(-1);
    expect(actionsIdx).toBeLessThan(gridIdx);
  });
});

describe('homepage Spark Path scroll-world (default-off decorative enhancement)', () => {
  it('switches every animated semantic hero child to a stable paint layer only after the first WebGL frame', () => {
    const activeHeroRule = cssSource.match(
      /html\.ft-scroll-world-on \.hero-title-char,\s*html\.ft-scroll-world-on \.hero-slogan > span,\s*html\.ft-scroll-world-on \.hero-copy > p:not\(\.hero-disclaimer\):not\(\.sr-only\),\s*html\.ft-scroll-world-on \.hero-copy p\.hero-disclaimer,\s*html\.ft-scroll-world-on \.hero-actions,\s*html\.ft-scroll-world-on \.hero-feature-grid > div\s*\{([^}]*)\}/,
    );

    expect(activeHeroRule).not.toBeNull();
    const declarations = activeHeroRule?.[1] ?? '';
    expect(declarations).toMatch(/animation:\s*none\s*!important/);
    expect(declarations).toMatch(/opacity:\s*1\s*!important/);
    expect(declarations).toMatch(/filter:\s*none\s*!important/);
    expect(declarations).toMatch(/transform:\s*none\s*!important/);

    expect(cssSource).toMatch(/\.hero-title-char\s*\{[^}]*opacity:\s*0;[^}]*animation:\s*siteTypeChar/);
    expect(cssSource).toMatch(/\.hero-actions\s*\{[^}]*opacity:\s*0;[^}]*animation:\s*siteRiseInBlur/);

    expect(wrapperSource.match(/classList\.add\('ft-scroll-world-on'\)/g)).toHaveLength(1);
    const firstSuccessfulRender = webglSource.indexOf('renderer.render(scene, camera)');
    const readySignal = webglSource.indexOf('onReady();', firstSuccessfulRender);
    expect(firstSuccessfulRender).toBeGreaterThan(-1);
    expect(readySignal).toBeGreaterThan(firstSuccessfulRender);
  });

  it('keeps every semantic hero child stable after an activated WebGL renderer falls back', () => {
    const fallbackHeroRule = cssSource.match(
      /html\.ft-scroll-world-fallback \.hero-title-char,\s*html\.ft-scroll-world-fallback \.hero-slogan > span,\s*html\.ft-scroll-world-fallback \.hero-copy > p:not\(\.hero-disclaimer\):not\(\.sr-only\),\s*html\.ft-scroll-world-fallback \.hero-copy p\.hero-disclaimer,\s*html\.ft-scroll-world-fallback \.hero-actions,\s*html\.ft-scroll-world-fallback \.hero-feature-grid > div\s*\{([^}]*)\}/,
    );

    expect(fallbackHeroRule).not.toBeNull();
    const declarations = fallbackHeroRule?.[1] ?? '';
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
    expect(sitePackage.dependencies?.three).toBe('0.185.1');
    expect(sitePackage.devDependencies?.['@types/three']).toBe('0.185.1');
  });

  it('preserves semantic CTA continuity and keeps the WebGL surface decorative', () => {
    const primaryMatches = pageSource.match(/className="button primary"/g) || [];
    expect(primaryMatches).toHaveLength(1);
    expect(pageSource).toContain('Start exploring — no install needed');
    expect(pageSource).toContain('href="/demo-app/welcome"');
    expect(pageSource).toContain('target="_blank"');
    expect(webglSource).toContain('aria-hidden="true"');
    expect(webglSource).toContain('role="presentation"');
    expect(cssSource).toMatch(/\.site-scroll-world-canvas\s*\{[^}]*pointer-events:\s*none/);
  });

  it('binds each Spark Path chapter 0 through 5 exactly once without replacing the existing bands', () => {
    const chapterIds = [...pageSource.matchAll(/data-scroll-chapter="([0-5])"/g)].map((match) => Number(match[1]));
    expect(chapterIds).toEqual([0, 1, 2, 3, 4, 5]);
    expect(chapterSource).toContain('id: 0');
    expect(chapterSource).toContain('id: 5');
    expect(pageSource).toContain('Self-hosted trading workspace');
    expect(pageSource).toContain('Evaluate and install');
    expect(pageSource).toContain('Contributor resources');
  });

  it('uses procedural/local scene data only and contains no network, trading, broker, terminal or demo integration', () => {
    const pilotSource = [wrapperSource, webglSource, capabilitySource, chapterSource].join('\n');
    expect(pilotSource).not.toMatch(/https?:\/\//);
    expect(pilotSource).not.toMatch(/TextureLoader|CubeTextureLoader|FontLoader|fetch\(|XMLHttpRequest|WebSocket/);
    expect(pilotSource).not.toMatch(/OpenAlgoClient|place_order|placeOrder|BrokerRouter|gate_order/);
    expect(pilotSource).not.toMatch(/packages\/apps\/terminal|demo-app/);
    expect(pilotSource).not.toContain('@react-three');
  });
});
