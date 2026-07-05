/**
 * BrokersSection.test.tsx — the native broker connect UI (Phase 1 G4).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.native", () => ({
  listNativeBrokers: vi.fn(),
  listBrokerMcpCatalogue: vi.fn(),
  listNativeAccounts: vi.fn(),
  connectNativeAccount: vi.fn(),
  oauthStartNativeAccount: vi.fn(),
  removeNativeAccount: vi.fn(),
  setPrimaryNativeAccount: vi.fn(),
  reloginNativeAccount: vi.fn(),
}));

import {
  listNativeBrokers,
  listBrokerMcpCatalogue,
  listNativeAccounts,
  connectNativeAccount,
  oauthStartNativeAccount,
  removeNativeAccount,
  setPrimaryNativeAccount,
  reloginNativeAccount,
} from "@/services/ftApi.native";
import { BrokersSection } from "../BrokersSection";

const BROKERS = [
  {
    adapter_id: "dhan",
    display_name: "Dhan",
    connectable: true,
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
    connectable: true,
    oauth_redirect_uri: "http://127.0.0.1:5100/api/v1/native/oauth/callback",
    postback_uri: "http://127.0.0.1:5100/api/v1/native/postbacks/upstox",
    auth_methods: [
      {
        id: "oauth",
        label: "Log in with Upstox (OAuth)",
        kind: "oauth" as const,
        description: (
          "Approve on upstox.com. Add your outbound public IP under Primary/Secondary IP before using order APIs; " +
          "changing those IPs invalidates Upstox access tokens. Leave Notifier blank."
        ),
        fields: [
          { name: "api_key", label: "API key", secret: false, required: true, help: "" },
          { name: "api_secret", label: "API secret", secret: true, required: true, help: "" },
        ],
      },
    ],
  },
  {
    adapter_id: "kotakneo",
    display_name: "Kotak Neo",
    connectable: false,
    auth_methods: [
      {
        id: "totp_mpin",
        label: "TOTP + MPIN",
        kind: "direct" as const,
        description: "Kotak NEO two-step 2FA.",
        fields: [
          { name: "consumer_key", label: "Consumer key", secret: true, required: true, help: "" },
          { name: "mobile_number", label: "Mobile number", secret: false, required: true, help: "" },
          { name: "ucc", label: "UCC", secret: false, required: true, help: "" },
          { name: "totp", label: "TOTP", secret: false, required: true, help: "" },
          { name: "mpin", label: "MPIN", secret: true, required: true, help: "" },
          { name: "access_token", label: "Portal access token", secret: true, required: false, help: "" },
        ],
      },
    ],
  },
  {
    adapter_id: "indmoney",
    display_name: "INDmoney",
    connectable: true,
    auth_methods: [
      {
        id: "access_token",
        label: "Access token",
        kind: "direct" as const,
        description: (
          "Generate an access token on the INDstocks API dashboard and paste it here. Save your static " +
          "outbound IP before live algo orders; INDstocks resets tokens daily at 06:00 IST and allows " +
          "up to five active tokens."
        ),
        fields: [
          { name: "user_id", label: "User ID", secret: false, required: false, help: "" },
          {
            name: "access_token",
            label: "Access token",
            secret: true,
            required: true,
            help: "Generate a fresh INDstocks token after the daily 06:00 IST reset.",
          },
        ],
      },
    ],
  },
];

const MCP_BROKERS = [
  {
    adapter_id: "dhan",
    display_name: "Dhan",
    native: true,
    connectable: true,
    mcp: {
      remote_url: "https://mcp.dhan.co/mcp",
      docs_url: "https://docs.dhanhq.co/mcp/",
      auth_mode: "Authorize through Dhan's hosted MCP flow from the client.",
      reauth: "Re-authorize when Dhan prompts.",
      read_only: false,
      trading_supported: true,
      login_steps: ["Add the Dhan remote MCP URL to a supported MCP client."],
      use_cases: ["Portfolio and account review", "Super Orders"],
      cautions: ["Broker MCP trade tools are outside FlintTrade's in-process safety gate."],
      client_configs: [
        { id: "remote_url", label: "Direct remote URL", url: "https://mcp.dhan.co/mcp" },
        {
          id: "mcp_remote",
          label: "mcp-remote",
          command: "npx",
          args: ["mcp-remote", "https://mcp.dhan.co/mcp"],
          config: {
            mcpServers: {
              dhan: { command: "npx", args: ["mcp-remote", "https://mcp.dhan.co/mcp"] },
            },
          },
        },
      ],
    },
  },
  {
    adapter_id: "upstox",
    display_name: "Upstox",
    native: true,
    connectable: true,
    mcp: {
      remote_url: "https://mcp.upstox.com/mcp",
      docs_url: "https://upstox.com/developer/api-documentation/mcp-integration/",
      auth_mode: "Authorize through Upstox's hosted MCP flow from the client.",
      reauth: "Daily re-authorisation is required.",
      read_only: true,
      trading_supported: false,
      daily_reauthorization: true,
      login_steps: ["Repeat authorisation daily before relying on account context."],
      use_cases: ["Holdings review", "Orders, positions, funds, mutual funds, and profile lookup"],
      cautions: ["Upstox MCP cannot place, modify, or cancel orders."],
      client_configs: [
        {
          id: "mcp_remote",
          label: "mcp-remote",
          command: "npx",
          args: ["mcp-remote", "https://mcp.upstox.com/mcp"],
          config: {
            mcpServers: {
              upstox: { command: "npx", args: ["mcp-remote", "https://mcp.upstox.com/mcp"] },
            },
          },
        },
      ],
    },
  },
  {
    adapter_id: "groww",
    display_name: "Groww",
    native: true,
    connectable: false,
    mcp: {
      remote_url: "https://mcp.groww.in/mcp",
      docs_url: "https://groww.in/updates/groww-mcp",
      auth_mode: "Authorize through Groww's hosted MCP flow from the client.",
      reauth: "Grant access when the MCP client asks.",
      read_only: false,
      trading_supported: true,
      login_steps: ["Complete the Groww authorisation opened by that client."],
      use_cases: ["Portfolio intelligence", "F&O analysis", "Smart order management", "Market context"],
      cautions: [
        "Sell orders through Groww MCP require DDPI authorisation.",
        "Groww native adapter code exists but remains disabled until live login/read verification passes.",
        "The Groww Trade API page still requires static IP setup for API-key order placement.",
      ],
      client_configs: [
        {
          id: "mcp_remote_cursor_vscode",
          label: "Cursor / VS Code mcp-remote",
          command: "npx",
          args: ["mcp-remote@0.1.18", "https://mcp.groww.in/mcp", "52155"],
          config: {
            mcpServers: {
              groww: {
                command: "npx",
                args: ["mcp-remote@0.1.18", "https://mcp.groww.in/mcp", "52155"],
              },
            },
          },
        },
      ],
    },
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
    (listBrokerMcpCatalogue as ReturnType<typeof vi.fn>).mockResolvedValue(MCP_BROKERS);
    (listNativeAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  });

  it("shows the section heading and empty connected-accounts state", async () => {
    renderSection();
    expect(screen.getByRole("heading", { name: "Brokers" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/No broker accounts connected/i)).toBeInTheDocument());
    expect(screen.getByText(/login and reads are verified for Dhan, Upstox, and INDmoney/i)).toBeInTheDocument();
  });

  it("shows hosted MCP setup without promoting Groww to native connect", async () => {
    renderSection();
    await waitFor(() => expect(listBrokerMcpCatalogue).toHaveBeenCalled());

    expect(await screen.findByText("Broker MCP assistants")).toBeInTheDocument();
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("Read-only");
    expect(screen.getByText("Repeat authorisation daily before relying on account context.")).toBeInTheDocument();
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent(
      "Upstox MCP cannot place, modify, or cancel orders.",
    );
    expect(screen.getByText("Add the Dhan remote MCP URL to a supported MCP client.")).toBeInTheDocument();
    expect(screen.getByTestId("broker-mcp-dhan-mcp_remote")).toHaveTextContent(
      "npx mcp-remote https://mcp.dhan.co/mcp",
    );
    expect(screen.getByTestId("broker-mcp-dhan-mcp_remote")).toHaveTextContent("mcpServers");
    expect(screen.getByText("https://mcp.groww.in/mcp")).toBeInTheDocument();
    expect(screen.getByText("npx mcp-remote@0.1.18 https://mcp.groww.in/mcp 52155")).toBeInTheDocument();
    expect(screen.getByTestId("broker-mcp-groww-mcp_remote_cursor_vscode")).toHaveTextContent("mcpServers");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("Native unavailable");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("disabled until live login/read verification");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("static IP setup");
    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    expect(screen.queryByRole("option", { name: "Groww" })).not.toBeInTheDocument();
  });

  it("shows retry-later broker login failures without asking for fresh login", async () => {
    (listNativeAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        adapter_id: "upstox",
        account_id: "UPX1",
        label: "Upstox",
        has_session: false,
        login_retryable: true,
        login_error: "Broker login is temporarily unavailable; retry later.",
      },
    ]);

    renderSection();

    await waitFor(() => expect(screen.getByText(/upstox.*retry later/i)).toBeInTheDocument());
    expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/needs fresh login/i)).not.toBeInTheDocument();
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
    expect(await screen.findByText(/Dhan account 1234567890 connected/i)).toBeInTheDocument();
  });

  it("launches OAuth for an oauth-method broker (Upstox)", async () => {
    (oauthStartNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue({
      auth_url: "https://api.upstox.com/v2/login/authorization/dialog?client_id=K",
      state: "S",
      redirect_uri: "http://127.0.0.1:5100/api/v1/native/oauth/callback",
      postback_uri: "http://127.0.0.1:5100/api/v1/native/postbacks/upstox",
    });
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Upstox" }));
    expect(screen.getByDisplayValue("http://127.0.0.1:5100/api/v1/native/oauth/callback")).toBeInTheDocument();
    expect(screen.getByDisplayValue("http://127.0.0.1:5100/api/v1/native/postbacks/upstox")).toBeInTheDocument();
    expect(screen.getByText(/Primary\/Secondary IP/i)).toBeInTheDocument();
    expect(screen.getByText(/invalidates Upstox access tokens/i)).toBeInTheDocument();
    expect(screen.getByText(/broker-reachable public or tunnel URL/i)).toBeInTheDocument();

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
    expect(screen.getByText(/Postback .* is optional/i)).toBeInTheDocument();
  });

  it("shows coming-soon native brokers but disables them", async () => {
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    const kotak = await screen.findByRole("option", { name: /Kotak Neo.*Coming soon/i });
    expect(kotak).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByLabelText(/consumer key/i)).not.toBeInTheDocument();
  });

  it("surfaces the live INDstocks token constraints from the catalogue", async () => {
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    fireEvent.click(await screen.findByRole("option", { name: "INDmoney" }));

    expect(screen.getByText(/INDstocks API dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/static outbound IP/i)).toBeInTheDocument();
    expect(screen.getByText(/resets tokens daily at 06:00 IST/i)).toBeInTheDocument();
    expect(screen.getByText(/up to five active tokens/i)).toBeInTheDocument();
    expect(screen.getByText(/daily 06:00 IST reset/i)).toBeInTheDocument();
  });
});

describe("BrokersSection — re-authentication (G5/G7)", () => {
  const STALE_ACCOUNT = {
    adapter_id: "dhan",
    account_id: "1234567890",
    label: "Dhan",
    has_session: false,
    needs_relogin: true,
    login_error: "login-failed: Dhan login requires an access_token",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue(BROKERS);
    (listBrokerMcpCatalogue as ReturnType<typeof vi.fn>).mockResolvedValue(MCP_BROKERS);
    (listNativeAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([STALE_ACCOUNT]);
  });

  it("shows the needs-fresh-login state with the actionable reason", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText(/needs fresh login/i)).toBeInTheDocument());
    expect(screen.getByText(/login-failed: Dhan login requires an access_token/i)).toBeInTheDocument();
  });

  it("one-click re-authenticate replays the stored credentials", async () => {
    (reloginNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue({ has_session: true });
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/re-authenticate dhan/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/re-authenticate dhan/i));
    await waitFor(() =>
      expect(reloginNativeAccount).toHaveBeenCalledWith("dhan", "1234567890"),
    );
    await waitFor(() =>
      expect(screen.getByText(/re-authenticated/i)).toBeInTheDocument(),
    );
  });

  it("prefills the connect form when the stored material is stale", async () => {
    (reloginNativeAccount as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("Re-login did not establish a session — enter fresh credentials."),
    );
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/re-authenticate dhan/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/re-authenticate dhan/i));
    await waitFor(() =>
      expect(screen.getByText(/enter fresh credentials below/i)).toBeInTheDocument(),
    );
    // Broker + account id are prefilled so the operator only types the fresh secret.
    expect((screen.getByLabelText(/account id/i) as HTMLInputElement).value).toBe("1234567890");
  });
});

describe("BrokersSection — primary account selection", () => {
  const CONNECTED_NON_PRIMARY = {
    adapter_id: "upstox",
    account_id: "UPX1",
    label: "Upstox",
    has_session: true,
    is_primary: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue(BROKERS);
    (listBrokerMcpCatalogue as ReturnType<typeof vi.fn>).mockResolvedValue(MCP_BROKERS);
    (listNativeAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([CONNECTED_NON_PRIMARY]);
  });

  it("can set a connected native account as primary", async () => {
    (setPrimaryNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/set upstox UPX1 as primary/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/set upstox UPX1 as primary/i));

    await waitFor(() => expect(setPrimaryNativeAccount).toHaveBeenCalledWith("upstox", "UPX1"));
    await waitFor(() => expect(screen.getByText(/set as primary/i)).toBeInTheDocument());
  });
});

describe("BrokersSection — disconnect feedback", () => {
  const CONNECTED_ACCOUNT = {
    adapter_id: "upstox",
    account_id: "UPX1",
    label: "Upstox",
    has_session: true,
    needs_relogin: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue(BROKERS);
    (listBrokerMcpCatalogue as ReturnType<typeof vi.fn>).mockResolvedValue(MCP_BROKERS);
    (listNativeAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([CONNECTED_ACCOUNT]);
  });

  it("shows a confirmation after disconnecting an account", async () => {
    (removeNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/disconnect upstox UPX1/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/disconnect upstox UPX1/i));

    await waitFor(() => expect(removeNativeAccount).toHaveBeenCalledWith("upstox", "UPX1"));
    expect(await screen.findByText(/upstox account UPX1 disconnected/i)).toBeInTheDocument();
  });

  it("surfaces disconnect failures instead of failing silently", async () => {
    (removeNativeAccount as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Vault is locked"));
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/disconnect upstox UPX1/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/disconnect upstox UPX1/i));

    expect(await screen.findByRole("alert")).toHaveTextContent("Vault is locked");
  });
});
