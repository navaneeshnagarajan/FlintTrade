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
    expect(screen.getByRole("button", { name: /set pin/i })).toBeDisabled();
    fireEvent.blur(screen.getByLabelText("Confirm new PIN"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not match/i);
    expect(pinSetCalls).toHaveLength(0);
  });

  it("constrains both PIN fields to six digits", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    const newPin = screen.getByLabelText("New 6-digit PIN");
    const confirmPin = screen.getByLabelText("Confirm new PIN");
    expect(newPin).toHaveAttribute("maxLength", "6");
    expect(confirmPin).toHaveAttribute("maxLength", "6");

    fireEvent.change(newPin, { target: { value: "12ab34567" } });
    expect(newPin).toHaveValue("123456");
  });

  it("does not nag a short PIN on every keystroke", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    fireEvent.change(screen.getByLabelText("New 6-digit PIN"), {
      target: { value: "12345" },
    });
    expect(screen.queryByText("PIN must be exactly 6 digits")).not.toBeInTheDocument();
  });

  it("shows an inline 6-digit error when a PIN field blurs with 1–5 digits", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    const newPin = screen.getByLabelText("New 6-digit PIN");
    fireEvent.change(newPin, { target: { value: "12345" } });
    fireEvent.blur(newPin);

    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("PIN must be exactly 6 digits");
    expect(newPin).toHaveAttribute("aria-invalid", "true");
  });

  it("clears the length error as soon as the PIN becomes six digits", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    const newPin = screen.getByLabelText("New 6-digit PIN");
    fireEvent.change(newPin, { target: { value: "12345" } });
    fireEvent.blur(newPin);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "PIN must be exactly 6 digits",
    );

    fireEvent.change(newPin, { target: { value: "123456" } });
    expect(screen.queryByText("PIN must be exactly 6 digits")).not.toBeInTheDocument();
    expect(newPin).not.toHaveAttribute("aria-invalid", "true");
  });

  it("shows a mismatch error when confirm blurs with both fields filled and different", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    fillPinForm("hunter2secret", "123456", "654321");
    fireEvent.blur(screen.getByLabelText("Confirm new PIN"));

    expect(await screen.findByRole("alert")).toHaveTextContent("PINs do not match");
    expect(pinSetCalls).toHaveLength(0);
  });

  it("disables Set PIN until password, both exact 6-digit PINs, and a match are present", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    const button = screen.getByRole("button", { name: /set pin/i });
    expect(button).toBeDisabled();

    fillPinForm("hunter2secret", "12345", "12345");
    expect(button).toBeDisabled();

    fillPinForm("hunter2secret", "123456", "654321");
    expect(button).toBeDisabled();

    fillPinForm("", "123456", "123456");
    expect(button).toBeDisabled();

    fillPinForm("hunter2secret", "123456", "123456");
    expect(button).toBeEnabled();
  });

  it("blocks a 5-digit submit without calling the endpoint", async () => {
    mockFetch({ hasPin: false });
    renderSection();
    await screen.findByText("No PIN set");

    fillPinForm("hunter2secret", "12345", "12345");
    const button = screen.getByRole("button", { name: /set pin/i });
    expect(button).toBeDisabled();
    fireEvent.blur(screen.getByLabelText("New 6-digit PIN"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "PIN must be exactly 6 digits",
    );
    expect(pinSetCalls).toHaveLength(0);
  });

  it("enrols an authenticator from Security after Set up later", async () => {
    const bodies: { url: string; body: unknown }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/auth/status")) {
        return Promise.resolve(
          jsonResponse({
            status: "success",
            data: { is_setup: true, is_locked: false, has_pin: true, totp_enabled: false },
          }),
        );
      }
      if (url.includes("/security/stats")) {
        return Promise.resolve(
          jsonResponse({ status: "success", data: { total_ips: 0, banned_count: 0, top_offenders: [] } }),
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
      if (url.includes("regenerate-2fa") || url.includes("/totp/enable")) {
        bodies.push({ url, body: JSON.parse(String(init?.body ?? "{}")) });
        if (url.includes("regenerate-2fa")) {
          return Promise.resolve(
            jsonResponse({
              status: "success",
              data: {
                totp_uri: "otpauth://totp/FlintTrade:op?secret=ABC234&issuer=FlintTrade",
                backup_codes: ["CODE1234"],
              },
            }),
          );
        }
        return Promise.resolve(jsonResponse({ status: "success", data: { totp_enabled: true } }));
      }
      return Promise.resolve(jsonResponse({ status: "success", data: {} }));
    });

    renderSection();

    expect(await screen.findByText("Not enrolled")).toBeInTheDocument();
    expect(screen.getByTestId("authenticator-enrolment")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Password to enrol authenticator"), {
      target: { value: "hunter2secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /show authenticator qr/i }));

    expect(await screen.findByLabelText("Authenticator QR code")).toBeInTheDocument();
    expect(screen.getByText("CODE1234")).toBeInTheDocument();
    expect(bodies[0]?.body).toEqual({ password: "hunter2secret" });

    fireEvent.change(screen.getByLabelText("Authenticator enrolment code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm enrolment/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Authenticator enrolled. Live can use it once a PIN and a broker are in place.",
    );
    expect(screen.getByText("Authenticator enrolled")).toBeInTheDocument();
    expect(bodies[1]?.body).toEqual({ totp_code: "123456" });
    expect(String(bodies[1]?.url)).toContain("/v1/auth/totp/enable");
  });
});
