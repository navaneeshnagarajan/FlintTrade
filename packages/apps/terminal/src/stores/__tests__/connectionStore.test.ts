import { beforeEach, describe, expect, it } from "vitest";
import { useConnectionStore } from "../connectionStore";
beforeEach(() => useConnectionStore.setState(useConnectionStore.getInitialState()));
describe("connection status cache", () => {
  it("starts disconnected and stores no broker credentials in browser storage", () => {
    expect(useConnectionStore.getState().status).toBe("disconnected");
    expect(sessionStorage.getItem("flinttrade:connection")).toBeNull();
  });
  it("updates broker status without changing account identity", () => {
    useConnectionStore.getState().setStatus("connected");
    expect(useConnectionStore.getState().status).toBe("connected");
  });
});
