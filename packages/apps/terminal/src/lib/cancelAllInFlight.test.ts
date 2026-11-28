import { describe, expect, it } from "vitest";
import { isCancelAllInFlight, sendCancelAllOnce } from "@/lib/cancelAllInFlight";

describe("cancel-all in-flight flag", () => {
  it("sends one request at a time and releases on success", async () => {
    let release!: (value: string) => void;
    const send = () => new Promise<string>((resolve) => { release = resolve; });
    const first = sendCancelAllOnce(send);

    expect(isCancelAllInFlight()).toBe(true);
    expect(sendCancelAllOnce(send)).toBeNull();
    release("done");
    await expect(first).resolves.toBe("done");
    expect(isCancelAllInFlight()).toBe(false);
  });

  it("releases when the request rejects", async () => {
    await expect(sendCancelAllOnce(() => Promise.reject(new Error("Gateway Timeout")))).rejects.toThrow("Gateway Timeout");
    expect(isCancelAllInFlight()).toBe(false);
  });

  it("releases when sending throws", async () => {
    await expect(sendCancelAllOnce(() => { throw new Error("offline"); })).rejects.toThrow("offline");
    expect(isCancelAllInFlight()).toBe(false);
  });
});
