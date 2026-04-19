/**
 * Typed helper for Dockview panel props in tests.
 *
 * Dockview widgets receive an `IDockviewPanelProps` object whose real
 * implementation is a large class from the dockview library. Tests that
 * render a widget in isolation only need a handful of fields, but Zustand
 * stores and hooks inside the widget will complain if the prop shape is
 * wrong.
 *
 * `makeDockviewPanelProps` returns a minimal, strictly-typed stub so test
 * files can drop `{} as any` casts. Use like:
 *
 * ```tsx
 * render(<PositionsWidget {...makeDockviewPanelProps()} />);
 * ```
 */

import type { IDockviewPanelProps } from "dockview";

export function makeDockviewPanelProps<
  TParams extends Record<string, unknown> = Record<string, never>,
>(overrides?: Partial<IDockviewPanelProps<TParams>>): IDockviewPanelProps<TParams> {
  const noop = (): void => {
    /* no-op */
  };
  // Most widget tests never call through to the real Dockview machinery;
  // the handful of fields accessed are `params`, `api`, `containerApi`.
  // Everything else is provided as a minimal stub that throws if used —
  // loud failure is better than silent success during test writing.
  const stub = new Proxy(
    {},
    {
      get(_target, prop) {
        if (prop === "then") return undefined; // keep Promise.resolve happy
        return noop;
      },
    },
  );

  return {
    params: {} as TParams,
    api: stub as IDockviewPanelProps<TParams>["api"],
    containerApi: stub as IDockviewPanelProps<TParams>["containerApi"],
    ...overrides,
  } as IDockviewPanelProps<TParams>;
}
