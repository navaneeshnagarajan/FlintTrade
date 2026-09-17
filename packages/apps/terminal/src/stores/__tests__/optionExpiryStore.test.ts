import { beforeEach, describe, expect, it } from "vitest";

import { optionExpiryIdentity, useOptionExpiryStore } from "../optionExpiryStore";

describe("optionExpiryStore", () => {
  beforeEach(() => {
    useOptionExpiryStore.setState({ selectedByIdentity: {} });
  });

  it("remembers a selected expiry per symbol/exchange identity", () => {
    const identity = optionExpiryIdentity("explore:mock", "NIFTY", "NFO");
    useOptionExpiryStore.getState().setSelected(identity, "24-SEP-26");
    expect(useOptionExpiryStore.getState().selectedByIdentity[identity]).toBe("24-SEP-26");
  });

  it("clears a selection without touching another identity", () => {
    const nifty = optionExpiryIdentity("explore:mock", "NIFTY", "NFO");
    const bank = optionExpiryIdentity("explore:mock", "BANKNIFTY", "NFO");
    useOptionExpiryStore.getState().setSelected(nifty, "24-SEP-26");
    useOptionExpiryStore.getState().setSelected(bank, "01-OCT-26");
    useOptionExpiryStore.getState().setSelected(nifty, null);
    expect(useOptionExpiryStore.getState().selectedByIdentity[nifty]).toBeUndefined();
    expect(useOptionExpiryStore.getState().selectedByIdentity[bank]).toBe("01-OCT-26");
  });
});
