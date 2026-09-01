'use client';

/**
 * SectionEnterController — tiny dedicated client boundary for observed reveal.
 * Renders null. Implements real fail-open observed reveal:
 * - Server/no-JS and reduced-motion baselines are visible.
 * - Controller marks initially visible sections BEFORE enabling motion (adding root class).
 * - Non-visible observed sections enter when intersecting.
 * - Uses .js-motion-enabled root class + .visible per-section contract.
 * - Disconnects observer and removes activation class on cleanup.
 * - State-driven transition (not animation) on the hidden rule.
 */

import { useEffect } from 'react';

export default function SectionEnterController() {
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const sections = document.querySelectorAll<HTMLElement>('.section-enter');
    if (!sections.length) return;

    const html = document.documentElement;

    if (reduceMotion) {
      sections.forEach((section) => section.classList.add('visible'));
      return;
    }

    // Mark initially visible sections BEFORE adding root activation class (per Sol review)
    // so they stay visible from baseline and never receive the hidden state.
    sections.forEach((section) => {
      const rect = section.getBoundingClientRect();
      // Initially visible if any part is in viewport
      if (rect.top < window.innerHeight && rect.bottom > 0) {
        section.classList.add('visible');
      }
    });

    // Now enable motion for the remaining sections
    html.classList.add('js-motion-enabled');

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

    sections.forEach((section) => {
      if (!section.classList.contains('visible')) {
        observer.observe(section);
      }
    });

    return () => {
      observer.disconnect();
      html.classList.remove('js-motion-enabled');
    };
  }, []);

  return null;
}
