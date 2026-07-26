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

export interface SectionDef {
  id: SectionId;
  label: string;
  icon: LucideIcon;
}

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
export function buildSections(desktopShell: boolean): SectionDef[] {
  const sections: SectionDef[] = [
    { id: "profile",    label: "Profile",            icon: UserCircle   },
    { id: "general",    label: "General",           icon: Monitor      },
    { id: "appearance", label: "Appearance",         icon: Palette      },
    { id: "ticker",     label: "Ticker Bar",         icon: Rss          },
    { id: "api",        label: "Broker Gateway",     icon: Wifi         },
    { id: "brokers",    label: "Brokers",            icon: Landmark     },
    { id: "trading",    label: "Trading Defaults",   icon: TrendingUp   },
    { id: "risk",       label: "Risk Limits",        icon: ShieldAlert  },
    { id: "leverage",   label: "Leverage",           icon: Scale        },
    { id: "practice",   label: "Practice Mode",      icon: FlaskConical },
    { id: "keyboard",   label: "Keyboard Shortcuts", icon: Keyboard     },
    { id: "llm",        label: "LLM Config",         icon: Brain        },
    { id: "telegram",   label: "Telegram",           icon: Send         },
    { id: "dataPaths",  label: "Data Paths",         icon: HardDrive    },
    { id: "security",   label: "Security",           icon: ShieldCheck  },
    { id: "monitoring", label: "Monitoring",         icon: Activity     },
    { id: "skill",      label: "Skill & Experience", icon: GraduationCap   },
    { id: "presets",    label: "Workspace Presets",  icon: LayoutTemplate  },
  ];
  if (desktopShell) {
    sections.push({ id: "updates", label: "Updates", icon: Download });
  }
  sections.push({ id: "support", label: "Report Bug", icon: Bug });
  sections.push({ id: "about", label: "About", icon: Info });
  return sections;
}

export const SECTIONS: SectionDef[] = buildSections(isDesktopShell());
