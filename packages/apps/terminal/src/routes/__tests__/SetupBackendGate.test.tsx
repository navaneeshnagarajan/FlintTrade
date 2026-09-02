import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SetupBackendGate } from "../SetupBackendGate";

function backendStatusResponse(isSetup = false): Response {
  return new Response(
    JSON.stringify({ status: "success", data: { is_setup: isSetup } }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function renderGate(onAdvance = vi.fn()) {
  render(
    <MemoryRouter>
      <SetupBackendGate>
        <div data-testid="setup-flow">
          <label htmlFor="setup-password">Account password</label>
          <input id="setup-password" type="password" />
          <button type="button" onClick={onAdvance}>Advance setup</button>
        </div>
      </SetupBackendGate>
    </MemoryRouter>,
  );
  return onAdvance;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SetupBackendGate", () => {
  it("shows an actionable accessible unavailable state without rendering or submitting setup fields", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    const onAdvance = renderGate();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAccessibleName("FlintTrade backend unavailable");
    expect(alert).toHaveTextContent(/start or restart the local FlintTrade backend/i);
    expect(alert).toHaveTextContent(/setup has not advanced/i);
    expect(alert).toHaveAttribute("aria-live", "assertive");
    await waitFor(() => expect(alert).toHaveFocus());
    expect(screen.getByRole("button", { name: "Retry connection" })).toBeEnabled();
    expect(screen.getByRole("link", { name: "Return to welcome" })).toHaveAttribute("href", "/welcome");

    expect(screen.queryByTestId("setup-flow")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Account password")).not.toBeInTheDocument();
    expect(onAdvance).not.toHaveBeenCalled();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, request] = fetchSpy.mock.calls[0] ?? [];
    expect(request).toMatchObject({ method: "GET", cache: "no-store" });
    expect(request).not.toHaveProperty("body");
    expect(request?.headers).toEqual({ Accept: "application/json" });
  });

  it("rechecks on retry and reveals the same setup flow only after the backend recovers", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(backendStatusResponse());
    const onAdvance = renderGate();

    fireEvent.click(await screen.findByRole("button", { name: "Retry connection" }));

    expect(await screen.findByTestId("setup-flow")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(onAdvance).not.toHaveBeenCalled();
  });

  it("treats an HTTP or malformed status response as unavailable rather than false success", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("service unavailable", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    renderGate();

    expect(await screen.findByRole("alert")).toHaveTextContent(/backend unavailable/i);
    fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("alert")).toHaveTextContent(/backend unavailable/i);
    expect(screen.queryByTestId("setup-flow")).not.toBeInTheDocument();
  });
});
