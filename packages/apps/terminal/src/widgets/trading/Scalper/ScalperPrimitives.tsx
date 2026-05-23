// ─── Scalper — primitive UI sub-components ────────────────────────────────────

import { AlertTriangle, Minus, Plus, RefreshCw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { fmt2, fmtInt } from "./helpers";
import type { StatusType, TickMap } from "./types";

// ─── LtpBlock ─────────────────────────────────────────────────────────────────

export interface LtpBlockProps {
  label: string;
  symbol: string;
  exchange: string;
  ticks: TickMap;
  className?: string;
}

export function LtpBlock({ label, symbol, exchange, ticks, className = "" }: LtpBlockProps) {
  const key = `${exchange}:${symbol}`;
  const tick = ticks[key];
  const ltp = tick?.ltp ?? tick?.close ?? null;
  const close = tick?.prev_close ?? tick?.close ?? null;
  const chg = ltp != null && close ? ltp - close : null;
  const pct = chg != null && close ? (chg / close) * 100 : null;
  const up = chg == null ? null : chg >= 0;

  return (
    <div className={`flex items-baseline gap-1.5 ${className}`}>
      <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">{label}</span>
      <span className="font-mono text-sm font-bold text-text-primary">
        {ltp != null ? fmtInt(ltp) : "—"}
      </span>
      {chg != null && (
        <span className={`font-mono text-xs ${up ? "text-profit" : "text-loss"}`}>
          {up ? "+" : ""}{fmt2(chg)} ({up ? "+" : ""}{fmt2(pct)}%)
        </span>
      )}
    </div>
  );
}

// ─── Stepper ──────────────────────────────────────────────────────────────────

export interface StepperProps {
  label: string;
  value: string;
  onDec: () => void;
  onInc: () => void;
  sublabel?: string;
  large?: boolean;
  className?: string;
}

export function Stepper({ label, value, onDec, onInc, sublabel, large = false, className = "" }: StepperProps) {
  const btnSize = large ? "w-8 h-8" : "w-6 h-8";
  const iconSize = large ? 12 : 10;
  const valueClass = large
    ? "font-mono text-sm font-bold text-text-primary bg-surface-card border-y border-border-default px-2 h-8 flex items-center min-w-14 justify-center"
    : "font-mono text-sm font-bold text-text-primary bg-surface-card border-y border-border-default px-2 h-8 flex items-center min-w-12 justify-center";

  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">
        {label}
        {sublabel && <span className="text-text-disabled ml-1">{sublabel}</span>}
      </span>
      <div className="flex items-center">
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={onDec}
          aria-label={`Decrease ${label}`}
          className={`${btnSize} flex items-center justify-center text-text-muted hover:text-text-primary bg-surface-hover border border-border-default rounded-l-md rounded-r-none hover:bg-surface-card transition-colors`}
        >
          <Minus size={iconSize} />
        </Button>
        <span className={valueClass}>
          {value}
        </span>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={onInc}
          aria-label={`Increase ${label}`}
          className={`${btnSize} flex items-center justify-center text-text-muted hover:text-text-primary bg-surface-hover border border-border-default rounded-r-md rounded-l-none hover:bg-surface-card transition-colors`}
        >
          <Plus size={iconSize} />
        </Button>
      </div>
    </div>
  );
}

// ─── NumberInput ──────────────────────────────────────────────────────────────

export interface NumberInputProps {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  min?: number;
  placeholder?: string;
  className?: string;
}

export function NumberInput({
  label,
  value,
  onChange,
  min = 0,
  placeholder,
  className = "",
}: NumberInputProps) {
  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">
        {label}
      </span>
      <Input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        min={min}
        placeholder={placeholder}
        className="w-16 h-8 text-sm font-mono"
      />
    </div>
  );
}

// ─── ToggleGroup ──────────────────────────────────────────────────────────────

export interface ToggleGroupProps {
  label?: string;
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
  className?: string;
}

export function ToggleGroup({ label, value, options, onChange, className = "" }: ToggleGroupProps) {
  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      {label && (
        <span className="text-xxs text-text-muted uppercase tracking-wider font-sans">{label}</span>
      )}
      <div role="radiogroup" aria-label={label} className="flex border border-border-default rounded-md overflow-hidden">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            role="radio"
            aria-checked={value === opt}
            onClick={() => onChange(opt)}
            className={`px-2.5 h-8 text-xs font-semibold transition-colors ${
              value === opt
                ? "bg-accent/15 text-accent border-accent/40"
                : "bg-surface-hover text-text-secondary hover:text-text-primary"
            }`}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── StatusPill ───────────────────────────────────────────────────────────────

export interface StatusPillProps {
  message: string;
  type?: StatusType;
}

export function StatusPill({ message, type = "idle" }: StatusPillProps) {
  if (!message) return null;
  const colors: Record<StatusType, string> = {
    success: "text-profit bg-profit/10 border-profit/30",
    error:   "text-loss bg-loss/10 border-loss/30",
    pending: "text-warning bg-warning/10 border-warning/30",
    idle:    "text-text-muted bg-surface-hover border-border-default",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-xs font-mono ${colors[type]}`}
    >
      {type === "pending" && <RefreshCw size={10} className="animate-spin" />}
      {type === "error" && <AlertTriangle size={10} />}
      {message}
    </span>
  );
}

// ─── ActionButton ─────────────────────────────────────────────────────────────

export interface ActionButtonProps {
  onClick: () => void;
  disabled?: boolean;
  title: string;
  variant: "buy" | "sell" | "neutral" | "warning";
  icon: React.ReactNode;
  label: string;
  shortcut: string;
  "aria-label"?: string;
}

export function ActionButton({
  onClick,
  disabled = false,
  title,
  variant,
  icon,
  label,
  shortcut,
  "aria-label": ariaLabel,
}: ActionButtonProps) {
  const variantClasses: Record<string, string> = {
    buy:     "bg-profit/10 text-profit border-profit/30 hover:bg-profit/20",
    sell:    "bg-loss/10 text-loss border-loss/30 hover:bg-loss/20",
    neutral: "bg-surface-card text-text-muted border-border-default hover:bg-surface-hover",
    warning: "bg-surface-card text-text-muted border-border-default hover:bg-surface-hover",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2 border text-sm font-semibold transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${variantClasses[variant]}`}
    >
      <span className="flex items-center gap-1">
        {icon}
        {label}
      </span>
      <span className="text-xxs text-text-disabled font-sans font-normal">{shortcut}</span>
    </button>
  );
}
