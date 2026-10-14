import { StrictMode, useCallback, useState, type CSSProperties } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { QueryProvider } from "../src/providers/QueryProvider";
import { useAuthStore } from "../src/stores/authStore";
import { useBrokerStore } from "../src/stores/brokerStore";
import { useModeStore } from "../src/stores/modeStore";
import { useBrokerAccounts } from "../src/hooks/useBrokerAccounts";
import { useTradingStoreSync } from "../src/hooks/useTradingStoreSync";
import { WelcomeCard } from "../src/routes/home/WelcomeCard";
import { PositionsCard } from "../src/routes/home/PositionsCard";
import TradeJournalTool from "../src/tools/TradeJournal/TradeJournalTool";
import ModeHonestyBar from "../src/chrome/ModeHonestyBar";
import TerminalRoute from "../src/routes/TerminalRoute";
import DailyWelcome from "../src/components/welcome/DailyWelcome";
import { usePrimaryBanner } from "../src/hooks/usePrimaryBannerKind";
import { OperatorStatusStrip } from "../src/chrome/OperatorStatusStrip";
import { Button } from "../src/components/ui/button";
import { onlineManager, useQueryClient, type Query } from "@tanstack/react-query";
import "../src/index.css";

// Keep the original unpadded fixture-control geometry when using the shared
// primitive. These styles belong only to synthetic controls, never consumers.
const fixtureButtonStyle: CSSProperties = {
  display: "inline-block", height: "auto", padding: 0, borderWidth: 0,
  borderRadius: 0, font: "inherit", color: "inherit", background: "transparent",
  boxShadow: "none", whiteSpace: "normal", flexShrink: 1,
};
const isAccountBook = (query: Query) =>
  ["funds", "positions", "tradebook", "orders"].includes(String(query.queryKey[0]));

const view = new URLSearchParams(window.location.search).get("view");
// Read-only observation, installed by the already-mounted entry. Re-importing
// a Vite HTML entry for diagnostics can execute createRoot a second time.
Object.defineProperty(window, "__foundationNetworkObservation", {
  value: () => ({ navigatorOnline: navigator.onLine, queryOnline: onlineManager.isOnline() }),
  writable: false,
});

// The currently wired risk owners. This is still a bounded composition, not
// AppLayout; the dormant recovery component is not a co-mounted shell owner.
function WiredRiskConsumers() {
  const { kind, incident } = usePrimaryBanner();
  return <>
    {kind ? <OperatorStatusStrip kind={kind} incident={incident} /> : null}
    <div style={{ height: 620 }}><TerminalRoute /></div>
  </>;
}

// Component coverage only: DailyWelcome has no current production mount path.
// Keep its real query/scope owner and complete copy without inventing a home.
function DormantRecoveryConsumer() {
  const [welcome, setWelcome] = useState(false);
  const dismiss = useCallback(() => setWelcome(false), []);
  return <>
    <Button type="button" style={fixtureButtonStyle} onClick={() => setWelcome(true)}>Open recovery notice</Button>
    {welcome ? <DailyWelcome onDismiss={dismiss} /> : null}
  </>;
}

/** Bounded composition of the real shared lifecycle and real consumers.
 * No replacement query client, decoder, readiness, transport or aggregate data.
 * Deliberately excludes unrelated shell feeds; this is not full-route acceptance.
 */
function FoundationLifecycle() {
  const queryClient = useQueryClient();
  const [sessionEnabled, setSessionEnabled] = useState(true);
  const mode = useModeStore((state) => state.mode);
  const authenticated = useAuthStore((state) => state.status === "logged-in");
  const accounts = useBrokerStore((state) => state.accounts);
  const activeAccount = useBrokerStore((state) => state.activeAccountId);
  useBrokerAccounts(authenticated && mode !== "explore");
  useTradingStoreSync(authenticated && sessionEnabled);
  return <>
    <header className="p-3 border-b border-border-default text-text-primary">
      <h1>Foundation truth — synthetic presentation only</h1>
      <div className="flex flex-wrap gap-3 mt-2">
        <label>Account <select aria-label="Synthetic account selection" value={activeAccount ?? ""}
          onChange={(event) => useBrokerStore.getState().setActiveAccount(event.target.value)}>
          {accounts.map((account) => <option key={`${account.source}:${account.broker}:${account.account_id}`}
            value={`${account.source}:${account.broker}:${account.account_id}`}>{account.account_id}</option>)}
        </select></label>
        <Button type="button" style={fixtureButtonStyle} onClick={() => useModeStore.getState().setMode("practice")}>Select Practice</Button>
        <Button type="button" style={fixtureButtonStyle} onClick={() => useModeStore.getState().setMode("explore")}>Select Explore</Button>
        <Button type="button" style={fixtureButtonStyle} onClick={() => useModeStore.getState().setMode("live")}>Select Live</Button>
        <Button type="button" style={fixtureButtonStyle} onClick={() => setSessionEnabled(false)}>Disable aggregate session</Button>
        <Button type="button" style={fixtureButtonStyle} onClick={() => useAuthStore.getState().setPinRequired()}>Lock synthetic session</Button>
        <Button type="button" style={fixtureButtonStyle} onClick={() => useAuthStore.getState().setLoggedOut()}>Log out synthetic session</Button>
        <Button type="button" style={fixtureButtonStyle} onClick={() => {
          void queryClient.invalidateQueries({ predicate: isAccountBook });
        }}>Refresh account books</Button>
        <Button type="button" style={fixtureButtonStyle} onClick={() => {
          void queryClient.invalidateQueries({ refetchType: "none", predicate: isAccountBook });
        }}>Mark account books stale</Button>
      </div>
    </header>
    <ModeHonestyBar mode={mode} />
    <main className="p-3">
      {view === "wired-risk" ? <WiredRiskConsumers /> : view === "dormant-recovery" ? <DormantRecoveryConsumer />
        : view === "session" ? <div style={{ height: 660 }}><TradeJournalTool onClose={() => undefined} /></div>
        : <div className="grid grid-cols-1 md:grid-cols-2 gap-3"><WelcomeCard /><PositionsCard /></div>}
    </main>
  </>;
}
function FoundationRoot() {
  const authenticated = useAuthStore((state) => state.status === "logged-in");
  return <QueryProvider><BrowserRouter>{authenticated ? <FoundationLifecycle /> : <p>Awaiting synthetic authentication</p>}</BrowserRouter></QueryProvider>;
}
const root = document.getElementById("root");
if (!root) throw new Error("Foundation fixture root is missing");
createRoot(root).render(<StrictMode><FoundationRoot /></StrictMode>);
