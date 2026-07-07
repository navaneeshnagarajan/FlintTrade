import { describe, it, expect, beforeEach, vi } from "vitest";
import { useConnectionStore } from "../connectionStore";

describe("connectionStore", () => {
  beforeEach(() => {
    useConnectionStore.setState(useConnectionStore.getInitialState());
    sessionStorage.clear();
  });

  it("initializes with disconnected status", () => {
    const state = useConnectionStore.getState();
    expect(state.status).toBe("disconnected");
    expect(state.wsConnected).toBe(false);
  });

  it("starts without build-time OpenAlgo connection defaults", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_OPENALGO_HOST", "http://192.0.2.10:5000");
    vi.stubEnv("VITE_OPENALGO_WS", "ws://192.0.2.10:8765");
    const { useConnectionStore: freshStore } = await import("../connectionStore");

    const state = freshStore.getInitialState();

    expect(state.host).toBe("");
    expect(state.wsUrl).toBe("");
    vi.unstubAllEnvs();
  });

  it("updates connection status", () => {
    useConnectionStore.getState().setStatus("connected");
    expect(useConnectionStore.getState().status).toBe("connected");
  });

  it("sets API configuration", () => {
    useConnectionStore.getState().setConfig({
      host: "http://localhost:5000",
      apiKey: "test-key",
    });
    const state = useConnectionStore.getState();
    expect(state.host).toBe("http://localhost:5000");
    expect(state.apiKey).toBe("test-key");
    expect(sessionStorage.getItem("flinttrade:connection")).toBeNull();
  });

  it("tracks WebSocket connection state", () => {
    useConnectionStore.getState().setWsConnected(true);
    expect(useConnectionStore.getState().wsConnected).toBe(true);
  });
});
