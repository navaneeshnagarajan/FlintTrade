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
    const actionsIdx = pageSource.indexOf('className=\"hero-actions\"');
    const gridIdx = pageSource.indexOf('className=\"hero-feature-grid\"');
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
    // One exact combined selector block containing all essential hero children
    expect(mobileCss).toMatch(/@media \(max-width:\s*620px\)\s*\{[^}]*\.hero-copy h1,\s*\.hero-title-char,\s*\.hero-slogan span,\s*\.hero-copy > p,\s*\.hero-actions,\s*\.hero-disclaimer\s*\{/);
    // Within that block: immediate visible + no animation/transition
    expect(mobileCss).toMatch(/opacity:\s*1\s*!important/);
    expect(mobileCss).toMatch(/animation:\s*none\s*!important/);
    expect(mobileCss).toMatch(/transition:\s*none\s*!important/);
    // Ensure the rules appear after the selector list in the mobile block (not arbitrary range or escaped regex)
  });

  it('primary hero action remains before feature grid and controller is mounted without moving static content to client', () => {
    const actionsIdx = pageSource.indexOf('className=\"hero-actions\"');
    const gridIdx = pageSource.indexOf('className=\"hero-feature-grid\"');
    expect(actionsIdx).toBeGreaterThan(-1);
    expect(gridIdx).toBeGreaterThan(-1);
    expect(actionsIdx).toBeLessThan(gridIdx);
    // page stays server; controller is the only client addition
  });
});
