/**
 * SecuritySection.test.tsx — the quick-unlock PIN block.
 *
 * Runs against real react-query + the real ftApi fetchers with a
 * URL-dispatching fetch mock, so the endpoint shapes are pinned:
 *   GET  /ft-api/v1/auth/status  → drives the set vs change state
 *   POST /ft-api/v1/auth/pin/set → password + 6-digit PIN, session Bearer JWT
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/authStore";
import { SecuritySection } from "../SecuritySection";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface FetchOptions {
  hasPin?: boolean;
  pinSetResponse?: () => Response;
}

let pinSetCalls: RequestInit[];

function mockFetch({ hasPin = false, pinSetResponse }: FetchOptions = {}) {
  pinSetCalls = [];
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/auth/pin/set")) {
        pinSetCalls.push(init ?? {});
        return Promise.resolve(
          pinSetResponse
            ? pinSetResponse()
            : jsonResponse({ status: "success", data: { has_pin: true } }),
        );
      }
      if (url.endsWith("/v1/auth/status")) {
        return Promise.resolve(
          jsonResponse({
            status: "success",
            data: { is_setup: true, is_locked: false, has_pin: hasPin },
          }),
        );
      }
      if (url.includes("/security/stats")) {
        return Promise.resolve(
          jsonResponse({
            status: "success",
            data: { total_ips: 0, banned_count: 0, top_offenders: [] },
          }),
        );
      }
      if (url.includes("/security/bans")) {
        return Promise.resolve(jsonResponse({ status: "success", data: { bans: [] } }));
      }
      if (url.includes("/security/settings")) {
        return Promise.resolve(
          jsonResponse({
            status: "success",
            data: {
              auto_ban_enabled: false,
              ban_threshold: 25,
              notfound_ban_threshold: 10,
              ban_duration: 24,
            },
          }),
        );
      }
      return Promise.resolve(jsonResponse({ status: "success", data: {} }));
    });
}

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SecuritySection />
    </QueryClientProvider>,
  );
}

function fillPinForm(password: string, pin: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("Account password"), {
    target: { value: password },
  });
  fireEvent.change(screen.getByLabelText("New 6-digit PIN"), {
    target: { value: pin },
  });
  fireEvent.change(screen.getByLabelText("Confirm new PIN"), {
    target: { value: confirm },
  });
}

describe("SecuritySection — quick-unlock PIN", () => {
  beforeEach(() => {
    // A real (non-demo) session token: the ftApi helpers attach it as the
    // Authorization Bearer header and skip the demo short-circuits.
    useAuthStore.setState({ token: "test-session-jwt" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the SET state when no PIN exists", async () => {
    mockFetch({ hasPin: false });
    renderSection();

    expect(await screen.findByText("No PIN set")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set pin/i })).toBeInTheDocument();
    expect(screen.getByText(/live mode cannot be armed/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /change pin/i })).not.toBeInTheDocument();
  });

  it("renders the CHANGE state when a PIN is already set", async () => {
    mockFetch({ hasPin: true });
    renderSection();

    expect(await screen.findByText("PIN set")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /change pin/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^set pin$/i })).not.toBeInTheDocument();
  });

  it("submits password + PIN to /ft-api/v1/auth/pin/set with the session Bearer token", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    fillPinForm("hunter2secret", "123456", "123456");
    fireEvent.click(screen.getByRole("button", { name: /set pin/i }));

    await waitFor(() => expect(pinSetCalls).toHaveLength(1));
    const init = pinSetCalls[0] ?? {};
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      password: "hunter2secret",
      pin: "123456",
    });
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer test-session-jwt");
    // Success feedback + fields cleared.
    expect(await screen.findByRole("status")).toHaveTextContent(/pin set/i);
    expect(screen.getByLabelText("Account password")).toHaveValue("");
  });

  it("surfaces the server error message on failure", async () => {
    mockFetch({
      hasPin: false,
      pinSetResponse: () =>
        jsonResponse({ status: "error", message: "Invalid password." }, 401),
    });
    renderSection();
    await screen.findByText("No PIN set");

    fillPinForm("wrong-password", "123456", "123456");
    fireEvent.click(screen.getByRole("button", { name: /set pin/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid password.");
    expect(pinSetCalls).toHaveLength(1);
  });

  it("validates locally (mismatched confirm) without calling the endpoint", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    fillPinForm("hunter2secret", "123456", "654321");
    fireEvent.click(screen.getByRole("button", { name: /set pin/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not match/i);
    expect(pinSetCalls).toHaveLength(0);
  });
});
