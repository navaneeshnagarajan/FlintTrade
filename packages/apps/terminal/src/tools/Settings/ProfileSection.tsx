/**
 * ProfileSection — the Profile Manager surface inside unified Settings.
 *
 * Single-operator model (operator == user == data principal), so "profile"
 * is intentionally light: an editable operator display name, the live session
 * context (mode + broker-gateway connection), quick links into the settings
 * sections that hold preferences and performance optimisations, and the
 * session-security actions (lock / sign out).
 *
 * Reachable from the avatar button (TopBar) and the quick-settings panel, both
 * of which deep-link to `/settings#profile`.
 */

import { useCallback } from "react";
import { Compass, FlaskConical, Zap, Wifi, WifiOff, Lock, LogOut } from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useAuthStore } from "@/stores/authStore";
import { SECTIONS, type SectionId } from "./settingsConfig";
import { SectionTitle, FieldRow, TextInput } from "./shared";

// ---------------------------------------------------------------------------
// Mode presentation
// ---------------------------------------------------------------------------

const MODE_META: Record<
  AppMode,
  { label: string; icon: typeof Compass; className: string }
> = {
  explore: {
    label: "Explore",
    icon: Compass,
    className: "bg-text-muted/15 text-text-secondary border-text-muted/25",
  },
  practice: {
    label: "Practice",
    icon: FlaskConical,
    className: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  },
  live: {
    label: "Live",
    icon: Zap,
    className: "bg-profit/15 text-profit border-profit/40",
  },
};

// Settings sections surfaced as "optimisation & preferences" quick links.
const QUICK_LINK_IDS: SectionId[] = [
  "appearance",
  "brokers",
  "risk",
  "monitoring",
  "dataPaths",
  "security",
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ProfileSection() {
  const name = useSettingsStore((s) => s.name);
  const setName = useSettingsStore((s) => s.setName);
  const experience = useSettingsStore((s) => s.experience);

  const mode = useModeStore((s) => s.mode);
  const connectionStatus = useConnectionStore((s) => s.status);
  const connected = connectionStatus === "connected";

  const authStatus = useAuthStore((s) => s.status);
  const username = useAuthStore((s) => s.username);
  const lockSession = useAuthStore((s) => s.setPinRequired);
  const signOut = useAuthStore((s) => s.setLoggedOut);

  const loggedIn = authStatus === "logged-in";

  // Navigate within Settings by mutating the hash — SettingsRoute listens for
  // `hashchange` and swaps the active section (no router import needed here).
  const jumpTo = useCallback((id: SectionId) => {
    window.location.hash = id;
  }, []);

  const modeMeta = MODE_META[mode];
  const ModeIcon = modeMeta.icon;
  const initial = (name.trim()[0] ?? "T").toUpperCase();

  const quickLinks = SECTIONS.filter((s) => QUICK_LINK_IDS.includes(s.id));

  return (
    <div className="space-y-6">
      <SectionTitle>Profile</SectionTitle>

      {/* Identity card -------------------------------------------------------- */}
      <div className="flex items-center gap-4 p-4 rounded-lg bg-surface-card border border-border-default">
        <div
          className="flex-none w-12 h-12 rounded-full bg-accent/15 border border-accent/30 flex items-center justify-center text-accent text-lg font-bold"
          aria-hidden="true"
        >
          {initial}
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-text-primary truncate">
            {name || "Trader"}
          </div>
          <div className="text-xs text-text-muted truncate">
            {loggedIn && username
              ? `Signed in as ${username}`
              : "Local operator · not signed in"}
            {" · "}
            <span className="capitalize">{experience}</span>
          </div>
        </div>
      </div>

      {/* Display name --------------------------------------------------------- */}
      <FieldRow
        label="Display name"
        hint="Shown on the profile button and welcome screen. Stored locally."
      >
        <TextInput
          value={name}
          onChange={setName}
          placeholder="Trader"
          aria-label="Operator display name"
        />
      </FieldRow>

      {/* Session context ------------------------------------------------------ */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Session
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border ${modeMeta.className}`}
          >
            <ModeIcon size={12} aria-hidden="true" />
            {modeMeta.label} mode
          </span>
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border ${
              connected
                ? "bg-profit/10 text-profit border-profit/30"
                : "bg-loss/10 text-loss border-loss/30"
            }`}
          >
            {connected ? (
              <Wifi size={12} aria-hidden="true" />
            ) : (
              <WifiOff size={12} aria-hidden="true" />
            )}
            {connected ? "Gateway connected" : "Gateway disconnected"}
          </span>
        </div>
      </div>

      {/* Preferences & optimisations ----------------------------------------- */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Preferences &amp; optimisation
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {quickLinks.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => jumpTo(id)}
              className="flex items-center gap-2 px-3 py-2 rounded border border-border-default bg-surface-card hover:bg-surface-hover text-xs text-text-secondary hover:text-text-primary transition-colors text-left"
              aria-label={`Open ${label} settings`}
            >
              <Icon size={13} className="flex-none text-text-muted" />
              <span className="truncate">{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Session security ----------------------------------------------------- */}
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Session security
        </p>
        {loggedIn ? (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={lockSession}
              className="flex items-center gap-2 px-3 py-2 rounded border border-border-default bg-surface-card hover:bg-surface-hover text-xs text-text-secondary hover:text-text-primary transition-colors"
            >
              <Lock size={13} className="flex-none" />
              Lock now
            </button>
            <button
              type="button"
              onClick={signOut}
              className="flex items-center gap-2 px-3 py-2 rounded border border-loss/30 bg-loss/5 hover:bg-loss/10 text-xs text-loss transition-colors"
            >
              <LogOut size={13} className="flex-none" />
              Sign out
            </button>
          </div>
        ) : (
          <p className="text-xs text-text-muted">
            No active broker session. Connect a broker account from{" "}
            <button
              type="button"
              onClick={() => jumpTo("brokers")}
              className="text-accent hover:underline"
            >
              Brokers settings
            </button>
            .
          </p>
        )}
      </div>
    </div>
  );
}
