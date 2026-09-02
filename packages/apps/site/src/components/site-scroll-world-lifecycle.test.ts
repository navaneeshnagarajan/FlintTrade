import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';

import { createScrollWorldLifecycle } from './site-scroll-world-lifecycle';

describe('scroll-world child lifecycle', () => {
  it('reports context loss through the real child callback and disposes every resource exactly once', () => {
    const onFallback = vi.fn();
    const renderer = { dispose: vi.fn(), forceContextLoss: vi.fn() };
    const geometry = { dispose: vi.fn() };
    const material = { dispose: vi.fn() };
    const removeListeners = vi.fn();
    const lifecycle = createScrollWorldLifecycle(onFallback);

    lifecycle.setRenderer(renderer);
    lifecycle.track(geometry);
    lifecycle.track(geometry);
    lifecycle.track(material);
    lifecycle.addCleanup(removeListeners);

    const contextLoss = new Event('webglcontextlost', { cancelable: true });
    lifecycle.onContextLost(contextLoss);
    lifecycle.onContextLost(new Event('webglcontextlost', { cancelable: true }));
    lifecycle.dispose();

    expect(contextLoss.defaultPrevented).toBe(true);
    expect(onFallback).toHaveBeenCalledTimes(1);
    expect(onFallback).toHaveBeenCalledWith('context-lost');
    expect(removeListeners).toHaveBeenCalledTimes(1);
    expect(geometry.dispose).toHaveBeenCalledTimes(1);
    expect(material.dispose).toHaveBeenCalledTimes(1);
    expect(renderer.dispose).toHaveBeenCalledTimes(1);
    expect(renderer.forceContextLoss).toHaveBeenCalledTimes(0);
    expect(lifecycle.isDisposed()).toBe(true);
  });

  it('does not force context loss on dispose so StrictMode can reuse the canvas', () => {
    const onFallback = vi.fn();
    const renderer = { dispose: vi.fn(), forceContextLoss: vi.fn() };
    const lifecycle = createScrollWorldLifecycle(onFallback);

    lifecycle.setRenderer(renderer);
    lifecycle.dispose();
    lifecycle.setRenderer({ dispose: vi.fn(), forceContextLoss: vi.fn() });

    expect(renderer.dispose).toHaveBeenCalledTimes(1);
    expect(renderer.forceContextLoss).not.toHaveBeenCalled();
  });

  it('supports fail-closed try/finally setup errors without duplicate disposal or callbacks', () => {
    const onFallback = vi.fn();
    const renderer = { dispose: vi.fn(), forceContextLoss: vi.fn() };
    const resource = { dispose: vi.fn() };
    const lifecycle = createScrollWorldLifecycle(onFallback);
    let setupComplete = false;

    try {
      lifecycle.setRenderer(renderer);
      lifecycle.track(resource);
      throw new Error('synthetic scene setup failure');
    } catch {
      lifecycle.fail('setup-error');
    } finally {
      if (!setupComplete) lifecycle.dispose();
    }

    expect(onFallback).toHaveBeenCalledOnce();
    expect(onFallback).toHaveBeenCalledWith('setup-error');
    expect(resource.dispose).toHaveBeenCalledOnce();
    expect(renderer.dispose).toHaveBeenCalledOnce();
    expect(renderer.forceContextLoss).not.toHaveBeenCalled();
    expect(setupComplete).toBe(false);
  });

  it('wires the production child through fail-closed setup and the exact-once lifecycle', () => {
    const childSource = readFileSync(resolve(process.cwd(), 'src/components/site-scroll-world-webgl.tsx'), 'utf8');
    const lifecycleSource = readFileSync(
      resolve(process.cwd(), 'src/components/site-scroll-world-lifecycle.ts'),
      'utf8',
    );

    expect(childSource).toContain('createScrollWorldLifecycle(onFallback)');
    expect(childSource).toMatch(/try \{[\s\S]*new THREE\.WebGLRenderer/);
    expect(childSource).toContain("setupFailureReason = 'setup-error'");
    expect(childSource).toContain('finally {');
    expect(childSource).toContain('if (!setupComplete) lifecycle.dispose()');
    expect(childSource).toContain('const onContextLost = lifecycle.onContextLost');
    expect(lifecycleSource).not.toContain('forceContextLoss()');
  });
});
