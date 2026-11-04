'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';

/** Retire only the completed intro; never hide the user's keyboard focus. */
export function IntroHandoff({ children, product }: { children: ReactNode; product: ReactNode }) {
  const intro = useRef<HTMLDivElement>(null);
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const element = intro.current;
    // Keep the original content usable when animation inspection is unavailable.
    if (!element?.getAnimations) return;
    let disposed = false;
    let ready = false;
    let generation = 0;
    let frame = 0;
    const retire = () => {
      if (!disposed && ready && !element.contains(document.activeElement)) setSettled(true);
    };
    // Focus may move between intro links. Inspect its final owner after focusout.
    const onFocusOut = (event: FocusEvent) => {
      // Native Tab dispatch can run microtasks before focusin. relatedTarget
      // owns that transition; never retire between two controls in this intro.
      if (event.relatedTarget instanceof Node && element.contains(event.relatedTarget)) return;
      queueMicrotask(retire);
    };
    const observe = () => {
      ready = false;
      const current = ++generation;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const signature = element.getAnimations({ subtree: true }).filter((animation) =>
          animation.effect?.getComputedTiming().iterations !== Infinity);
        void Promise.allSettled(signature.map((animation) => animation.finished)).then(() => {
          if (disposed || current !== generation) return;
          ready = true;
          retire();
        });
      });
    };
    const preference = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
    element.addEventListener('focusout', onFocusOut);
    preference?.addEventListener('change', observe);
    observe();
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      element.removeEventListener('focusout', onFocusOut);
      preference?.removeEventListener('change', observe);
    };
  }, []);
  return <>
    <div ref={intro} className="site-intro-boundary" data-site-intro hidden={settled}>{children}</div>
    <div className="site-product-boundary" data-site-product hidden={!settled}>{product}</div>
  </>;
}
