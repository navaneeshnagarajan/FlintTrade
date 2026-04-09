/**
 * ExpressionInput.tsx — Textarea for flow node expression fields.
 *
 * Features:
 * - Highlights {{...}} tokens in accent colour via overlay technique
 * - Shows autocomplete dropdown for available variables on {{ trigger
 * - Validates expression syntax on blur and reports unresolved paths
 * - Fully controlled: value/onChange follow standard React patterns
 */

import { useRef, useState, useCallback, useId } from "react";
import { Label } from "@/components/ui/label";
import { validateExpression, extractTokenPaths } from "./expressionEvaluator";
import type { ExpressionContext } from "./expressionEvaluator";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ExpressionInputProps {
  /** Field label shown above the textarea. */
  label: string;
  /** Current expression value. */
  value: string;
  /** Called whenever the expression changes. */
  onChange: (value: string) => void;
  /** Placeholder shown when empty. */
  placeholder?: string;
  /** Help text shown below the textarea. */
  helpText?: string;
  /**
   * Context used for autocomplete suggestions and validation.
   * Keys should be dot-path prefixes available in the flow (e.g. "upstream.placeOrder").
   */
  context?: ExpressionContext;
  /** Additional suggestion strings beyond those derived from context. */
  extraSuggestions?: string[];
  /** Whether the field is required. */
  required?: boolean;
  /** Whether the field is disabled. */
  disabled?: boolean;
}

// ---------------------------------------------------------------------------
// Token highlighter
// ---------------------------------------------------------------------------

const TOKEN_REGEX = /\{\{([^}]+?)\}\}/g;

interface HighlightSegment {
  text: string;
  isToken: boolean;
}

/**
 * Splits a template string into plain-text and token segments for rendering.
 */
function splitIntoSegments(text: string): HighlightSegment[] {
  const segments: HighlightSegment[] = [];
  let lastIndex = 0;

  TOKEN_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = TOKEN_REGEX.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index), isToken: false });
    }
    segments.push({ text: match[0], isToken: true });
    lastIndex = match.index + match[0].length;
  }
  TOKEN_REGEX.lastIndex = 0;

  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex), isToken: false });
  }
  return segments;
}

// ---------------------------------------------------------------------------
// Suggestion builder
// ---------------------------------------------------------------------------

const BUILTIN_SUGGESTIONS = ["$now", "$today", "$timestamp", "$env."];

/**
 * Builds a flat list of suggestion strings from context keys and extra list.
 * For nested objects, generates dot-path strings one level deep.
 */
function buildSuggestions(
  context: ExpressionContext,
  extras: string[]
): string[] {
  const suggestions: string[] = [...BUILTIN_SUGGESTIONS, ...extras];

  function walk(obj: unknown, prefix: string, depth: number): void {
    if (depth > 3) return; // cap recursion
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return;
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      const path = prefix ? `${prefix}.${k}` : k;
      suggestions.push(path);
      if (depth < 2) walk(v, path, depth + 1);
    }
  }

  walk(context, "", 0);
  // Deduplicate
  return [...new Set(suggestions)];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ExpressionInput({
  label,
  value,
  onChange,
  placeholder = "e.g. {{upstream.nodeName.output}}",
  helpText,
  context = {},
  extraSuggestions = [],
  required = false,
  disabled = false,
}: ExpressionInputProps) {
  const labelId = useId();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [showAutocomplete, setShowAutocomplete] = useState(false);
  const [autocompleteFilter, setAutocompleteFilter] = useState("");
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [isFocused, setIsFocused] = useState(false);

  const allSuggestions = buildSuggestions(context, extraSuggestions);
  const existingTokens = extractTokenPaths(value);

  // Merge existing token paths into suggestions so users see their own tokens.
  const mergedSuggestions = [...new Set([...allSuggestions, ...existingTokens])];

  const filteredSuggestions = autocompleteFilter
    ? mergedSuggestions.filter((s) =>
        s.toLowerCase().includes(autocompleteFilter.toLowerCase())
      )
    : mergedSuggestions;

  // ----- Handlers -----

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const v = e.target.value;
      onChange(v);

      // Show autocomplete when user types "{{"
      const cursor = e.target.selectionStart ?? v.length;
      const before = v.slice(0, cursor);
      const tokenStart = before.lastIndexOf("{{");
      const tokenEnd = before.lastIndexOf("}}");

      if (tokenStart !== -1 && tokenStart > tokenEnd) {
        // Inside an open token — extract partial path after "{{"
        const partial = before.slice(tokenStart + 2);
        setAutocompleteFilter(partial);
        setShowAutocomplete(true);
      } else {
        setShowAutocomplete(false);
        setAutocompleteFilter("");
      }
    },
    [onChange]
  );

  const handleBlur = useCallback(() => {
    setIsFocused(false);
    // Delay closing autocomplete so click on suggestion registers first.
    setTimeout(() => setShowAutocomplete(false), 150);

    // Validate expression
    const errors = validateExpression(value, context);
    setValidationErrors(errors);
  }, [value, context]);

  const handleFocus = useCallback(() => {
    setIsFocused(true);
    setValidationErrors([]);
  }, []);

  const insertSuggestion = useCallback(
    (suggestion: string) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      const cursor = textarea.selectionStart ?? value.length;
      const before = value.slice(0, cursor);
      const after = value.slice(cursor);

      // Find the opening "{{" before the cursor
      const tokenStart = before.lastIndexOf("{{");
      const tokenEnd = before.lastIndexOf("}}");
      let newValue: string;

      if (tokenStart !== -1 && tokenStart > tokenEnd) {
        // Replace partial token with completed one
        const prefix = before.slice(0, tokenStart);
        newValue = `${prefix}{{${suggestion}}}${after}`;
      } else {
        // No open token — insert a fresh one
        newValue = `${before}{{${suggestion}}}${after}`;
      }

      onChange(newValue);
      setShowAutocomplete(false);
      setAutocompleteFilter("");

      // Restore focus and move cursor after the inserted token
      requestAnimationFrame(() => {
        const insertEnd = newValue.indexOf(`{{${suggestion}}}`) + `{{${suggestion}}}`.length;
        textarea.focus();
        textarea.setSelectionRange(insertEnd, insertEnd);
      });
    },
    [value, onChange]
  );

  // ----- Highlighted overlay -----

  const segments = splitIntoSegments(value);

  const hasErrors = validationErrors.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, position: "relative" }}>
      {/* Label */}
      <Label
        htmlFor={labelId}
        style={{
          fontSize: 10,
          color: "var(--color-text-muted)",
          display: "flex",
          alignItems: "center",
          gap: 4,
        }}
      >
        {label}
        {required && (
          <span style={{ color: "#f87171", fontSize: 10 }} aria-hidden="true">
            *
          </span>
        )}
      </Label>

      {/* Textarea wrapper — overlay technique for token highlighting */}
      <div style={{ position: "relative" }}>
        {/*
          Highlight layer: absolutely positioned behind the textarea.
          Matches textarea font/size/padding exactly so characters align.
          Pointer events are off so the real textarea handles interaction.
        */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            padding: "6px 8px",
            fontFamily: "var(--font-mono, monospace)",
            fontSize: 11,
            lineHeight: "1.5",
            whiteSpace: "pre-wrap",
            overflowWrap: "break-word",
            wordBreak: "break-all",
            pointerEvents: "none",
            color: "transparent",
            zIndex: 1,
            borderRadius: 6,
            overflow: "hidden",
          }}
        >
          {segments.map((seg, i) =>
            seg.isToken ? (
              <span
                key={i}
                style={{
                  // Semi-transparent accent tint visible through transparent text layer
                  background: "#818cf833",
                  borderRadius: 3,
                  color: "#818cf8",
                  // Make the highlight visible since parent text is transparent
                  opacity: 1,
                }}
              >
                {seg.text}
              </span>
            ) : (
              <span key={i}>{seg.text}</span>
            )
          )}
        </div>

        {/* Real textarea (transparent text, so highlight shows through) */}
        <textarea
          id={labelId}
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onBlur={handleBlur}
          onFocus={handleFocus}
          placeholder={placeholder}
          disabled={disabled}
          rows={3}
          spellCheck={false}
          autoComplete="off"
          style={{
            position: "relative",
            zIndex: 2,
            width: "100%",
            padding: "6px 8px",
            fontFamily: "var(--font-mono, monospace)",
            fontSize: 11,
            lineHeight: "1.5",
            background: "var(--color-base)",
            border: `1px solid ${
              hasErrors && !isFocused
                ? "#f87171"
                : isFocused
                ? "var(--color-accent, #818cf8)"
                : "var(--color-border)"
            }`,
            borderRadius: 6,
            color: "var(--color-text)",
            resize: "vertical",
            outline: "none",
            display: "block",
            boxSizing: "border-box",
            whiteSpace: "pre-wrap",
            overflowWrap: "break-word",
            wordBreak: "break-all",
            transition: "border-color 0.15s",
          }}
          aria-describedby={helpText ? `${labelId}-help` : undefined}
          aria-required={required}
          aria-invalid={hasErrors && !isFocused}
        />
      </div>

      {/* Autocomplete dropdown */}
      {showAutocomplete && filteredSuggestions.length > 0 && (
        <div
          role="listbox"
          aria-label="Variable suggestions"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 50,
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
            maxHeight: 160,
            overflowY: "auto",
            marginTop: 2,
          }}
        >
          {filteredSuggestions.slice(0, 20).map((suggestion) => (
            <button
              key={suggestion}
              role="option"
              aria-selected={false}
              type="button"
              onMouseDown={(e) => {
                // mousedown fires before blur — prevent blur from hiding list first
                e.preventDefault();
                insertSuggestion(suggestion);
              }}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "4px 8px",
                fontFamily: "var(--font-mono, monospace)",
                fontSize: 10,
                color: "var(--color-text)",
                background: "none",
                border: "none",
                cursor: "pointer",
                transition: "background 0.1s",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background =
                  "var(--color-border)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "none";
              }}
            >
              <span style={{ color: "#818cf8" }}>{"{{"}</span>
              {suggestion}
              <span style={{ color: "#818cf8" }}>{"}}"}</span>
            </button>
          ))}
        </div>
      )}

      {/* Validation errors */}
      {hasErrors && !isFocused && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {validationErrors.map((err) => (
            <p
              key={err}
              style={{
                fontSize: 9,
                color: "#f87171",
                margin: 0,
                fontFamily: "var(--font-mono, monospace)",
              }}
            >
              Unresolved: {`{{${err}}}`}
            </p>
          ))}
        </div>
      )}

      {/* Help text */}
      {helpText && (
        <p
          id={`${labelId}-help`}
          style={{ fontSize: 9, color: "var(--color-text-muted)", margin: 0 }}
        >
          {helpText}
        </p>
      )}
    </div>
  );
}
