import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

import ModeSelectRoute from "../ModeSelectRoute";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ModeSelectRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  function clickLiveMode() {
    const liveLabel = screen.getByText("Live");
    const liveButton = liveLabel.closest("button");
    expect(liveButton).not.toBeNull();
    fireEvent.click(liveButton as HTMLButtonElement);
  }

  it("verifies the Live PIN and passes the live-unlocked session token upward", async () => {
    const onSelect = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { token: "live-unlocked-jwt", live_mode_unlocked: true },
      }),
    );

    render(<ModeSelectRoute onSelect={onSelect} />);

    clickLiveMode();
    fireEvent.change(screen.getByLabelText(/enter your 6-digit pin to enable live mode/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /continue with live/i }));

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("live", "live-unlocked-jwt"));
    // Routed through unlockWithPin, which always sends the explicit live mode.
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/ft-api/v1/auth/pin",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ pin: "123456", mode: "live" }),
      }),
    );
  });

  it("keeps the user on the mode step if Live PIN verification returns no token", async () => {
    const onSelect = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ status: "success", data: {} }),
    );

    render(<ModeSelectRoute onSelect={onSelect} />);

    clickLiveMode();
    fireEvent.change(screen.getByLabelText(/enter your 6-digit pin to enable live mode/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /continue with live/i }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce());
    expect(onSelect).not.toHaveBeenCalled();
    // unlockWithPin throws on a missing token; the route surfaces the generic
    // PIN error rather than proceeding.
    expect(screen.getByText(/incorrect pin/i)).toBeInTheDocument();
  });
});
