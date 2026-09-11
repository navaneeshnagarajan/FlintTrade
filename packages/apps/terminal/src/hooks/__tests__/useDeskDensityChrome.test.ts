import { createElement, type ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { useSettingsStore } from "@/stores/settingsStore";
import { useDeskChromeStore } from "@/stores/deskChromeStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { selectDeskDensity, useDeskDensityChrome } from "../useDeskDensityChrome";

function wrapperFor(path: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(MemoryRouter, { initialEntries: [path] }, children);
  };
}

describe("useDeskDensityChrome", () => {
  afterEach(() => {
    Object.defineProperty(window, "innerWidth", { value: 1024, writable: true });
    useSettingsStore.setState({ density: "comfortable" });
    useDeskChromeStore.setState({ toolsExpanded: false });
  });

  it("marks Compact @ 1280 as progressive and collapses ticker until toggled", () => {
    Object.defineProperty(window, "innerWidth", { value: 1280, writable: true });
    useSettingsStore.setState({ density: "compact" });
    const { result } = renderHook(() => useDeskDensityChrome(), {
      wrapper: wrapperFor("/trade"),
    });

    expect(result.current.progressive).toBe(true);
    expect(result.current.showTicker).toBe(false);
    expect(result.current.showToolRibbon).toBe(false);
    expect(result.current.dockModeFor("expanded")).toBe("icons");

    act(() => {
      result.current.setToolsExpanded(true);
    });
    expect(result.current.showTicker).toBe(true);
    expect(result.current.showToolRibbon).toBe(true);
  });

  it("selecting Compact at 1280 on Trade collapses a beginner-core desk by default", () => {
    Object.defineProperty(window, "innerWidth", { value: 1280, writable: true });
    window.history.replaceState({}, "", "/trade");
    useSettingsStore.setState({ density: "comfortable" });
    useDeskChromeStore.setState({ toolsExpanded: true });

    const beginnerCore = {
      layout: {
        children: [
          { component: "indexstrip" },
          { component: "chart" },
          { component: "positions" },
          { component: "watchlist" },
          { component: "orderpad" },
        ],
      },
    };
    let current = beginnerCore as Record<string, unknown>;
    const previousApi = useLayoutStore.getState().workspaceApi;
    useLayoutStore.setState({
      workspaceApi: {
        addPanel: () => undefined,
        toJSON: () => current,
        loadModelJson: (json: Record<string, unknown>) => {
          current = json;
        },
      } as unknown as ReturnType<typeof useLayoutStore.getState>["workspaceApi"],
    });

    try {
      selectDeskDensity("compact");
      expect(useSettingsStore.getState().density).toBe("compact");
      expect(useDeskChromeStore.getState().toolsExpanded).toBe(false);
      expect(current).toEqual(expect.objectContaining({
        global: expect.any(Object),
      }));
      expect(JSON.stringify(current)).not.toContain('"watchlist"');
      expect(JSON.stringify(current)).not.toContain('"indexstrip"');
      expect(JSON.stringify(current)).toContain('"orderpad"');
    } finally {
      useLayoutStore.setState({ workspaceApi: previousApi });
    }
  });

  it("does not collapse chrome on Compact Home", () => {
    Object.defineProperty(window, "innerWidth", { value: 1280, writable: true });
    useSettingsStore.setState({ density: "compact" });
    const { result } = renderHook(() => useDeskDensityChrome(), {
      wrapper: wrapperFor("/home"),
    });

    expect(result.current.progressive).toBe(false);
    expect(result.current.showTicker).toBe(true);
    expect(result.current.showToolRibbon).toBe(true);
    expect(result.current.dockModeFor("expanded")).toBe("expanded");
  });
});
