/**
 * FormulaBuilder — compact editor for user-defined watchlist formula columns
 * (W1). Users name a formula and enter an arithmetic expression over quote
 * fields; the expression is validated by the safe {@link compileFormula} engine
 * before it can be added (no eval, no arbitrary JS).
 */

import { useState } from "react";
import { Plus, Trash2, Check } from "lucide-react";
import { compileFormula, FORMULA_FIELD_NAMES } from "./formulaEngine";
import type { WatchlistCustomFormula } from "./types";

export interface FormulaBuilderProps {
  customFormulas: WatchlistCustomFormula[];
  onAdd: (name: string, expression: string) => void;
  onRemove: (id: string) => void;
}

export function FormulaBuilder({ customFormulas, onAdd, onRemove }: FormulaBuilderProps) {
  const [name, setName] = useState("");
  const [expression, setExpression] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleAdd = () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Give the formula a name");
      return;
    }
    const compiled = compileFormula(expression);
    if (!compiled.ok) {
      setError(compiled.error);
      return;
    }
    onAdd(trimmedName, expression.trim());
    setName("");
    setExpression("");
    setError(null);
  };

  return (
    <div className="mt-3 border-t border-border-default pt-2">
      <div className="text-xs text-text-secondary mb-1">Custom formulas</div>

      {customFormulas.length > 0 && (
        <div className="space-y-1 mb-2">
          {customFormulas.map((f) => (
            <div key={f.id} className="flex items-center gap-2 rounded px-1.5 py-1 bg-surface-elevated text-xs">
              <span className="text-text-primary font-medium truncate">{f.name}</span>
              <span className="text-[10px] text-text-muted font-mono truncate flex-1">{f.expression}</span>
              <button
                type="button"
                onClick={() => onRemove(f.id)}
                aria-label={`Delete formula ${f.name}`}
                className="text-text-muted hover:text-loss shrink-0"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1">
        <input
          type="text"
          value={name}
          onChange={(e) => { setName(e.target.value); setError(null); }}
          placeholder="Name (e.g. Range %)"
          aria-label="Formula name"
          className="w-full rounded border border-border-default bg-surface-elevated px-2 py-1 text-xs text-text-primary"
        />
        <input
          type="text"
          value={expression}
          onChange={(e) => { setExpression(e.target.value); setError(null); }}
          placeholder="(high - low) / ltp * 100"
          aria-label="Formula expression"
          className="w-full rounded border border-border-default bg-surface-elevated px-2 py-1 text-xs text-text-primary font-mono"
          onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
        />
        <button
          type="button"
          onClick={handleAdd}
          className="flex items-center gap-1 rounded bg-accent/15 hover:bg-accent/25 text-accent px-2 py-1 text-xs w-full justify-center"
        >
          {error ? <Check size={12} className="opacity-0" /> : <Plus size={12} />}
          Add formula
        </button>
      </div>

      {error ? (
        <p className="mt-1 text-[10px] text-loss">{error}</p>
      ) : (
        <p className="mt-1 text-[10px] text-text-muted">Fields: {FORMULA_FIELD_NAMES.join(", ")}</p>
      )}
    </div>
  );
}
