/**
 * ModeIndicator — Mode menu, disabled reasons, and the Live PIN gate.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import ModeIndicator from "../ModeIndicator";

function resetStore(mode: "explore" | "practice" | "live" = "explore") {
  useModeStore.setState({ mode });
  useAuthStore.setState({
    status: "logged-in",
    token: "initial-jwt-token",
    reauthToken: null,
    username: "testuser",
    sessionGeneration: 0,
  });
  useBrokerStore.setState({ accounts: [], activeAccountId: null });
  useConnectionStore.setState({ status: "disconnected" });
}

function connectBroker() {
  useBrokerStore.setState({
    accounts: [{
      account_id: "acc-1",
      broker: "dhan",
      label: "Dhan",
      status: "connected",
      connected_at: null,
      error_message: null,
      is_primary: true,
      source: "native",
    }],
    activeAccountId: null,
  });
}

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function statusResponse(totpEnabled: boolean): Response {
  return jsonResponse({
    status: "success",
    data: { is_setup: true, is_locked: false, has_pin: true, totp_enabled: totpEnabled },
  });
}

async function openMenu() {
  const user = userEvent.setup();
  await user.click(screen.getByTestId("execution-mode"));
  return user;
}

describe("ModeIndicator", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  describe("mode menu", () => {
    it("names Example on the chip for sample data and does not say Practice", () => {
      resetStore("explore");
      render(<ModeIndicator />);

      const chip = screen.getByTestId("execution-mode");
      expect(chip).toHaveTextContent("Example");
      expect(chip).not.toHaveTextContent("Practice");
      expect(chip).not.toHaveTextContent(/explore/i);
    });

    it("names Practice on the chip and does not say Explore", () => {
      resetStore("practice");
      render(<ModeIndicator />);

      const chip = screen.getByTestId("execution-mode");
      expect(chip).toHaveTextContent("Practice");
      expect(chip).not.toHaveTextContent(/explore/i);
      expect(screen.queryByText("EXPLORE")).not.toBeInTheDocument();
    });

    it("opens Practice, Connected (read), and Live without the Live dialog", async () => {
      resetStore("practice");
      render(<ModeIndicator />);

      await openMenu();

      expect(screen.getByRole("menuitem", { name: "Practice" })).toBeInTheDocument();
      expect(screen.getByRole("menuitem", { name: /Connected \(read\)/ })).toHaveTextContent(
        "Connect a broker first",
      );
      expect(screen.getByRole("menuitem", { name: /Live/ })).toHaveTextContent(
        "Enrol 2FA and connect a broker",
      );
      expect(screen.queryByText("Not qualified for Live")).not.toBeInTheDocument();
      expect(screen.queryByText("Switch to Live Trading?")).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/authenticator/i)).not.toBeInTheDocument();
    });

    it("keeps Live disabled, so a click cannot ask for an authenticator code", async () => {
      resetStore("practice");
      render(<ModeIndicator />);
      await openMenu();

      fireEvent.click(screen.getByRole("menuitem", { name: /Enrol 2FA and connect a broker/ }));

      expect(screen.queryByText("Switch to Live Trading?")).not.toBeInTheDocument();
      expect(screen.queryByPlaceholderText("6-digit PIN")).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/authenticator/i)).not.toBeInTheDocument();
    });

    it("enables Connected (read) once a broker is connected and still skips Live", async () => {
      resetStore("practice");
      connectBroker();
      render(<ModeIndicator />);
      const user = await openMenu();

      const connected = screen.getByRole("menuitem", { name: "Connected (read)" });
      expect(connected).not.toHaveTextContent("Connect a broker first");
      expect(screen.getByRole("menuitem", { name: /Live/ })).toHaveTextContent(
        "Enrol 2FA and connect a broker",
      );

      await user.click(connected);

      expect(screen.getByTestId("execution-mode")).toHaveTextContent("Connected (read)");
      expect(screen.queryByText("Switch to Live Trading?")).not.toBeInTheDocument();
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("lists Not qualified for Live beside the 2FA and broker reason", async () => {
      resetStore("practice");
      render(<ModeIndicator layaQualifiedForLive={false} />);
      await openMenu();

      const reasons = screen.getByTestId("live-lock-reasons");
      expect(reasons).toHaveTextContent("Enrol 2FA and connect a broker");
      expect(reasons).toHaveTextContent("Not qualified for Live");
      fireEvent.click(screen.getByRole("menuitem", { name: /Not qualified for Live/ }));

      expect(screen.queryByText("Switch to Live Trading?")).not.toBeInTheDocument();
      expect(screen.queryByPlaceholderText("6-digit PIN")).not.toBeInTheDocument();
    });

    it("keeps Live locked on qualification alone, with no PIN dialog", async () => {
      resetStore("practice");
      connectBroker();
      vi.spyOn(globalThis, "fetch").mockImplementation(async () => statusResponse(true));
      render(<ModeIndicator layaQualifiedForLive={false} />);
      await openMenu();

      await waitFor(() => {
        expect(screen.getByTestId("live-lock-reasons")).toHaveTextContent("Not qualified for Live");
      });
      expect(screen.getByTestId("live-lock-reasons")).not.toHaveTextContent(
        "Enrol 2FA and connect a broker",
      );
      expect(screen.getByRole("menuitem", { name: /Not qualified for Live/ })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
      fireEvent.click(screen.getByRole("menuitem", { name: /Not qualified for Live/ }));

      expect(screen.queryByText("Switch to Live Trading?")).not.toBeInTheDocument();
    });
  });

  describe("sample session", () => {
    it("switches to Practice from the menu and stores the Practice JWT", async () => {
      resetStore("explore");
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(false);
        return jsonResponse({ status: "success", data: { token: "practice-jwt", mode: "practice" } });
      });

      render(<ModeIndicator />);
      const user = await openMenu();
      await user.click(screen.getByRole("menuitem", { name: "Practice" }));

      await waitFor(() => expect(useModeStore.getState().mode).toBe("practice"));
      expect(fetchSpy).toHaveBeenCalledWith(
        "/ft-api/v1/auth/mode",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ mode: "practice" }) }),
      );
      expect(useAuthStore.getState().token).toBe("practice-jwt");
    });

    it("stays put if the Practice JWT sync fails", async () => {
      resetStore("explore");
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(false);
        return jsonResponse({}, 503);
      });

      render(<ModeIndicator />);
      const user = await openMenu();
      await user.click(screen.getByRole("menuitem", { name: "Practice" }));

      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
      expect(useModeStore.getState().mode).toBe("explore");
    });

    it("routes demo users to account setup instead of switching mode", async () => {
      resetStore("explore");
      useAuthStore.setState({ token: "demo-user" });
      const listener = vi.fn();
      window.addEventListener("flinttrade:navigate", listener);
      render(<ModeIndicator />);

      const user = await openMenu();
      await user.click(screen.getByRole("menuitem", { name: "Practice" }));

      expect(useModeStore.getState().mode).toBe("explore");
      expect(listener).toHaveBeenCalledTimes(1);
      const event = listener.mock.calls[0]?.[0] as CustomEvent<{ path?: string }>;
      expect(event.detail.path).toBe("/setup");
      window.removeEventListener("flinttrade:navigate", listener);
    });
  });

  describe("eligible Live unlock", () => {
    function armLive() {
      resetStore("practice");
      connectBroker();
    }

    async function chooseLive() {
      const user = await openMenu();
      await waitFor(() => {
        expect(screen.getByRole("menuitem", { name: "Live" })).toBeEnabled();
      });
      await user.click(screen.getByRole("menuitem", { name: "Live" }));
    }

    it("opens the PIN dialog only after Live is chosen, with no authenticator field", async () => {
      armLive();
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(true);
        return jsonResponse({ status: "success", data: { token: "unused" } });
      });
      render(<ModeIndicator />);

      expect(screen.queryByText("Switch to Live Trading?")).not.toBeInTheDocument();
      await chooseLive();

      expect(screen.getByText("Switch to Live Trading?")).toBeInTheDocument();
      expect(screen.getByPlaceholderText("6-digit PIN")).toBeInTheDocument();
      expect(screen.queryByLabelText(/authenticator/i)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /switch to live/i })).toBeDisabled();
    });

    it("switches to live after a successful PIN and stores the live JWT", async () => {
      armLive();
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(true);
        return jsonResponse({
          status: "success",
          data: { token: "live-unlocked-jwt", live_mode_unlocked: true },
        });
      });
      render(<ModeIndicator />);
      await chooseLive();

      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), { target: { value: "123456" } });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));

      await waitFor(() => expect(useModeStore.getState().mode).toBe("live"));
      expect(useAuthStore.getState().token).toBe("live-unlocked-jwt");
    });

    it("ignores a PIN response that arrives after the session locks", async () => {
      armLive();
      let finishRequest: ((response: Response) => void) | undefined;
      vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return Promise.resolve(statusResponse(true));
        return new Promise<Response>((resolve) => {
          finishRequest = resolve;
        });
      });
      render(<ModeIndicator />);
      await chooseLive();
      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), { target: { value: "123456" } });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));
      await waitFor(() => expect(finishRequest).toBeTypeOf("function"));

      act(() => useAuthStore.getState().setPinRequired());
      await act(async () => {
        finishRequest?.(jsonResponse({
          status: "success",
          data: { token: "late-live-token", mode: "live", live_mode_unlocked: true },
        }));
        await Promise.resolve();
      });

      expect(useAuthStore.getState()).toMatchObject({
        status: "pin-required",
        token: null,
        username: "testuser",
      });
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("rejects a PIN response that returned no token", async () => {
      armLive();
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(true);
        return jsonResponse({ status: "success", data: {} });
      });
      render(<ModeIndicator />);
      await chooseLive();
      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), { target: { value: "123456" } });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));

      await waitFor(() => expect(useModeStore.getState().mode).toBe("practice"));
      expect(useAuthStore.getState().token).toBe("initial-jwt-token");
    });

    it("does not switch to live on an incorrect PIN", async () => {
      armLive();
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(true);
        return new Response(null, { status: 401 });
      });
      render(<ModeIndicator />);
      await chooseLive();
      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), { target: { value: "000000" } });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));

      await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("surfaces the server PIN message", async () => {
      const serverMessage = "No PIN is set for this account. Create one in Settings → Security, then retry.";
      armLive();
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(true);
        return jsonResponse({ status: "error", code: "pin_not_set", message: serverMessage }, 409);
      });
      render(<ModeIndicator />);
      await chooseLive();
      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), { target: { value: "123456" } });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));

      expect(await screen.findByText(serverMessage)).toBeInTheDocument();
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("falls back when the PIN request carries no message", async () => {
      armLive();
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(true);
        throw "boom";
      });
      render(<ModeIndicator />);
      await chooseLive();
      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), { target: { value: "123456" } });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));

      expect(await screen.findByText("Incorrect PIN. Try again.")).toBeInTheDocument();
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("closes the dialog on cancel without changing mode", async () => {
      armLive();
      vi.spyOn(globalThis, "fetch").mockImplementation(async () => statusResponse(true));
      render(<ModeIndicator />);
      await chooseLive();
      fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

      expect(useModeStore.getState().mode).toBe("practice");
      expect(screen.queryByText("Switch to Live Trading?")).not.toBeInTheDocument();
    });
  });

  describe("live mode", () => {
    it("renders Live and downgrades through the Practice item", async () => {
      resetStore("live");
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(true);
        return jsonResponse({
          status: "success",
          data: { token: "fresh-practice-jwt", mode: "practice", live_mode_unlocked: false },
        });
      });
      useAuthStore.setState({ token: "stale-live-jwt" });
      render(<ModeIndicator />);

      expect(screen.getByTestId("execution-mode")).toHaveTextContent("Live");
      const user = await openMenu();
      await user.click(screen.getByRole("menuitem", { name: "Practice" }));

      await waitFor(() => expect(useModeStore.getState().mode).toBe("practice"));
      expect(useAuthStore.getState().token).toBe("fresh-practice-jwt");
      const modeCall = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.find(
        (call) => String(call[0]).includes("/v1/auth/mode"),
      );
      expect(modeCall).toBeTruthy();
      const init = modeCall?.[1] as RequestInit;
      expect(init.method).toBe("POST");
      expect((init.headers as Record<string, string>).Authorization).toBe("Bearer stale-live-jwt");
      expect(JSON.parse(init.body as string)).toEqual({ mode: "practice" });
      expect(screen.queryByText("Switch to Live Trading?")).not.toBeInTheDocument();
    });

    it("ignores a mode response that arrives after logout", async () => {
      resetStore("live");
      useAuthStore.setState({ token: "stale-live-jwt" });
      let finishRequest: ((response: Response) => void) | undefined;
      vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return Promise.resolve(statusResponse(false));
        return new Promise<Response>((resolve) => {
          finishRequest = resolve;
        });
      });
      render(<ModeIndicator />);
      const user = await openMenu();
      await user.click(screen.getByRole("menuitem", { name: "Practice" }));
      await waitFor(() => expect(finishRequest).toBeTypeOf("function"));

      act(() => useAuthStore.getState().setLoggedOut());
      await act(async () => {
        finishRequest?.(jsonResponse({
          status: "success",
          data: { token: "late-practice-token", mode: "practice" },
        }));
        await Promise.resolve();
      });

      expect(useAuthStore.getState()).toMatchObject({
        status: "logged-out",
        token: null,
        username: null,
      });
      expect(useModeStore.getState().mode).toBe("live");
    });

    it("does not flip to Practice if the mode switch fails", async () => {
      resetStore("live");
      useAuthStore.setState({ token: "stale-live-jwt" });
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/v1/auth/status")) return statusResponse(false);
        return new Response("", { status: 500 });
      });
      render(<ModeIndicator />);
      const user = await openMenu();
      await user.click(screen.getByRole("menuitem", { name: "Practice" }));

      expect(await screen.findByRole("alert")).toBeInTheDocument();
      expect(useModeStore.getState().mode).toBe("live");
      expect(useAuthStore.getState().token).toBe("stale-live-jwt");
    });
  });
});
