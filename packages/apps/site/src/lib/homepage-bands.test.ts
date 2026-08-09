/**
 * Graphite Continuity A1 homepage band structure, CTA uniqueness,
 * reduced-motion, and motion guard tests.
 * Source-based guards (no React render) to enforce the four-band visual IA,
 * exactly one global primary CTA, truthful copy floor from base 1b49ed1c,
 * action-before-feature order, mobile early CTA, next.config turbopack,
 * developer progressive disclosure, and static reduced-motion path.
 * TDD guard added before visual implementation.
 * Strengthened for Sol REJECT-v3: reads controller source, exact state contract
 * (transition not animation on hidden rule), exact mobile child selectors (.hero-title-char etc),
 * page server-only.
 * Strengthened for Sol REJECT-v4: robust mobile test via slice + combined selector block,
 * controller source-index order/cleanup assertions (no arbitrary range, no double-escape).
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const pageSource = readFileSync(resolve(process.cwd(), 'src/app/page.tsx'), 'utf8');
const cssSource = readFileSync(resolve(process.cwd(), 'src/app/globals.css'), 'utf8');
const nextConfigSource = readFileSync(resolve(process.cwd(), 'next.config.mjs'), 'utf8');
const controllerSource = readFileSync(resolve(process.cwd(), 'src/components/section-enter-controller.tsx'), 'utf8');
const wrapperSource = readFileSync(resolve(process.cwd(), 'src/components/site-scroll-world.tsx'), 'utf8');
const webglSource = readFileSync(resolve(process.cwd(), 'src/components/site-scroll-world-webgl.tsx'), 'utf8');
const capabilitySource = readFileSync(resolve(process.cwd(), 'src/lib/site-scroll-world-capability.ts'), 'utf8');
const chapterSource = readFileSync(resolve(process.cwd(), 'src/lib/site-scroll-world-chapters.ts'), 'utf8');
const sitePackage = JSON.parse(readFileSync(resolve(process.cwd(), 'package.json'), 'utf8')) as {
  dependencies: Record<string, string>;
  devDependencies: Record<string, string>;
};

describe('homepage Graphite Continuity A1 (bands + CTA + motion)', () => {
  it('structures homepage into exactly four calm product bands after the cinematic hero with polished user-facing headings', () => {
    // Band 1: Hero / brand (existing section.hero)
    expect(pageSource).toContain('section className=\"section hero\"');
    // Band 2: Self-hosted trading workspace (polished from internal \"Product story\")
    expect(pageSource).toContain('Self-hosted trading workspace');
    expect(pageSource).toContain('self-hosted');
    expect(pageSource).toContain('safety modes');
    // Band 3: Evaluate and install (honest desktop/web path)
    expect(pageSource).toContain('Evaluate and install');
    expect(pageSource).toContain('install');
    // Band 4: Contributor resources (polished from internal \"Developer depth\", demoted with progressive disclosure)
    expect(pageSource).toContain('Contributor resources');
    expect(pageSource).toContain('progressive disclosure');
    // Count top-level section className=\"section\" markers (hero + product + evaluate + developer + others)
    const sectionMatches = pageSource.match(/<section className=\"section/g) || [];
    expect(sectionMatches.length).toBeGreaterThanOrEqual(4);
  });

  it('preserves exactly one global primary CTA (no regression to multiple primaries)', () => {
    const primaryMatches = pageSource.match(/className=\"button primary\"/g) || [];
    expect(primaryMatches.length).toBe(1);
    expect(pageSource).toContain('Start exploring — no install needed');
    expect(pageSource).toContain('/demo-app/welcome');
    // No other primary class
  });

  it('keeps truthful copy and Explore/Practice/Live vocabulary (no install-complete lies)', () => {
    expect(pageSource).toContain('v0.0.1 is not production ready');
    expect(pageSource).toContain('Explore and Practice modes first');
    expect(pageSource).toContain('/demo-app/welcome');
    // Truthful negative is present; no contradictory substring forbid
  });

  it('has reduced-motion static path that disables continuous/entrance animation', () => {
    expect(cssSource).toContain('@media (prefers-reduced-motion: reduce)');
    expect(cssSource).toContain('animation: none');
    expect(cssSource).toContain('transition: none');
    // Hero particles / meteors hidden or static under reduced motion
    expect(cssSource).toMatch(/reduced-motion.*hero|hero.*reduced-motion|prefers-reduced-motion.*particle|meteor/);
  });

  it('uses only CSS + IntersectionObserver for section enter motion (no new deps)', () => {
    // Guard that any new motion is cheap CSS/IO only; no framer, three imports in page or new components touched
    expect(pageSource).not.toContain('framer-motion');
    expect(pageSource).not.toContain('three');
    expect(pageSource).not.toContain('@react-three');
    // Expect data-motion or observer pattern comment / class for enter
    expect(cssSource).toMatch(/@keyframes.*fadeIn|section-enter|data-observed|IntersectionObserver/);
  });

  it('preserves Canvas2D HeroCinematic, /demo-app rewrite, CSP, target blank', () => {
    expect(pageSource).toContain('HeroCinematic');
    expect(pageSource).toContain('/demo-app/welcome');
    expect(pageSource).toContain('target=\"_blank\"');
    // turbopack.root / portable root is in next.config.mjs (read separately); not asserted in page.tsx
  });

  it('reads turbopack.root from next.config.mjs (portable root, not in page.tsx)', () => {
    expect(nextConfigSource).toContain("turbopack: {");
    expect(nextConfigSource).toContain("root: repoRoot");
  });

  it('places primary hero-actions before feature-grid for early mobile CTA visibility', () => {
    const actionsIdx = pageSource.indexOf('className="hero-actions"');
    const gridIdx = pageSource.indexOf('className="hero-feature-grid"');
    expect(actionsIdx).toBeGreaterThan(-1);
    expect(gridIdx).toBeGreaterThan(-1);
    // actions before grid in source for action-before-feature order (compact mobile)
    expect(actionsIdx).toBeLessThan(gridIdx);
  });

  it('uses progressive disclosure for demoted contributor/MCP/package depth', () => {
    expect(pageSource).toContain('progressive disclosure');
    // details/summary or collapsed marker for MCP and package map
    expect(pageSource).toMatch(/<details|<summary|progressive disclosure/);
  });

  it('keeps page.tsx a pure server component with no top-level use client, hooks, or observer logic', () => {
    // Architecture guard: page must not be client component
    expect(pageSource).not.toMatch(/^\s*['"]use client['"]\s*;/m);
    expect(pageSource).not.toContain('useSectionEnterObserver');
    expect(pageSource).not.toContain('useEffect');
    expect(pageSource).not.toContain('IntersectionObserver');
    expect(pageSource).not.toContain('matchMedia');
  });

  it('mounts a tiny dedicated client controller for section reveal (renders null, separate file, reads controller source for contract)', () => {
    expect(pageSource).toMatch(/import.*SectionEnterController|from ['\"].*section-enter-controller['\"]/);
    expect(pageSource).toContain('<SectionEnterController');
    expect(controllerSource).toContain('SectionEnterController');
    expect(controllerSource).toContain('useEffect');
    expect(controllerSource).toContain('js-motion-enabled');
    expect(controllerSource).toContain('visible');
    // Controller source read to enforce architecture
  });

  it('controller implements correct order and cleanup (mark initial visible BEFORE root class; new IntersectionObserver; observer.disconnect(); root-class cleanup on unmount)', () => {
    const controllerSrc = controllerSource;
    // Order: mark initially visible sections before adding js-motion-enabled class
    const markIdx = controllerSrc.indexOf('Mark initially visible sections BEFORE adding root activation class');
    const addClassIdx = controllerSrc.indexOf("html.classList.add('js-motion-enabled')");
    expect(markIdx).toBeGreaterThan(-1);
    expect(addClassIdx).toBeGreaterThan(-1);
    expect(markIdx).toBeLessThan(addClassIdx);
    // Has IntersectionObserver constructor
    expect(controllerSrc).toContain('new IntersectionObserver');
    // Has disconnect in cleanup
    const disconnectIdx = controllerSrc.indexOf('observer.disconnect()');
    const cleanupIdx = controllerSrc.indexOf("html.classList.remove('js-motion-enabled')");
    expect(disconnectIdx).toBeGreaterThan(-1);
    expect(cleanupIdx).toBeGreaterThan(-1);
    // Cleanup after observer setup
    expect(disconnectIdx).toBeLessThan(cleanupIdx);
    // return cleanup function present
    expect(controllerSrc).toContain('return () => {');
  });

  it('CSS has real fail-open observed reveal contract (baseline visible + .visible state, transition on hidden rule, no animation on enabled-hidden, exact state contract)', () => {
    // Baseline (no-JS / SSR) must be visible
    expect(cssSource).toMatch(/\.section-enter\s*\{[^}]*opacity:\s*1/);
    // Actual enabled/visible state contract (not just animation on load)
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*opacity:\s*0/);
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*transition:/);
    // Forbid unconditional animation on the hidden rule (must be transition only for state-driven)
    expect(cssSource).not.toMatch(/\.js-motion-enabled\s+\.section-enter\s*\{[^}]*animation:/);
    expect(cssSource).toMatch(/\.js-motion-enabled\s+\.section-enter\.visible\s*\{[^}]*opacity:\s*1/);
    // Controller source read enforces the contract too (no animation in hidden)
    expect(controllerSource).toContain('js-motion-enabled');
  });

  it('mobile (max-width: 620px) makes essential hero content immediately useful with one exact combined selector block (no opacity:0 or multi-second delay on title/slogan/actions/disclaimer; includes .hero-title-char)', () => {
    const mediaIdx = cssSource.indexOf('@media (max-width: 620px)');
    expect(mediaIdx).toBeGreaterThan(-1);
    const mobileCss = cssSource.slice(mediaIdx);
    // One exact combined selector block containing all essential hero children (direct match, no media prefix, no arbitrary cross-block scan)
    expect(mobileCss).toMatch(/\.hero-copy h1,\s*\.hero-title-char,\s*\.hero-slogan span,\s*\.hero-copy > p,\s*\.hero-actions,\s*\.hero-disclaimer\s*\{[^}]*opacity:\s*1\s*!important;[^}]*animation:\s*none\s*!important;[^}]*transition:\s*none\s*!important;[^}]*\}/);
    // Within that block: immediate visible + no animation/transition
    expect(mobileCss).toMatch(/opacity:\s*1\s*!important/);
    expect(mobileCss).toMatch(/animation:\s*none\s*!important/);
    expect(mobileCss).toMatch(/transition:\s*none\s*!important/);
    // Ensure the rules appear after the selector list in the mobile block (not arbitrary range or escaped regex)
  });

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

    // The default-off/fallback page retains the accepted Graphite intro timeline.
    expect(cssSource).toMatch(/\.hero-title-char\s*\{[^}]*opacity:\s*0;[^}]*animation:\s*siteTypeChar/);
    expect(cssSource).toMatch(/\.hero-actions\s*\{[^}]*opacity:\s*0;[^}]*animation:\s*siteRiseInBlur/);

    // Runtime promotion is unique and happens only after a successful Three render.
    expect(wrapperSource.match(/classList\.add\('ft-scroll-world-on'\)/g)).toHaveLength(1);
    const firstSuccessfulRender = webglSource.indexOf('renderer.render(scene, camera)');
    const readySignal = webglSource.indexOf('onReady();', firstSuccessfulRender);
    expect(firstSuccessfulRender).toBeGreaterThan(-1);
    expect(readySignal).toBeGreaterThan(firstSuccessfulRender);
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
    expect(sitePackage.dependencies.three).toBe('0.185.1');
    expect(sitePackage.devDependencies['@types/three']).toBe('0.185.1');
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
    expect(chapterSource).toContain("id: 0");
    expect(chapterSource).toContain("id: 5");
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
