/**
 * PersonaStep — persona picker and name input for the setup wizard.
 * Used in Quick (step 1), Guided (step 0), and Advanced (step 0).
 */

import {
  BookOpen,
  PiggyBank,
  CandlestickChart,
  Zap,
  Workflow,
  Bot,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Persona = "trader" | "investor" | "beginner";
export type ExperienceLevel = "new" | "intermediate" | "professional";

// ---------------------------------------------------------------------------
// PersonaPicker
// ---------------------------------------------------------------------------

interface PersonaPickerProps {
  selected: Persona | null;
  onSelect: (p: Persona) => void;
}

export function PersonaPicker({ selected, onSelect }: PersonaPickerProps) {
  const options: Array<{ value: Persona; label: string; description: string; hint: string }> = [
    {
      value: "trader",
      label: "Active Trader",
      description: "F&O, intraday, scalping",
      hint: "Full terminal with order pad, depth, Greeks",
    },
    {
      value: "investor",
      label: "Investor",
      description: "Equity, long-term, SIP",
      hint: "Portfolio overview with holdings dashboard",
    },
    {
      value: "beginner",
      label: "Learner",
      description: "Learning markets, paper trading",
      hint: "Guided workspace with explanations",
    },
  ];

  return (
    <div className="space-y-3">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          aria-label={`Select ${opt.label} persona`}
          onClick={() => onSelect(opt.value)}
          className={[
            "w-full text-left rounded-lg border p-4 transition-colors duration-150",
            selected === opt.value
              ? "border-accent/40 bg-accent/15"
              : "border-border-default bg-surface-base hover:border-accent/40",
          ].join(" ")}
        >
          <div className="flex items-center justify-between">
            <span className="text-text-primary font-medium text-sm">{opt.label}</span>
            <Badge
              variant="outline"
              className={[
                "text-xs border-border-default",
                selected === opt.value ? "border-accent/40 text-accent" : "text-text-muted",
              ].join(" ")}
            >
              {opt.description}
            </Badge>
          </div>
          <p className="text-text-muted text-xs mt-1">{opt.hint}</p>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ExperiencePicker
// ---------------------------------------------------------------------------

interface ExperiencePickerProps {
  selected: ExperienceLevel | null;
  onSelect: (e: ExperienceLevel) => void;
}

export function ExperiencePicker({ selected, onSelect }: ExperiencePickerProps) {
  const options: Array<{ value: ExperienceLevel; label: string; description: string }> = [
    { value: "new",          label: "New to markets",   description: "Less than 1 year"          },
    { value: "intermediate", label: "Intermediate",     description: "1-3 years of trading"      },
    { value: "professional", label: "Professional",     description: "3+ years, active strategies" },
  ];

  return (
    <div className="space-y-3">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          aria-label={`Select ${opt.label} experience level`}
          onClick={() => onSelect(opt.value)}
          className={[
            "w-full text-left rounded-lg border p-4 transition-colors duration-150",
            selected === opt.value
              ? "border-accent/40 bg-accent/15"
              : "border-border-default bg-surface-base hover:border-accent/40",
          ].join(" ")}
        >
          <span className="text-text-primary font-medium text-sm block">{opt.label}</span>
          <span className="text-text-muted text-xs">{opt.description}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interest constants and picker
// ---------------------------------------------------------------------------

export const INTERESTS = [
  { id: "learning",    label: "Learning & Education", icon: BookOpen,        desc: "Market basics, strategies, paper trading"   },
  { id: "investing",   label: "Investing",            icon: PiggyBank,       desc: "Mutual funds, SIPs, portfolio, net worth"   },
  { id: "trading",     label: "Trading",              icon: CandlestickChart, desc: "F&O scalping, options, intraday"           },
  { id: "backtesting", label: "Backtesting",          icon: Zap,             desc: "Strategy testing, walk-forward, optimization" },
  { id: "automation",  label: "Automation",           icon: Workflow,        desc: "Flow builder, cron jobs, alerts"            },
  { id: "ai",          label: "AI & Analysis",        icon: Bot,             desc: "LLM advisor, sentiment, signals"            },
] as const;

interface InterestPickerProps {
  selected: string[];
  onToggle: (id: string) => void;
}

export function InterestPicker({ selected, onToggle }: InterestPickerProps) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {INTERESTS.map((interest) => {
        const Icon: LucideIcon = interest.icon;
        const isSelected = selected.includes(interest.id);
        return (
          <button
            key={interest.id}
            type="button"
            aria-label={`${isSelected ? "Deselect" : "Select"} ${interest.label} interest`}
            aria-pressed={isSelected}
            onClick={() => onToggle(interest.id)}
            className={[
              "text-left rounded-lg border p-4 transition-colors duration-150",
              isSelected
                ? "bg-accent/10 border-accent/40 ring-1 ring-accent/20"
                : "bg-surface-card border-border-default hover:border-accent/30 hover:bg-surface-hover",
            ].join(" ")}
          >
            <div className="flex items-center gap-2.5 mb-1.5">
              <Icon className={["size-4", isSelected ? "text-accent" : "text-text-muted"].join(" ")} />
              <span className={["text-sm font-medium", isSelected ? "text-accent" : "text-text-primary"].join(" ")}>
                {interest.label}
              </span>
            </div>
            <p className={["text-xs leading-relaxed", isSelected ? "text-accent/70" : "text-text-muted"].join(" ")}>
              {interest.desc}
            </p>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// NameInput
// ---------------------------------------------------------------------------

interface NameInputProps {
  value: string;
  onChange: (name: string) => void;
}

export function NameInput({ value, onChange }: NameInputProps) {
  return (
    <div className="space-y-1.5">
      <Label className="text-text-secondary text-xs uppercase tracking-wider">
        What should we call you?
      </Label>
      <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Trader"
          aria-label="Your name or display name"
          className="h-9 text-sm border-border-default rounded-md font-sans bg-surface-base text-text-primary"
        />
      </div>
    </div>
  );
}
