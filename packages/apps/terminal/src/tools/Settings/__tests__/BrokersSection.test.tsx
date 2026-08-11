/**
 * BrokersSection.test.tsx — the native broker connect UI (Phase 1 G4).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { BrokerAccount } from "@/types/broker";

vi.mock("@/services/ftApi.native", () => ({
  listNativeBrokers: vi.fn(),
  listBrokerMcpCatalogue: vi.fn(),
  connectNativeAccount: vi.fn(),
  oauthStartNativeAccount: vi.fn(),
}));

vi.mock("@/services/brokerAccountsApi", () => ({
  listBrokerAccounts: vi.fn(),
  removeBrokerAccount: vi.fn(),
  reconnectBrokerAccount: vi.fn(),
  setPrimaryBrokerAccount: vi.fn(),
}));

import {
  listNativeBrokers,
  listBrokerMcpCatalogue,
  connectNativeAccount,
  oauthStartNativeAccount,
} from "@/services/ftApi.native";
import {
  listBrokerAccounts,
  removeBrokerAccount,
  reconnectBrokerAccount,
  setPrimaryBrokerAccount,
} from "@/services/brokerAccountsApi";
import { useBrokerStore } from "@/stores/brokerStore";
import { useAuthStore } from "@/stores/authStore";
import { BrokersSection } from "../BrokersSection";

const BROKERS = [
  {
    adapter_id: "dhan",
    display_name: "Dhan",
    connectable: true,
    requires_static_ip: true,
    native_connect_blockers: [],
    sdk_pin: "dhanhq",
    sdk_attestation: {
      pin: "dhanhq",
      pinned_version: "2.2.0",
      installed_version: "2.2.0",
      status: "ok" as const,
    },
    oauth_redirect_uri: "http://127.0.0.1:5100/api/v1/native/oauth/callback",
    postback_uri: "http://127.0.0.1:5100/api/v1/native/postbacks/dhan",
    auth_methods: [
      {
        id: "oauth",
        label: "Log in with Dhan (OAuth)",
        kind: "oauth" as const,
        description: (
          "Approve a DhanHQ app-consent login. Register the shown redirect URL in your DhanHQ app; " +
          "Dhan redirects back with a tokenId that FlintTrade consumes for a 24h access token."
        ),
        fields: [
          { name: "api_key", label: "App ID", secret: false, required: true, help: "" },
          { name: "api_secret", label: "App secret", secret: true, required: true, help: "" },
        ],
      },
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
      {
        id: "pin_totp",
        label: "PIN + TOTP",
        kind: "direct" as const,
        description: "Mint a fresh 24h token from your PIN and authenticator code.",
        fields: [
          { name: "client_id", label: "Dhan client ID", secret: false, required: true, help: "" },
          { name: "pin", label: "PIN", secret: true, required: true, help: "" },
          { name: "totp", label: "6-digit TOTP", secret: false, required: true, help: "" },
        ],
      },
    ],
  },
  {
    adapter_id: "upstox",
    display_name: "Upstox",
    connectable: true,
    requires_static_ip: true,
    native_connect_blockers: [],
    sdk_pin: "upstox-python-sdk",
    sdk_attestation: {
      pin: "upstox-python-sdk",
      pinned_version: "2.28.0",
      installed_version: "2.28.0",
      status: "ok" as const,
    },
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
      {
        id: "analytics_access_token",
        label: "Analytics access token (read-only)",
        kind: "direct" as const,
        description:
          "Paste the one-year Analytics Access Token from Upstox Developer → Apps. FlintTrade blocks writes.",
        fields: [
          { name: "client_id", label: "Client ID", secret: false, required: false, help: "" },
          { name: "access_token", label: "Analytics access token", secret: true, required: true, help: "" },
        ],
        credential_defaults: { read_only: "true", token_scope: "analytics" },
      },
    ],
  },
  {
    adapter_id: "kotakneo",
    display_name: "Kotak Neo",
    connectable: false,
    requires_static_ip: true,
    native_connect_blockers: [
      "Maintainer live login/read verification with current TOTP and MPIN",
      "Live order-safety proof",
    ],
    auth_methods: [
      {
        id: "totp_mpin",
        label: "TOTP + MPIN",
        kind: "direct" as const,
        description: "Kotak NEO two-step 2FA.",
        fields: [
          {
            name: "access_token",
            label: "Trade API access token",
            secret: true,
            required: true,
            help: "Maps to the SDK consumer_key internally.",
          },
          { name: "mobile_number", label: "Mobile number", secret: false, required: true, help: "" },
          { name: "ucc", label: "UCC", secret: false, required: true, help: "" },
          { name: "totp", label: "TOTP", secret: false, required: true, help: "" },
          { name: "mpin", label: "MPIN", secret: true, required: true, help: "" },
        ],
      },
    ],
  },
  {
    adapter_id: "indmoney",
    display_name: "INDmoney",
    connectable: false,
    requires_static_ip: true,
    native_connect_blockers: [
      "Authoritative smart-parent cancellation discriminator",
      "Broker-native atomic reduce-only close primitive",
      "Live order-safety proof",
    ],
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
  {
    adapter_id: "groww",
    display_name: "Groww",
    connectable: false,
    requires_static_ip: true,
    native_connect_blockers: ["Broker-side market-data/API permission", "Live order-safety proof"],
    auth_methods: [
      {
        id: "api_key_totp",
        label: "API key + TOTP",
        kind: "direct" as const,
        description: "Enter the Groww Trade API key and current TOTP code.",
        fields: [
          { name: "user_id", label: "User ID", secret: false, required: false, help: "" },
          { name: "api_key", label: "API key", secret: true, required: true, help: "" },
          { name: "totp", label: "6-digit TOTP", secret: false, required: true, help: "" },
        ],
      },
      {
        id: "api_key_secret",
        label: "API key + secret",
        kind: "direct" as const,
        description: (
          "Enter the Groww Trade API key and secret from Groww Cloud/API Keys. Live order placement still " +
          "requires static outbound IP setup."
        ),
        fields: [
          { name: "api_key", label: "Groww Trade API key", secret: true, required: true, help: "" },
          { name: "api_secret", label: "Groww Trade API secret", secret: true, required: true, help: "" },
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
    requires_static_ip: true,
    native_connect_blockers: [],
    mcp: {
      remote_url: "https://mcp.dhan.co/mcp",
      docs_url: "https://docs.dhanhq.co/mcp/",
      auth_mode: "Authorize through Dhan's hosted MCP flow from the client.",
      reauth: "Re-authorize in the MCP client when Dhan prompts for a fresh session.",
      read_only: false,
      trading_supported: true,
      login_steps: [
        "Add the Dhan remote MCP URL to a supported MCP client.",
        "Complete the Dhan browser authorisation and explicit consent flow opened by that client.",
        "Keep FlintTrade live orders on the gated native/OpenAlgo path.",
      ],
      use_cases: [
        "Portfolio and account review",
        "Market data, historical OHLC, option chain with Greeks, and live-feed lookup",
      ],
      cautions: [
        "Broker MCP trade tools are outside FlintTrade's in-process safety gate.",
        "Dhan's agent skill pack is reference/setup help; it does not establish a FlintTrade broker session.",
        "Dhan's documented skill guardrails require explicit confirmation before place/modify/cancel, use LIMIT defaults, and validate F&O lot sizes.",
      ],
      client_configs: [
        { id: "remote_url", label: "Claude / ChatGPT / custom connector", url: "https://mcp.dhan.co/mcp" },
        {
          id: "claude_code",
          label: "Claude Code CLI",
          command: "claude",
          args: ["mcp", "add", "--transport", "http", "dhan", "https://mcp.dhan.co/mcp"],
        },
        {
          id: "codex_cli",
          label: "Codex CLI",
          command: "codex",
          args: ["mcp", "add", "dhan", "--url", "https://mcp.dhan.co/mcp"],
        },
        {
          id: "cursor",
          label: "Cursor direct URL",
          url: "https://mcp.dhan.co/mcp",
          config: {
            mcpServers: {
              dhan: { url: "https://mcp.dhan.co/mcp" },
            },
          },
        },
        {
          id: "vscode_copilot",
          label: "VS Code direct URL",
          url: "https://mcp.dhan.co/mcp",
          config: {
            mcp: {
              servers: {
                dhan: { url: "https://mcp.dhan.co/mcp" },
              },
            },
          },
        },
        {
          id: "kiro",
          label: "Kiro direct URL",
          url: "https://mcp.dhan.co/mcp",
          config: {
            mcpServers: {
              dhan: { url: "https://mcp.dhan.co/mcp" },
            },
          },
        },
        {
          id: "opencode",
          label: "OpenCode remote OAuth",
          url: "https://mcp.dhan.co/mcp",
          config: {
            name: "dhan",
            type: "remote",
            url: "https://mcp.dhan.co/mcp",
            oauth: true,
          },
        },
        {
          id: "dhanhq_skill_pack",
          label: "DhanHQ agent skill pack",
          command: "skills",
          args: ["add", "dhan-oss/dhanhq-skills", "--skill", "dhanhq"],
        },
      ],
    },
  },
  {
    adapter_id: "upstox",
    display_name: "Upstox",
    native: true,
    connectable: true,
    requires_static_ip: true,
    native_connect_blockers: [],
    mcp: {
      remote_url: "https://mcp.upstox.com/mcp",
      docs_url: "https://upstox.com/developer/api-documentation/mcp-integration/",
      auth_mode: "Authorize through Upstox's hosted MCP flow from the client.",
      reauth: "Daily re-authorisation is required.",
      read_only: true,
      trading_supported: false,
      daily_reauthorization: true,
      login_steps: [
        "Install Node.js, then add the Upstox MCP configuration to Claude Desktop, ChatGPT, Cursor, or VS Code.",
        "Use an active, non-dormant Upstox account; dormant accounts cannot complete MCP authorisation.",
        "Complete the OAuth authorisation opened by that client.",
        "Repeat authorisation daily before relying on account context.",
        "Keep FlintTrade live orders on the gated native/OpenAlgo path.",
      ],
      use_cases: [
        "Read-only holdings, orders, positions, mutual funds, funds, and profile lookup",
        "Account-scoped portfolio composition, performance, risk, and buying-power analysis",
        "Individual stock research in the context of current holdings",
        "Technical indicator, chart, trend, market-quote, and market-context analysis",
        "Activity summaries, margins, historical trading information, and P&L overviews",
        "Portfolio beta and correlation studies against NIFTY over multi-year windows",
        "Professional investment-model reviews over the operator's current portfolio",
        "Board-meeting, AGM/EGM, corporate-governance, and hold-or-sell context checks",
      ],
      cautions: [
        "Upstox MCP cannot place, modify, or cancel orders.",
        "Treat AI-generated analysis as research support; verify critical data directly on Upstox before acting.",
        "Do not treat the hosted MCP as a FlintTrade live order path.",
        "If the MCP client starts the wrong Node.js/npx binary, configure full node and npx paths instead of relying on PATH.",
      ],
      client_configs: [
        {
          id: "remote_url",
          label: "ChatGPT / custom connector URL",
          url: "https://mcp.upstox.com/mcp",
          config: { name: "Upstox MCP", url: "https://mcp.upstox.com/mcp", developer_mode: true },
        },
        {
          id: "claude_cursor_mcp_remote",
          label: "Claude Desktop / Cursor mcp-remote",
          command: "npx",
          args: ["mcp-remote", "https://mcp.upstox.com/mcp"],
          config: {
            mcpServers: {
              "Upstox MCP": { command: "npx", args: ["mcp-remote", "https://mcp.upstox.com/mcp"] },
            },
          },
        },
        {
          id: "vscode_copilot",
          label: "VS Code GitHub Copilot",
          url: "https://mcp.upstox.com/mcp",
          config: { mcp: { inputs: [], servers: { "Upstox MCP": { url: "https://mcp.upstox.com/mcp" } } } },
        },
      ],
    },
  },
  {
    adapter_id: "groww",
    display_name: "Groww",
    native: true,
    connectable: false,
    requires_static_ip: true,
    native_connect_blockers: ["Broker-side market-data/API permission", "Live order-safety proof"],
    mcp: {
      remote_url: "https://mcp.groww.in/mcp",
      docs_url: "https://groww.in/updates/groww-mcp",
      auth_mode: "Authorize through Groww's hosted MCP flow from the client with explicit account permission.",
      reauth: "Grant access when the MCP client asks; Groww documents explicit permission rather than background sync.",
      read_only: false,
      trading_supported: true,
      login_steps: [
        "For Claude Pro, add a custom connector named GrowwMCP with the Groww MCP URL.",
        "For Cursor, VS Code, or Windsurf, add the mcp-remote configuration and install Node.js if needed.",
        "Confirm DDPI status before sell-order workflows.",
      ],
      use_cases: [
        "Portfolio performance, exposure, benchmark, and market-fall analysis",
        "F&O position, candle, expiry, and P&L analysis",
        "Smart order management in the external MCP client",
        "Market context and holdings near 52-week highs",
        "Stocks and F&O today; mutual funds, IPOs, bonds, and fundamental analysis are future broker scope",
      ],
      cautions: [
        "Sell orders through Groww MCP require DDPI authorisation.",
        "Groww describes MCP as early-stage and not investment advice; verify outputs before trading.",
        "Groww documents explicit permission, no background syncing, and no AI-server data storage for MCP access.",
        "Groww native token minting may require approving the API-key session in Groww Cloud before FlintTrade can log in.",
        "Groww native account reads and margin checks have passed with an approved key, but native connect stays disabled until market-data/API permissions, static IP setup, and order-safety verification pass.",
      ],
      client_configs: [
        {
          id: "remote_url",
          label: "Claude Pro custom connector",
          url: "https://mcp.groww.in/mcp",
          config: { name: "GrowwMCP", url: "https://mcp.groww.in/mcp" },
        },
        {
          id: "mcp_remote_cursor_vscode",
          label: "Cursor / VS Code / Windsurf mcp-remote",
          command: "npx",
          args: ["mcp-remote@0.1.18", "https://mcp.groww.in/mcp", "52155"],
          config: {
            mcpServers: {
              growwmcp: {
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

function renderSection(pollAccounts?: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrokersSection pollAccounts={pollAccounts} />
    </QueryClientProvider>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function submitDhanAccessToken(accountId: string, accountLabel = "") {
  fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
  fireEvent.click(await screen.findByRole("option", { name: "Dhan" }));
  fireEvent.click(screen.getByRole("combobox", { name: /login method/i }));
  fireEvent.click(await screen.findByRole("option", { name: "Access token" }));
  fireEvent.change(screen.getByLabelText(/account id/i), { target: { value: accountId } });
  if (accountLabel) {
    fireEvent.change(screen.getByLabelText(/account label/i), { target: { value: accountLabel } });
  }
  fireEvent.change(screen.getByLabelText("Dhan client ID"), { target: { value: accountId } });
  fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "TOK" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
}

function makeNativeAccount(overrides: Partial<BrokerAccount> = {}): BrokerAccount {
  return {
    account_id: "D1",
    broker: "dhan",
    label: "Dhan",
    status: "connected",
    connected_at: null,
    error_message: null,
    is_primary: false,
    source: "native",
    ...overrides,
  };
}

function makeGatewayAccount(overrides: Partial<BrokerAccount> = {}): BrokerAccount {
  return {
    account_id: "GW1",
    broker: "zerodha",
    label: "Zerodha Main",
    status: "connected",
    connected_at: null,
    error_message: null,
    is_primary: false,
    source: "gateway",
    ...overrides,
  };
}

function setClipboard(writeText?: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: writeText ? { writeText } : undefined,
  });
}

describe("BrokersSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setClipboard();
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue(BROKERS);
    (listBrokerMcpCatalogue as ReturnType<typeof vi.fn>).mockResolvedValue(MCP_BROKERS);
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    // The broker store is a module singleton; reset it so a seeded gateway
    // account from one test never leaks into the next.
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
    useAuthStore.setState({
      status: "logged-in",
      token: "settings-session",
      reauthToken: null,
      username: "settings-user",
      sessionGeneration: 1,
    });
  });

  it("can consume AppLayout's account snapshot without mounting another poll", async () => {
    renderSection(false);

    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());
    expect(listBrokerAccounts).not.toHaveBeenCalled();
  });

  it("polls accounts by default for setup callers outside AppLayout", async () => {
    renderSection();

    await waitFor(() => expect(listBrokerAccounts).toHaveBeenCalledTimes(1));
  });

  it("shows the section heading and empty connected-accounts state", async () => {
    renderSection();
    expect(screen.getByRole("heading", { name: "Brokers" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/No broker accounts connected/i)).toBeInTheDocument());
    expect(screen.getByText(/not fully tested — use at your own risk/i)).toBeInTheDocument();
    await waitFor(() => {
      const nativeWarning = screen.getByText(/Native connection is currently enabled for/i);
      expect(nativeWarning).toHaveTextContent("Dhan and Upstox");
      expect(nativeWarning).toHaveTextContent("Kotak Neo, INDmoney, and Groww stay visible");
      expect(nativeWarning).toHaveTextContent("not been live-verified for any broker");
    });
  });

  it("shows SDK readiness for the selected native broker", async () => {
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Dhan" }));

    expect(screen.getByTestId("native-broker-sdk-status")).toHaveTextContent("SDK readiness");
    expect(screen.getByTestId("native-broker-sdk-status")).toHaveTextContent("dhanhq 2.2.0 OK");
  });

  it("blocks native connect when the selected broker SDK is not attested", async () => {
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        ...BROKERS[0],
        sdk_attestation: {
          pin: "dhanhq",
          pinned_version: "2.2.0",
          installed_version: null,
          status: "missing" as const,
        },
      },
    ]);
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Dhan" }));

    expect(screen.getByTestId("native-broker-sdk-status")).toHaveTextContent("dhanhq 2.2.0 missing");
    expect(screen.getByText(/sync dependencies before connecting/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /log in with dhan/i })).toBeDisabled();
  });

  it("lists a legacy gateway account and disconnects it (finding #9 — no orphaned management)", async () => {
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([makeGatewayAccount()]);
    (removeBrokerAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    renderSection();

    await waitFor(() => expect(screen.getByText("Gateway accounts")).toBeInTheDocument());
    expect(screen.getByText("Zerodha Main")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /disconnect zerodha main/i }));
    await waitFor(() =>
      expect(removeBrokerAccount).toHaveBeenCalledWith(
        expect.objectContaining({ source: "gateway", broker: "zerodha", account_id: "GW1" }),
      ),
    );
  });

  it("can set a connected gateway account as primary", async () => {
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeGatewayAccount({ is_primary: false }),
    ]);
    (setPrimaryBrokerAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    renderSection();

    const promote = await screen.findByRole("button", { name: /set zerodha main as primary/i });
    fireEvent.click(promote);

    await waitFor(() =>
      expect(setPrimaryBrokerAccount).toHaveBeenCalledWith(
        expect.objectContaining({ source: "gateway", broker: "zerodha", account_id: "GW1" }),
      ),
    );
  });

  it("does not offer primary selection for stale or read-only gateway accounts", async () => {
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeGatewayAccount({ account_id: "GW1", label: "Read Only Bridge", read_only: true }),
      makeGatewayAccount({
        account_id: "GW2",
        label: "Expired Bridge",
        status: "token_expired",
        error_message: "Needs a fresh gateway login",
      }),
    ]);

    renderSection();

    await waitFor(() => expect(screen.getByText("Gateway accounts")).toBeInTheDocument());
    expect(screen.getByText("Read Only Bridge")).toBeInTheDocument();
    expect(screen.getByText(/zerodha.*read-only/i)).toBeInTheDocument();
    expect(screen.getByText("Expired Bridge")).toBeInTheDocument();
    expect(screen.queryByLabelText(/set read only bridge as primary/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/set expired bridge as primary/i)).not.toBeInTheDocument();
    expect(setPrimaryBrokerAccount).not.toHaveBeenCalled();
  });

  it("removing a gateway account never evicts a same-id native write target", async () => {
    // Round-3 finding: the same broker-supplied client code can be linked via
    // BOTH the native adapter and the OpenAlgo bridge. Removing the gateway row
    // must use a source-qualified key so it cannot cross-evict the native row
    // (and silently null the active native write target).
    const sharedAccounts = [
      makeNativeAccount({ account_id: "SHARED", broker: "upstox", label: "Upstox Native" }),
      makeGatewayAccount({ account_id: "SHARED", broker: "upstox", label: "Upstox Bridge" }),
    ];
    (listBrokerAccounts as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(sharedAccounts)
      .mockResolvedValue([sharedAccounts[0]]);
    (removeBrokerAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    useBrokerStore.setState({
      accounts: sharedAccounts,
      activeAccountId: "native:upstox:SHARED",
    });

    renderSection();

    const disconnect = await screen.findByRole("button", { name: /disconnect upstox bridge/i });
    fireEvent.click(disconnect);

    await waitFor(() =>
      expect(removeBrokerAccount).toHaveBeenCalledWith(
        expect.objectContaining({ source: "gateway", broker: "upstox", account_id: "SHARED" }),
      ),
    );
    await waitFor(() => {
      const accts = useBrokerStore.getState().accounts;
      expect(accts).toHaveLength(1);
      expect(accts[0].source).toBe("native");
    });
    // The operator's active native write target must survive the gateway removal.
    expect(useBrokerStore.getState().activeAccountId).toBe("native:upstox:SHARED");
  });

  it("optimistically drops a removed native account from the store (finding #2 — no resurrection)", async () => {
    // A removed native account must leave the write-target store immediately so
    // the next account poll's last-good preservation cannot resurrect it as a
    // live write target while its source route refreshes.
    const nativeAccount = makeNativeAccount({ account_id: "D1", broker: "dhan", label: "Dhan" });
    (listBrokerAccounts as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce([nativeAccount])
      .mockResolvedValue([]);
    (removeBrokerAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    useBrokerStore.setState({
      accounts: [nativeAccount],
      activeAccountId: "native:dhan:D1",
    });

    renderSection();

    const disconnect = await screen.findByRole("button", { name: /disconnect dhan d1/i });
    fireEvent.click(disconnect);

    await waitFor(() =>
      expect(removeBrokerAccount).toHaveBeenCalledWith(
        expect.objectContaining({ source: "native", broker: "dhan", account_id: "D1" }),
      ),
    );
    await waitFor(() => expect(useBrokerStore.getState().accounts).toHaveLength(0));
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
  });

  it("shows hosted MCP setup without promoting Groww to native connect", async () => {
    renderSection();
    await waitFor(() => expect(listBrokerMcpCatalogue).toHaveBeenCalled());

    expect(await screen.findByText("Broker MCP assistants")).toBeInTheDocument();
    expect(screen.getByTestId("native-connect-blockers")).toHaveTextContent(
      "Kotak Neo: Maintainer live login/read verification with current TOTP and MPIN and Live order-safety proof",
    );
    expect(screen.getByTestId("native-connect-blockers")).toHaveTextContent(
      "Groww: Broker-side market-data/API permission and Live order-safety proof",
    );
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("Read-only");
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("Static IP for live API orders");
    expect(screen.getByText(/active, non-dormant Upstox account/)).toBeInTheDocument();
    expect(screen.getByText("Repeat authorisation daily before relying on account context.")).toBeInTheDocument();
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent(
      "Upstox MCP cannot place, modify, or cancel orders.",
    );
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent(
      "gated native/OpenAlgo path",
    );
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent(
      "not treat the hosted MCP as a FlintTrade live order path",
    );
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("verify critical data");
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("full node and npx paths");
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("market-quote");
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("historical trading information");
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("Portfolio beta");
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("Professional investment-model");
    expect(screen.getByTestId("broker-mcp-upstox")).toHaveTextContent("corporate-governance");
    expect(screen.getByText("Add the Dhan remote MCP URL to a supported MCP client.")).toBeInTheDocument();
    expect(screen.getByTestId("broker-mcp-dhan-claude_code")).toHaveTextContent(
      "claude mcp add --transport http dhan https://mcp.dhan.co/mcp",
    );
    expect(screen.getByTestId("broker-mcp-dhan-codex_cli")).toHaveTextContent(
      "codex mcp add dhan --url https://mcp.dhan.co/mcp",
    );
    expect(screen.getByTestId("broker-mcp-dhan-cursor")).toHaveTextContent("mcpServers");
    expect(screen.getByTestId("broker-mcp-dhan-vscode_copilot")).toHaveTextContent("VS Code direct URL");
    expect(screen.getByTestId("broker-mcp-dhan-vscode_copilot")).toHaveTextContent("mcp");
    expect(screen.getByTestId("broker-mcp-dhan-kiro")).toHaveTextContent("Kiro direct URL");
    expect(screen.getByTestId("broker-mcp-dhan-opencode")).toHaveTextContent("OpenCode remote OAuth");
    expect(screen.getByTestId("broker-mcp-dhan-opencode")).toHaveTextContent("oauth");
    expect(screen.getByTestId("broker-mcp-dhan-dhanhq_skill_pack")).toHaveTextContent(
      "skills add dhan-oss/dhanhq-skills --skill dhanhq",
    );
    expect(screen.getByTestId("broker-mcp-dhan")).toHaveTextContent("LIMIT defaults");
    expect(screen.getByTestId("broker-mcp-dhan")).toHaveTextContent("F&O lot sizes");
    expect(screen.getByTestId("broker-mcp-dhan")).toHaveTextContent("Static IP for live API orders");
    expect(screen.getByTestId("broker-mcp-upstox-vscode_copilot")).toHaveTextContent("VS Code GitHub Copilot");
    expect(screen.getAllByText("https://mcp.groww.in/mcp").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId("broker-mcp-groww-remote_url")).toHaveTextContent("GrowwMCP");
    expect(screen.getByText("npx mcp-remote@0.1.18 https://mcp.groww.in/mcp 52155")).toBeInTheDocument();
    expect(screen.getByTestId("broker-mcp-groww-mcp_remote_cursor_vscode")).toHaveTextContent("mcpServers");
    expect(screen.getByTestId("broker-mcp-groww-mcp_remote_cursor_vscode")).toHaveTextContent("growwmcp");
    expect(screen.getByTestId("broker-mcp-groww-mcp_remote_cursor_vscode")).toHaveTextContent("Windsurf");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("Native unavailable");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent(
      "Native blockers: Broker-side market-data/API permission and Live order-safety proof",
    );
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("Static IP for live API orders");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("early-stage");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("no background syncing");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("no AI-server data storage");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("API-key session in Groww Cloud");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("market-data/API permissions");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("static IP setup");
    expect(screen.getByTestId("broker-mcp-groww")).toHaveTextContent("future broker scope");
    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    const groww = await screen.findByRole("option", { name: /Groww.*Coming soon/i });
    expect(groww).toHaveAttribute("aria-disabled", "true");
  });

  it("reports MCP setup copy success only after the clipboard write succeeds", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard(writeText);

    renderSection();
    await screen.findByText("Broker MCP assistants");

    fireEvent.click(screen.getByRole("button", { name: "Copy Upstox MCP URL" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("https://mcp.upstox.com/mcp"));
    expect(await screen.findByText("Upstox MCP URL copied.")).toBeInTheDocument();
  });

  it("does not claim MCP setup copy success when the clipboard write fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("clipboard denied"));
    setClipboard(writeText);

    renderSection();
    await screen.findByText("Broker MCP assistants");

    fireEvent.click(screen.getByRole("button", { name: "Copy Upstox MCP URL" }));

    expect(
      await screen.findByText("Upstox MCP URL could not be copied. Select and copy it manually."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Upstox MCP URL copied.")).not.toBeInTheDocument();
  });

  it("shows retry-later broker login failures without asking for fresh login", async () => {
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeNativeAccount({
        account_id: "UPX1",
        broker: "upstox",
        label: "Upstox",
        status: "disconnected",
        login_retryable: true,
        error_message: "Broker login is temporarily unavailable; retry later.",
      }),
    ]);

    renderSection();

    await waitFor(() => expect(screen.getByText(/upstox.*retry later/i)).toBeInTheDocument());
    expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/needs fresh login/i)).not.toBeInTheDocument();
  });

  it("labels connected read-only native sessions", async () => {
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeNativeAccount({
        account_id: "UPXRO",
        broker: "upstox",
        label: "Upstox Analytics",
        read_only: true,
      }),
    ]);

    renderSection();

    await waitFor(() => expect(screen.getByText(/upstox.*read-only.*connected/i)).toBeInTheDocument());
  });

  it("connects a direct-credential account (Dhan access token)", async () => {
    (connectNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue({ connected: true, login: "ok" });
    const refreshedAccount = makeNativeAccount({ account_id: "1234567890" });
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([refreshedAccount]);
    renderSection(false);
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());
    expect(listBrokerAccounts).not.toHaveBeenCalled();

    await submitDhanAccessToken("1234567890", "Dhan swing");

    await waitFor(() =>
      expect(connectNativeAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          adapter_id: "dhan",
          account_id: "1234567890",
          label: "Dhan swing",
          credentials: { client_id: "1234567890", access_token: "TOK" },
        }),
      ),
    );
    expect(await screen.findByText(/Dhan account 1234567890 connected/i)).toBeInTheDocument();
    await waitFor(() => expect(listBrokerAccounts).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(useBrokerStore.getState().accounts).toEqual([refreshedAccount]));
  });

  it.each(["unmount", "retire-session"] as const)(
    "does not apply a manual account refresh after %s",
    async (boundary) => {
      const refresh = deferred<BrokerAccount[]>();
      (connectNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue({ connected: true, login: "ok" });
      (listBrokerAccounts as ReturnType<typeof vi.fn>).mockReturnValue(refresh.promise);
      const view = renderSection(false);
      await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

      await submitDhanAccessToken("STALE1");
      await waitFor(() => expect(listBrokerAccounts).toHaveBeenCalledTimes(1));

      if (boundary === "unmount") {
        view.unmount();
      } else {
        act(() => useAuthStore.getState().setPinRequired());
      }

      await act(async () => {
        refresh.resolve([makeNativeAccount({ account_id: "STALE1" })]);
        await refresh.promise;
        await Promise.resolve();
      });

      expect(useBrokerStore.getState().accounts).toEqual([]);
    },
  );

  it("launches OAuth for Dhan app-consent logins", async () => {
    (oauthStartNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue({
      auth_url: "https://auth.dhan.co/login/consentApp-login?consentAppId=C1",
      state: "S",
      redirect_uri: "http://127.0.0.1:5100/api/v1/native/oauth/callback",
      postback_uri: "http://127.0.0.1:5100/api/v1/native/postbacks/dhan",
    });
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Dhan" }));
    expect(screen.getByDisplayValue("http://127.0.0.1:5100/api/v1/native/oauth/callback")).toBeInTheDocument();
    expect(screen.getByDisplayValue("http://127.0.0.1:5100/api/v1/native/postbacks/dhan")).toBeInTheDocument();
    expect(screen.getByText(/Dhan redirects back with a tokenId/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/account id/i), { target: { value: "DHANCLIENT1" } });
    fireEvent.change(screen.getByLabelText(/account label/i), { target: { value: "Dhan OAuth" } });
    fireEvent.change(screen.getByLabelText("App ID"), { target: { value: "APPID" } });
    fireEvent.change(screen.getByLabelText("App secret"), { target: { value: "SECRET" } });
    fireEvent.click(screen.getByRole("button", { name: /log in with dhan/i }));

    await waitFor(() =>
      expect(oauthStartNativeAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          adapter_id: "dhan",
          account_id: "DHANCLIENT1",
          label: "Dhan OAuth",
          api_key: "APPID",
          api_secret: "SECRET",
        }),
      ),
    );
    expect(openSpy).toHaveBeenCalledWith(expect.stringContaining("auth.dhan.co"), "_blank", "noopener");
    expect(screen.getByText(/Postback .* is optional/i)).toBeInTheDocument();
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

  it("connects Upstox analytics tokens as read-only native sessions", async () => {
    (connectNativeAccount as ReturnType<typeof vi.fn>).mockResolvedValue({ connected: true, login: "ok" });
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Upstox" }));
    fireEvent.click(screen.getByRole("combobox", { name: /login method/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Analytics access token (read-only)" }));

    fireEvent.change(screen.getByLabelText(/account id/i), { target: { value: "UPX1" } });
    fireEvent.change(screen.getByLabelText(/^Client ID/i), { target: { value: "UPX1" } });
    fireEvent.change(screen.getByLabelText("Analytics access token"), { target: { value: "ANALYTICS-TOK" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(connectNativeAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          adapter_id: "upstox",
          account_id: "UPX1",
          credentials: {
            read_only: "true",
            token_scope: "analytics",
            client_id: "UPX1",
            access_token: "ANALYTICS-TOK",
          },
        }),
      ),
    );
    expect(await screen.findByText(/Upstox account UPX1 connected/i)).toBeInTheDocument();
  });

  it("shows coming-soon native brokers but disables them", async () => {
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    const kotak = await screen.findByRole("option", { name: /Kotak Neo.*Coming soon/i });
    expect(kotak).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByLabelText(/consumer key/i)).not.toBeInTheDocument();
  });

  it("keeps INDmoney disabled with its activation blockers visible", async () => {
    renderSection();
    await waitFor(() => expect(listNativeBrokers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("combobox", { name: /broker/i }));
    const indmoney = await screen.findByRole("option", { name: /INDmoney.*Coming soon/i });
    expect(indmoney).toHaveAttribute("aria-disabled", "true");
    const blockers = screen.getByTestId("native-connect-blockers");
    expect(blockers).toHaveTextContent(
      "Authoritative smart-parent cancellation discriminator",
    );
    expect(blockers).toHaveTextContent(
      "Broker-native atomic reduce-only close primitive",
    );
    expect(blockers).toHaveTextContent("Live order-safety proof");
  });
});

describe("BrokersSection — re-authentication (G5/G7)", () => {
  const STALE_ACCOUNT = makeNativeAccount({
    account_id: "1234567890",
    broker: "dhan",
    label: "Dhan",
    status: "token_expired",
    needs_relogin: true,
    error_message: "login-failed: Dhan login requires an access_token",
  });

  beforeEach(() => {
    vi.clearAllMocks();
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue(BROKERS);
    (listBrokerMcpCatalogue as ReturnType<typeof vi.fn>).mockResolvedValue(MCP_BROKERS);
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([STALE_ACCOUNT]);
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
  });

  it("shows the needs-fresh-login state with the actionable reason", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText(/needs fresh login/i)).toBeInTheDocument());
    expect(screen.getByText(/login-failed: Dhan login requires an access_token/i)).toBeInTheDocument();
  });

  it("one-click re-authenticate replays the stored credentials", async () => {
    (reconnectBrokerAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/re-authenticate dhan/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/re-authenticate dhan/i));
    await waitFor(() =>
      expect(reconnectBrokerAccount).toHaveBeenCalledWith(
        expect.objectContaining({ source: "native", broker: "dhan", account_id: "1234567890" }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByText(/re-authenticated/i)).toBeInTheDocument(),
    );
  });

  it("prefills the connect form when the stored material is stale", async () => {
    (reconnectBrokerAccount as ReturnType<typeof vi.fn>).mockRejectedValue(
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
  const CONNECTED_NON_PRIMARY = makeNativeAccount({
    account_id: "UPX1",
    broker: "upstox",
    label: "Upstox",
    status: "connected",
    is_primary: false,
  });

  beforeEach(() => {
    vi.clearAllMocks();
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue(BROKERS);
    (listBrokerMcpCatalogue as ReturnType<typeof vi.fn>).mockResolvedValue(MCP_BROKERS);
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([CONNECTED_NON_PRIMARY]);
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
  });

  it("can set a connected native account as primary", async () => {
    (setPrimaryBrokerAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/set upstox UPX1 as primary/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/set upstox UPX1 as primary/i));

    await waitFor(() =>
      expect(setPrimaryBrokerAccount).toHaveBeenCalledWith(
        expect.objectContaining({ source: "native", broker: "upstox", account_id: "UPX1" }),
      ),
    );
    await waitFor(() => expect(screen.getByText(/set as primary/i)).toBeInTheDocument());
  });

  it("does not offer primary selection for read-only native sessions", async () => {
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([
      { ...CONNECTED_NON_PRIMARY, read_only: true },
    ]);
    renderSection();

    await waitFor(() => expect(screen.getByText(/upstox.*read-only.*connected/i)).toBeInTheDocument());

    expect(screen.queryByLabelText(/set upstox UPX1 as primary/i)).not.toBeInTheDocument();
    expect(setPrimaryBrokerAccount).not.toHaveBeenCalled();
  });
});

describe("BrokersSection — disconnect feedback", () => {
  const CONNECTED_ACCOUNT = makeNativeAccount({
    account_id: "UPX1",
    broker: "upstox",
    label: "Upstox",
    status: "connected",
    needs_relogin: false,
  });

  beforeEach(() => {
    vi.clearAllMocks();
    (listNativeBrokers as ReturnType<typeof vi.fn>).mockResolvedValue(BROKERS);
    (listBrokerMcpCatalogue as ReturnType<typeof vi.fn>).mockResolvedValue(MCP_BROKERS);
    (listBrokerAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([CONNECTED_ACCOUNT]);
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
  });

  it("shows a confirmation after disconnecting an account", async () => {
    (removeBrokerAccount as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/disconnect upstox UPX1/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/disconnect upstox UPX1/i));

    await waitFor(() =>
      expect(removeBrokerAccount).toHaveBeenCalledWith(
        expect.objectContaining({ source: "native", broker: "upstox", account_id: "UPX1" }),
      ),
    );
    expect(await screen.findByText(/upstox account UPX1 disconnected/i)).toBeInTheDocument();
  });

  it("surfaces disconnect failures instead of failing silently", async () => {
    (removeBrokerAccount as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Vault is locked"));
    renderSection();
    await waitFor(() => expect(screen.getByLabelText(/disconnect upstox UPX1/i)).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText(/disconnect upstox UPX1/i));

    expect(await screen.findByRole("alert")).toHaveTextContent("Vault is locked");
  });
});
