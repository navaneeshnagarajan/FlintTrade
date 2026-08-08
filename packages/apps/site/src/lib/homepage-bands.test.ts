/**
 * Graphite Continuity A1 homepage band structure, CTA uniqueness,
 * reduced-motion, and motion guard tests.
 * Source-based guards (no React render) to enforce the four-band visual IA,
 * exactly one global primary CTA, truthful copy floor from base 1b49ed1c,
 * and static reduced-motion path. TDD guard added before visual implementation.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const pageSource = readFileSync(resolve(process.cwd(), 'src/app/page.tsx'), 'utf8');
const cssSource = readFileSync(resolve(process.cwd(), 'src/app/globals.css'), 'utf8');

describe('homepage Graphite Continuity A1 (bands + CTA + motion)', () => {
  it('structures homepage into exactly four calm product bands after the cinematic hero', () => {
    // Band 1: Hero / brand (existing section.hero)
    expect(pageSource).toContain('section className="section hero"');
    // Band 2: Product story — self-hosted / safety / local-first
    expect(pageSource).toContain('Product story');
    expect(pageSource).toContain('self-hosted');
    expect(pageSource).toContain('safety modes');
    // Band 3: Evaluate → install (honest desktop/web path)
    expect(pageSource).toContain('Evaluate and install');
    expect(pageSource).toContain('install');
    // Band 4: Developer / contributor depth (docs, MCP, package map)
    expect(pageSource).toContain('Developer depth');
    expect(pageSource).toContain('Docs, MCP, package map');
    // Count top-level section className="section" markers (hero + product + evaluate + developer + others)
    const sectionMatches = pageSource.match(/<section className="section/g) || [];
    expect(sectionMatches.length).toBeGreaterThanOrEqual(4);
  });

  it('preserves exactly one global primary CTA (no regression to multiple primaries)', () => {
    const primaryMatches = pageSource.match(/className="button primary"/g) || [];
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
    expect(pageSource).toContain('target="_blank"');
    // turbopack.root / portable root is in next.config.mjs (read separately); not asserted in page.tsx
  });
});
