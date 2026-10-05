/**
 * settingsConfig — shared section definitions for SettingsRoute.
 *
 * Extracted so the full-page settings route and any consumers use the same
 * section IDs, labels, and icons without duplicating them.
 */

import {
  Monitor,
  Palette,
  Wifi,
  TrendingUp,
  ShieldAlert,
  Keyboard,
  Brain,
  Send,
  HardDrive,
  ShieldCheck,
  Activity,
  GraduationCap,
  Info,
  Scale,
  FlaskConical,
  LayoutTemplate,
  Rss,
  UserCircle,
  Landmark,
  Download,
  Bug,
  type LucideIcon,
} from "lucide-react";
import { isDesktopShell } from "@/lib/desktopShell";
import { isPublicDemoBuild } from "@/lib/demoSession";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SectionId =
  | "profile"
  | "general"
  | "appearance"
  | "ticker"
  | "api"
  | "brokers"
  | "trading"
  | "risk"
  | "leverage"
  | "practice"
  | "keyboard"
  | "llm"
  | "telegram"
  | "dataPaths"
  | "security"
  | "monitoring"
  | "skill"
  | "presets"
  | "updates"
  | "support"
  | "about";

export type SectionGroupId = "account" | "preferences" | "trading" | "integrations" | "system";

export interface SectionDef {
  id: SectionId;
  label: string;
  icon: LucideIcon;
  group: SectionGroupId;
}

/** Headings for the Settings section nav, in display order. */
export const SECTION_GROUPS: readonly { id: SectionGroupId; label: string }[] = [
  { id: "account", label: "Account" },
  { id: "preferences", label: "Preferences" },
  { id: "trading", label: "Trading" },
  { id: "integrations", label: "AI & alerts" },
  { id: "system", label: "System" },
];

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Build the visible section list.
 *
   * The Updates section drives the desktop shell's binary-first updater (with a
   * source-rebuild fallback), so it only exists inside the desktop app — web
   * builds must not show it at all.
 */
/**
 * Sections that collect a real secret, and are therefore absent from the public
 * hosted demo.
 *
 * Gating /setup and /setup-account was not sufficient: ExploreRoute's "Demo
 * Mode" button signs in the `demo-user` sentinel and navigates to /home, from
 * where Settings is reachable and renders these. Nothing can be SAVED - the
 * sentinel is not a JWT, so every guarded write 401s - but the harm was never
 * theft. It is that a visitor types a real API key, broker password, bot token
 * or account PIN into a public origin, where a password manager offers to store
 * it against that origin.
 */
export const DEMO_HIDDEN_SECTIONS: readonly SectionId[] = [
  "api",       // OpenAlgo host + API key
  "brokers",   // broker account credentials
  "llm",       // LLM provider API keys
  "telegram",  // bot token
  "security",  // account password and PIN
];

export function buildSections(desktopShell: boolean, publicDemo: boolean = isPublicDemoBuild()): SectionDef[] {
  // Listed in SECTION_GROUPS order so keyboard order matches what is on screen.
  const sections: SectionDef[] = [
    { id: "profile",    label: "Profile",            icon: UserCircle,     group: "account" },
    { id: "security",   label: "Security",           icon: ShieldCheck,    group: "account" },
    { id: "general",    label: "General",            icon: Monitor,        group: "preferences" },
    { id: "appearance", label: "Appearance",         icon: Palette,        group: "preferences" },
    { id: "ticker",     label: "Ticker Bar",         icon: Rss,            group: "preferences" },
    { id: "keyboard",   label: "Keyboard Shortcuts", icon: Keyboard,       group: "preferences" },
    { id: "skill",      label: "Skill & Experience", icon: GraduationCap,  group: "preferences" },
    { id: "presets",    label: "Workspace Presets",  icon: LayoutTemplate, group: "preferences" },
    { id: "brokers",    label: "Brokers",            icon: Landmark,       group: "trading" },
    { id: "api",        label: "Broker Gateway",     icon: Wifi,           group: "trading" },
    { id: "trading",    label: "Trading Defaults",   icon: TrendingUp,     group: "trading" },
    { id: "risk",       label: "Risk Limits",        icon: ShieldAlert,    group: "trading" },
    { id: "leverage",   label: "Leverage",           icon: Scale,          group: "trading" },
    { id: "practice",   label: "Practice Mode",      icon: FlaskConical,   group: "trading" },
    { id: "llm",        label: "AI",         icon: Brain,          group: "integrations" },
    { id: "telegram",   label: "Telegram",           icon: Send,           group: "integrations" },
    { id: "dataPaths",  label: "Data Paths",         icon: HardDrive,      group: "system" },
    { id: "monitoring", label: "Monitoring",         icon: Activity,       group: "system" },
  ];
  if (desktopShell) {
    sections.push({ id: "updates", label: "Updates", icon: Download, group: "system" });
  }
  sections.push({ id: "support", label: "Report Bug", icon: Bug, group: "system" });
  sections.push({ id: "about", label: "About", icon: Info, group: "system" });
  if (publicDemo) {
    return sections.filter((section) => !DEMO_HIDDEN_SECTIONS.includes(section.id));
  }
  return sections;
}

export const SECTIONS: SectionDef[] = buildSections(isDesktopShell());
