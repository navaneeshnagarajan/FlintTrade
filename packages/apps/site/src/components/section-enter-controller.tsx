'use client';

import { useEffect } from 'react';

/**
 * Tiny client-only IntersectionObserver controller for .section-enter reveals.
 * Fail-open: SSR / no-JS / reduced-motion sections are visible by default.
 * JS + motion: starts unrevealed, IO adds .visible to trigger reveal.
 * Keeps page.tsx a server component (no whole-page 'use client').
 */
export function SectionEnterController() {
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion) return;

    // Mark root so CSS can apply motion-ready hidden state only for JS clients
    document.documentElement.classList.add('section-motion');

    const sections = document.querySelectorAll<HTMLElement>('.section-enter');
    if (!sections.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px -10% 0px' }
    );

    sections.forEach((section) => observer.observe(section));

    return () => observer.disconnect();
  }, []);

  return null;
}
