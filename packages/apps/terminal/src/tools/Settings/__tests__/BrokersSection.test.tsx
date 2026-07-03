/**
 * BrokersSection.test.tsx — the native broker connect UI (Phase 1 G4).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.native", () => ({
  listNativeBrokers: vi.fn(),
  listNativeAccounts: vi.fn(),
  connectNativeAccount: vi.fn(),
  oauthStartNativeAccount: vi.fn(),
  removeNativeAccount: vi.fn(),
}));

import {
  listNativeBrokers,
  listNativeAccounts,
  connectNativeAccount,
  oauthStartNativeAccount,
} from "@/services/ftApi.native";
import { BrokersSection } from "../BrokersSection";

const BROKERS = [
  {
    adapter_id: "dhan",
    display_name: "Dhan",
    auth_methods: [
      {
        id: "access_token",
        label: "Access token",
        kind: "direct" as const,
        description: "Paste a token.",
        fields: [
          { name: "client_id", label: "Dhan client ID", secret: false, required: true, help: "" },
          { name: "access_token", label: "Access token", secret: true, required: true, help: "" },
        ],
      },
    ],
  },
  {
    adapter_id: "upstox",
    display_name: "Upstox",
    auth_methods: [
      {
        id: "oauth",
        label: "Log in with Upstox (OAuth)",
        kind: "oauth" as const,
        description: "Approve on upstox.com.",
        fields: [
          { name: "api_key", label: "API key", secret: false, required: true, help: "" },
          { name: "api_secret", label: "API secret", secret: true, required: true, help: "" },
        ],
      },
    ],
  },
];

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrokersSection />
    </QueryClientProvider>,
  );
}

describe("BrokersSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue(BROKERS);
    (listNativeAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  });

  it("shows the section heading and empty connected-accounts state", async () => {
    renderSection();
    expect(screen.getByRole("heading", { name: "Brokers" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/No broker accounts connected/i)).toBeInTheDocument());
  });

  it("connects a direct-credential account (Dhan access token)", async () => {
    (connectNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue({ connected: true, login: "ok" });
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    // Pick Dhan (native select renders options once opened).
    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Dhan" }));

    fireEvent.change(screen.getByLabelText(/account id/i), { target: { value: "1234567890" } });
    fireEvent.change(screen.getByLabelText("Dhan client ID"), { target: { value: "1234567890" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "TOK" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(connectNativeAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          adapter_id: "dhan",
          account_id: "1234567890",
          credentials: { client_id: "1234567890", access_token: "TOK" },
        }),
      ),
    );
  });

  it("launches OAuth for an oauth-method broker (Upstox)", async () => {
    (oauthStartNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue({
      auth_url: "https://api.upstox.com/v2/login/authorization/dialog?client_id=K",
      state: "S",
      redirect_uri: "http://127.0.0.1:5100/api/v1/native/oauth/callback",
    });
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Upstox" }));

    fireEvent.change(screen.getByLabelText(/account id/i), { target: { value: "UPX1" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "K" } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: "SEC" } });
    fireEvent.click(screen.getByRole("button", { name: /log in with upstox/i }));

    await waitFor(() =>
      expect(oauthStartNativeAccount).toHaveBeenCalledWith(
        expect.objectContaining({ adapter_id: "upstox", account_id: "UPX1", api_key: "K", api_secret: "SEC" }),
      ),
    );
    expect(openSpy).toHaveBeenCalledWith(expect.stringContaining("api.upstox.com"), "_blank", "noopener");
  });
});
