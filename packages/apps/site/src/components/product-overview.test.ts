/** @vitest-environment jsdom */

import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';

import { ProductOverview } from './product-overview';

// Mounted public product seam. Real image custody is recorded separately;
// jsdom does not establish browser layout or the pixels in a screenshot.
afterEach(() => vi.unstubAllGlobals());

it('pairs every product view with a fresh public-demo image and an accessible example-data warning', async () => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(ProductOverview)));
    const views = [
      { name: 'Trading', asset: 'trading.webp', href: '/demo-app/terminal' },
      { name: 'Studio', asset: 'studio.webp', href: '/demo-app/testing' },
      { name: 'Review', asset: 'review.webp', href: '/demo-app/reports' },
    ];
    expect(container.querySelectorAll('figure')).toHaveLength(3);
    for (const view of views) {
      const section = [...container.querySelectorAll('section[aria-labelledby]')].find((candidate) =>
        document.getElementById(candidate.getAttribute('aria-labelledby') ?? '')?.textContent === view.name);
      expect(section, `${view.name} has a named section`).toBeDefined();
      const figure = section?.querySelector('figure');
      const image = figure?.querySelector('img');
      const caption = figure?.querySelector('figcaption');
      expect(decodeURIComponent(image?.getAttribute('src') ?? '')).toContain(`/product/${view.asset}`);
      expect(image?.getAttribute('alt')).toMatch(/FlintTrade.*example data/i);
      expect(image?.getAttribute('width')).toBe('1600');
      expect(image?.getAttribute('height')).toBe('900');
      expect(caption?.textContent).toMatch(/example data/i);
      expect(caption?.textContent).toMatch(/not live market data or trading performance/i);
      expect(caption?.textContent).not.toMatch(/earlier version|future returns|guaranteed|qualified/i);
      const link = section?.querySelector(`a[href="${view.href}"]`);
      expect(link?.textContent).toContain('example data');
      expect(link?.getAttribute('rel')).toContain('noopener');
      expect(link?.getAttribute('target')).toBe('_blank');
    }
    expect(container.textContent).toContain('A conversation is not trading permission.');
    expect(container.textContent).toContain('Live execution needs explicit account permissions and qualification');
    expect(container.textContent).toContain('No broker is connected and no orders are sent.');
    expect(container.textContent).not.toMatch(/live prices|verified returns|guaranteed returns|broker connected|production.ready/i);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
