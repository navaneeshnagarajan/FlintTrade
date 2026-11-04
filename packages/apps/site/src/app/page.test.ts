/** @vitest-environment jsdom */

import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CANONICAL_SITE_ORIGIN } from '@/lib/site-origin';

import HomePage from './page';
import DownloadPage from './download/page';
import ApiReferencePage from './api-reference/page';
import McpPage from './mcp/page';
import ContributePage from './contribute/page';
import NotFound from './not-found';

// This seam mounts the resolved public page, not a mock marketing composition.
// Next request handling, CSS layout and cinematic frame timing need browser acceptance.
describe('public website journey', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.stubGlobal('React', React);
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Network disabled in site journey'))));
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('lets readers explore Trading, Studio and Review without presenting example data as live results', async () => {
    await act(async () => root.render(await HomePage()));
    expect([...container.querySelectorAll('[data-scroll-chapter]')].map((section) => section.getAttribute('data-scroll-chapter')))
      .toEqual(['0', '1', '2', '3', '4', '5']);
    const journeys = [
      { name: 'Trading', href: '/demo-app/terminal' },
      { name: 'Studio', href: '/demo-app/testing' },
      { name: 'Review', href: '/demo-app/reports' },
    ];
    for (const journey of journeys) {
      const section = [...container.querySelectorAll('section[aria-labelledby]')].find((candidate) => {
        const heading = document.getElementById(candidate.getAttribute('aria-labelledby') ?? '');
        return heading?.textContent === journey.name;
      });
      expect(section, `${journey.name} has a named product section`).toBeDefined();
      const link = section?.querySelector(`a[href="${journey.href}"]`);
      expect(link?.textContent).toContain('example data');
      expect(link?.getAttribute('rel')).toContain('noopener');
    }
    const figures = [...container.querySelectorAll('figure')];
    expect(figures).toHaveLength(4);
    for (const figure of figures) {
      const caption = figure.querySelector('figcaption')?.textContent;
      expect(caption).toContain('example data');
      expect(caption).toContain('not live market data or trading performance');
      expect(caption).not.toMatch(/earlier version|verified returns|guaranteed/i);
      expect(figure.querySelector('img')?.getAttribute('alt')).toMatch(/example data/i);
    }
    expect(container.textContent).toContain('manual orders, automation, and AI-assisted workflows');
    expect(container.textContent).toContain('A conversation is not trading permission.');
    expect(container.textContent).toContain('No broker is connected and no orders are sent.');
  });

  it('keeps navigation, a keyboard skip target and legal guidance reachable in the compact menu', async () => {
    await act(async () => root.render(await HomePage()));
    const menu = container.querySelector<HTMLDetailsElement>('details.site-menu');
    expect(menu).not.toBeNull();
    expect(menu?.open).toBe(false);
    await act(async () => menu?.querySelector('summary')?.click());
    expect(menu?.open).toBe(true);
    const links = [...(menu?.querySelectorAll('a') ?? [])].map((link) => link.getAttribute('href'));
    expect(links).toEqual(['/explore', '/download', '/demo-app/welcome', '/docs', '/api-reference', '/mcp', '/contribute']);
    const skip = container.querySelector<HTMLAnchorElement>('a[href="#site-content"]');
    expect(skip?.textContent).toBe('Skip to content');
    expect(container.querySelector('#site-content')?.tagName).toBe('MAIN');
    const footer = container.querySelector('footer');
    expect(footer?.querySelector('a[href="/docs/disclaimer"]')?.textContent).toBe('Risk disclaimer');
    expect(footer?.textContent).toContain('AGPL-3.0 open source software');
  });

  it('preserves usable destination pages and an honest download fallback when release lookup fails', async () => {
    const pages = [
      { render: DownloadPage, path: '/download' },
      { render: ApiReferencePage, path: '/api-reference' },
      { render: McpPage, path: '/mcp' },
      { render: ContributePage, path: '/contribute' },
    ];
    for (const page of pages) {
      await act(async () => root.render(await page.render()));
      expect(container.querySelector('main#site-content h1'), page.path).not.toBeNull();
      const current = container.querySelector('nav[aria-label="Primary navigation"] a[aria-current="page"]');
      expect(current?.getAttribute('href')).toBe(page.path);
    }
    await act(async () => root.render(await DownloadPage()));
    expect(container.textContent).toContain('Desktop release status temporarily unavailable');
    expect(container.textContent).not.toContain('Electron installer release pending');
    expect(container.textContent).toContain('web-install.sh | bash');
    expect(container.textContent).not.toContain(`${CANONICAL_SITE_ORIGIN}/install.sh | bash`);
    expect(container.textContent).toContain('If this site is unreachable');
    expect(container.textContent).toContain('Uninstall');
    await act(async () => root.render(React.createElement(NotFound)));
    expect(container.querySelector('main#site-content h1')?.textContent).toBe('Page not found');
    expect(container.querySelector('a[href="/docs"]')).not.toBeNull();
  });

  it('introduces the product before offering distinct install and example-data paths', async () => {
    const page = await HomePage();
    await act(async () => root.render(page));
    const hero = container.querySelector('.hero');
    expect(hero?.textContent).toContain('Research, practise and review');
    expect(hero?.querySelector('h1')?.getAttribute('aria-label')).toBe('FlintTrade');
    expect(hero?.querySelectorAll('.site-impact-debris')).toHaveLength(8);
    expect(hero?.querySelector('pre')).toBeNull();
    const install = hero?.querySelector('a[href="/download"]');
    expect(install?.textContent).toContain('Install the web app');
    const demo = hero?.querySelector('a[href="/demo-app/welcome"]');
    expect(demo?.textContent).toContain('Demo (example data)');
    expect(demo?.getAttribute('target')).toBe('_blank');
    expect(demo?.getAttribute('rel')).toContain('noopener');
  });
});
