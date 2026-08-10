import type { ScrollWorldFailureReason } from './site-scroll-world';

export interface DisposableResource {
  dispose: () => void;
}

export interface DisposableRenderer extends DisposableResource {
  forceContextLoss: () => void;
}

export interface ScrollWorldLifecycle {
  setRenderer: (renderer: DisposableRenderer) => void;
  track: <T extends DisposableResource>(resource: T) => T;
  addCleanup: (cleanup: () => void) => void;
  fail: (reason: ScrollWorldFailureReason) => void;
  onContextLost: (event: Event) => void;
  dispose: () => void;
  isDisposed: () => boolean;
}

function safely(run: () => void): void {
  try {
    run();
  } catch {
    // Teardown is fail-closed: one broken disposer must not strand later resources.
  }
}

export function createScrollWorldLifecycle(
  onFallback: (reason: ScrollWorldFailureReason) => void,
): ScrollWorldLifecycle {
  const resources = new Set<DisposableResource>();
  const cleanups: Array<() => void> = [];
  let renderer: DisposableRenderer | null = null;
  let disposed = false;
  let failureReported = false;

  const dispose = () => {
    if (disposed) return;
    disposed = true;

    for (let index = cleanups.length - 1; index >= 0; index -= 1) safely(cleanups[index]);
    cleanups.length = 0;
    for (const resource of resources) safely(() => resource.dispose());
    resources.clear();
    if (renderer) {
      safely(() => renderer?.dispose());
      safely(() => renderer?.forceContextLoss());
      renderer = null;
    }
  };

  const fail = (reason: ScrollWorldFailureReason) => {
    if (failureReported || disposed) return;
    failureReported = true;
    dispose();
    onFallback(reason);
  };

  return {
    setRenderer(nextRenderer) {
      if (disposed) {
        safely(() => nextRenderer.dispose());
        safely(() => nextRenderer.forceContextLoss());
        return;
      }
      renderer = nextRenderer;
    },
    track<T extends DisposableResource>(resource: T): T {
      if (disposed) safely(() => resource.dispose());
      else resources.add(resource);
      return resource;
    },
    addCleanup(cleanup) {
      if (disposed) safely(cleanup);
      else cleanups.push(cleanup);
    },
    fail,
    onContextLost(event) {
      event.preventDefault();
      fail('context-lost');
    },
    dispose,
    isDisposed: () => disposed,
  };
}
