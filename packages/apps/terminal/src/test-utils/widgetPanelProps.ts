/**
 * Typed helper for widget panel props in tests.
 *
 * Widgets receive the FlintTrade-owned `WidgetProps` contract
 * (`types/widgets.ts`): panel `params` plus a narrow panel `api`. Tests that
 * render a widget in isolation get a minimal, strictly-typed stub so test
 * files can drop `{} as any` casts. Use like:
 *
 * ```tsx
 * render(<PositionsWidget {...makeWidgetPanelProps()} />);
 * ```
 *
 * The default `api.updateParameters` records calls on the returned props
 * object (`props.updateParametersCalls`) so tests can assert view-state
 * persistence without wiring their own mock.
 */

import type { WidgetPanelApi, WidgetProps } from "@/types/widgets";

export interface TestWidgetProps extends WidgetProps {
  /** Params objects passed to `api.updateParameters`, in call order. */
  updateParametersCalls: Array<Record<string, unknown>>;
}

export function makeWidgetPanelProps<
  TParams extends Record<string, unknown> = Record<string, never>,
>(overrides?: { params?: TParams; api?: WidgetPanelApi }): TestWidgetProps {
  const updateParametersCalls: Array<Record<string, unknown>> = [];
  const api: WidgetPanelApi = overrides?.api ?? {
    id: "test-panel",
    updateParameters: (params) => {
      updateParametersCalls.push(params);
    },
  };
  return {
    params: overrides?.params ?? ({} as TParams),
    api,
    updateParametersCalls,
  };
}
