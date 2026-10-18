import { describe, expect, it, vi } from "vitest";
import { createPreviewFetch, previewSnapshotTime } from "../publicPreview";

describe("anonymous frozen preview", () => {
  it("allows only same-origin build assets and rejects provider/API writes before transport", async () => {
    const transport = vi.fn().mockResolvedValue(new Response("asset"));
    const fetch = createPreviewFetch(transport, "https://preview.invalid");
    for (const url of ["https://provider.invalid/chat", "/api/v1/advisor/status", "/ft-api/v1/auth/status", "/v1/auth/setup"]) {
      await expect(fetch(url)).rejects.toThrow(/frozen preview/);
    }
    await expect(fetch("/demo-app/assets/data.json", { method: "POST" })).rejects.toThrow();
    expect(transport).not.toHaveBeenCalled();
    await fetch("/demo-app/assets/app.js");
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it("keeps snapshot time independent of the browser clock and rejects malformed build values", () => {
    expect(previewSnapshotTime("2026-10-07T13:46:34-07:00")).toBe(Date.parse("2026-10-07T20:46:34Z"));
    expect(() => previewSnapshotTime("today")).toThrow();
  });
});
