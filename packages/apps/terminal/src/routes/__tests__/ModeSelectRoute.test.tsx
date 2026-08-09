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

  it("does not claim Practice needs a broker — it is the broker-free native sandbox", () => {
    render(<ModeSelectRoute onSelect={vi.fn()} />);

    const practiceButton = screen.getByText("Practice").closest("button") as HTMLButtonElement;
    expect(practiceButton).not.toBeNull();
    expect(practiceButton).toHaveTextContent(/no broker needed/i);
    expect(practiceButton).not.toHaveTextContent(/broker required/i);

    // Live genuinely requires a broker + PIN — that copy must stay.
    const liveButton = screen.getByText("Live").closest("button") as HTMLButtonElement;
    expect(liveButton).toHaveTextContent(/broker required/i);
  });

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
    // unlockWithPin throws on a missing token; the route now surfaces the
    // ACTUAL reason (audit fix — the old blanket "Incorrect PIN" mislabelled a
    // missing/expired session).
    expect(screen.getByText(/no token/i)).toBeInTheDocument();
  });

  it("marks a valid requested mode as selected without submitting it", () => {
    const onSelect = vi.fn();

    render(<ModeSelectRoute initialMode="practice" onSelect={onSelect} />);

    expect(screen.getByRole("radio", { name: /Practice/i })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: /Explore/i })).toHaveAttribute("aria-checked", "false");
    expect(onSelect).not.toHaveBeenCalled();
  });
});
