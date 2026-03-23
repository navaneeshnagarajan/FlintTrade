/**
 * shared — reusable form primitives for Settings sections.
 * All components match the FlintTrade terminal theme.
 */

import { useEffect } from "react";
import { CheckCircle2 } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SelectOption {
  value: string;
  label: string;
}

// ---------------------------------------------------------------------------
// FieldLabel
// ---------------------------------------------------------------------------

export function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-xs text-text-secondary mb-1">{children}</label>
  );
}

// ---------------------------------------------------------------------------
// TextInput
// ---------------------------------------------------------------------------

interface TextInputProps {
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  type?: string;
  disabled?: boolean;
  "aria-label"?: string;
}

export function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
  disabled = false,
  "aria-label": ariaLabel,
}: TextInputProps) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      aria-label={ariaLabel}
      className="w-full px-3 py-1.5 text-xs font-mono bg-surface-base border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    />
  );
}

// ---------------------------------------------------------------------------
// SelectInput
// ---------------------------------------------------------------------------

interface SelectInputProps {
  value: string;
  onChange: (val: string) => void;
  options: SelectOption[];
  "aria-label"?: string;
}

export function SelectInput({ value, onChange, options, "aria-label": ariaLabel }: SelectInputProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel}
      className="w-full px-3 py-1.5 text-xs bg-surface-base border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/20 transition-colors appearance-none cursor-pointer"
    >
      {options.map(({ value: v, label }) => (
        <option key={v} value={v}>{label}</option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// SegmentControl
// ---------------------------------------------------------------------------

interface SegmentControlProps {
  value: string;
  onChange: (val: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  "aria-label"?: string;
}

export function SegmentControl({
  value,
  onChange,
  options,
  disabled = false,
  "aria-label": ariaLabel,
}: SegmentControlProps) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={`flex items-center bg-surface-base border border-border-default rounded overflow-hidden w-fit ${disabled ? "opacity-50 pointer-events-none" : ""}`}
    >
      {options.map(({ value: v, label }) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          disabled={disabled}
          aria-pressed={v === value}
          className={`px-3 py-1 text-xs transition-colors ${
            v === value
              ? "bg-accent/15 text-accent font-medium"
              : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toggle
// ---------------------------------------------------------------------------

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}

export function Toggle({ checked, onChange, label }: ToggleProps) {
  return (
    <label className="flex items-center gap-2.5 cursor-pointer w-fit">
      <div
        role="switch"
        aria-checked={checked}
        aria-label={label}
        tabIndex={0}
        onClick={() => onChange(!checked)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onChange(!checked);
          }
        }}
        className={`relative inline-flex h-4 w-7 shrink-0 cursor-pointer rounded-full border border-transparent transition-colors focus:outline-none focus:ring-1 focus:ring-accent/30 ${
          checked ? "bg-accent" : "bg-surface-hover border-border-default"
        }`}
      >
        <span
          className={`pointer-events-none inline-block h-3 w-3 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
            checked ? "translate-x-3" : "translate-x-0.5"
          }`}
        />
      </div>
      <span className="text-xs text-text-secondary">{label}</span>
    </label>
  );
}

// ---------------------------------------------------------------------------
// FieldRow
// ---------------------------------------------------------------------------

export function FieldRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <FieldLabel>{label}</FieldLabel>
      {children}
      {hint && <p className="text-xs text-text-muted mt-0.5">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SectionTitle
// ---------------------------------------------------------------------------

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-heading font-semibold text-sm text-text-primary mb-4 pb-2 border-b border-border-default">
      {children}
    </h2>
  );
}

// ---------------------------------------------------------------------------
// InlineToast
// ---------------------------------------------------------------------------

interface ToastProps {
  message: string;
  onDismiss: () => void;
}

export function InlineToast({ message, onDismiss }: ToastProps) {
  useEffect(() => {
    const id = setTimeout(onDismiss, 3000);
    return () => clearTimeout(id);
  }, [onDismiss]);

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded text-xs border bg-profit/10 border-profit/20 text-profit">
      <CheckCircle2 size={13} className="flex-none" />
      <span>{message}</span>
    </div>
  );
}
