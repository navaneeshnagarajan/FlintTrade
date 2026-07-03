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
  MessageCircle,
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
  type LucideIcon,
} from "lucide-react";

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
  | "whatsapp"
  | "dataPaths"
  | "security"
  | "monitoring"
  | "skill"
  | "presets"
  | "about";

export interface SectionDef {
  id: SectionId;
  label: string;
  icon: LucideIcon;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const SECTIONS: SectionDef[] = [
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
  { id: "whatsapp",   label: "WhatsApp",           icon: MessageCircle },
  { id: "dataPaths",  label: "Data Paths",         icon: HardDrive    },
  { id: "security",   label: "Security",           icon: ShieldCheck  },
  { id: "monitoring", label: "Monitoring",         icon: Activity     },
  { id: "skill",      label: "Skill & Experience", icon: GraduationCap   },
  { id: "presets",    label: "Workspace Presets",  icon: LayoutTemplate  },
  { id: "about",      label: "About",              icon: Info            },
];
