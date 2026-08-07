import { describe, it, expect, beforeEach } from "vitest";
import { useLayoutStore } from "../layoutStore";

describe("layoutStore", () => {
  beforeEach(() => {
    useLayoutStore.setState(useLayoutStore.getInitialState());
  });

  it("initializes with one default tab", () => {
    const state = useLayoutStore.getState();
    expect(state.tabs.length).toBeGreaterThanOrEqual(1);
    expect(state.activeTabId).toBeTruthy();
  });

  it("adds a new tab", () => {
    const before = useLayoutStore.getState().tabs.length;
    useLayoutStore.getState().addTab("Test Layout");
    expect(useLayoutStore.getState().tabs.length).toBe(before + 1);
  });

  it("switches active tab", () => {
    useLayoutStore.getState().addTab("Second");
    const tabs = useLayoutStore.getState().tabs;
    const secondId = tabs[tabs.length - 1].id;
    useLayoutStore.getState().setActiveTab(secondId);
    expect(useLayoutStore.getState().activeTabId).toBe(secondId);
  });

  it("does not activate an ID that has no persisted layout tab", () => {
    const originalId = useLayoutStore.getState().activeTabId;

    useLayoutStore.getState().setActiveTab("ws-missing");

    expect(useLayoutStore.getState().activeTabId).toBe(originalId);
  });

  it("renames a tab", () => {
    const tabId = useLayoutStore.getState().tabs[0].id;
    useLayoutStore.getState().renameTab(tabId, "Renamed");
    const tab = useLayoutStore.getState().tabs.find((t) => t.id === tabId);
    expect(tab?.name).toBe("Renamed");
  });
});
