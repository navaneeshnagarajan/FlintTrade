import { describe, it, expect, beforeEach } from "vitest";
import { useConnectionStore } from "../connectionStore";

describe("connectionStore", () => {
  beforeEach(() => {
    useConnectionStore.setState(useConnectionStore.getInitialState());
  });

  it("initializes with disconnected status", () => {
    const state = useConnectionStore.getState();
    expect(state.status).toBe("disconnected");
    expect(state.wsConnected).toBe(false);
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
  });

  it("tracks WebSocket connection state", () => {
    useConnectionStore.getState().setWsConnected(true);
    expect(useConnectionStore.getState().wsConnected).toBe(true);
  });
});
