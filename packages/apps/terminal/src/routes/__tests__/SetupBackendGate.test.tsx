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
        <form data-testid="setup-flow" aria-label="Create operator">
          <label htmlFor="setup-username">Choose a username</label>
          <input id="setup-username" />
          <label htmlFor="setup-password">Account password</label>
          <input id="setup-password" type="password" />
          <button type="button" onClick={onAdvance}>Advance setup</button>
        </form>
      </SetupBackendGate>
    </MemoryRouter>,
  );
  return onAdvance;
}

const BUSY_TITLE = "FlintTrade is busy";
const BUSY_BODY = "FlintTrade is busy right now. Wait a moment, then retry.";
const UNREADABLE_TITLE = "Can't check setup status";
const UNREADABLE_BODY = "FlintTrade answered, but setup status couldn't be read. Retry in a moment.";
const UNAVAILABLE_TITLE = "FlintTrade backend unavailable";
const UNAVAILABLE_BODY = "Start or restart the local FlintTrade backend, then retry. Setup has not advanced and no account, broker, or credential details were submitted from this screen.";

async function expectStatusFailure(title: string, body: string): Promise<HTMLElement> {
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveAccessibleName(title);
  expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  expect(screen.getByText(body)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Retry connection" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Choose a username")).not.toBeInTheDocument();
  expect(screen.queryByTestId("setup-flow")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Account password")).not.toBeInTheDocument();
  return alert;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SetupBackendGate", () => {
  it("shows an actionable accessible unavailable state without rendering or submitting setup fields", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    const onAdvance = renderGate();

    const alert = await expectStatusFailure(UNAVAILABLE_TITLE, UNAVAILABLE_BODY);
    expect(alert).toHaveAttribute("aria-live", "assertive");
    await waitFor(() => expect(alert).toHaveFocus());
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

    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    expect(await screen.findByTestId("setup-flow")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(onAdvance).not.toHaveBeenCalled();
  });

  it.each([
    {
      name: "HTTP 429",
      response: () => new Response(JSON.stringify({ status: "error", message: "rate limit" }), {
        status: 429,
        headers: { "Content-Type": "application/json" },
      }),
      title: BUSY_TITLE,
      body: BUSY_BODY,
    },
    {
      name: "HTTP 500",
      response: () => new Response("service unavailable", { status: 500 }),
      title: UNREADABLE_TITLE,
      body: UNREADABLE_BODY,
    },
    {
      name: "HTTP 404",
      response: () => new Response(JSON.stringify({ status: "error", message: "missing" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
      title: UNREADABLE_TITLE,
      body: UNREADABLE_BODY,
    },
    {
      name: "malformed JSON",
      response: () => new Response("{", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
      title: UNREADABLE_TITLE,
      body: UNREADABLE_BODY,
    },
    {
      name: "a 200 with missing fields",
      response: () => new Response(JSON.stringify({ status: "success", data: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
      title: UNREADABLE_TITLE,
      body: UNREADABLE_BODY,
    },
  ])("shows $name without the fresh-install form", async ({ response, title, body }) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response());
    renderGate();

    const alert = await expectStatusFailure(title, body);
    expect(alert).not.toHaveTextContent(UNAVAILABLE_TITLE);
    expect(screen.queryByText("Setup is busy")).not.toBeInTheDocument();
    expect(screen.queryByText("Setup status could not be read")).not.toBeInTheDocument();
  });

  it("shows a network failure without the fresh-install form", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    renderGate();

    const alert = await expectStatusFailure(UNAVAILABLE_TITLE, UNAVAILABLE_BODY);
    expect(alert).not.toHaveTextContent(BUSY_TITLE);
    expect(alert).not.toHaveTextContent(UNREADABLE_TITLE);
  });
});
