/**
 * PresetSection — Settings section for managing workspace presets.
 *
 * Features:
 *   - Lists all presets (built-in + custom) in a responsive card grid
 *   - Built-in presets show a "Built-in" badge; they cannot be edited or deleted
 *   - "Fork" on a built-in preset creates a named custom copy
 *   - "Edit" on a custom preset opens an inline form
 *   - "Delete" on a custom preset shows a confirmation then calls the API
 *   - "Create New Preset" opens a form: name, description, widget selection
 *   - "Export" downloads the preset as a JSON file
 *   - "Import" uploads a JSON file and creates a new custom preset
 *
 * API:
 *   GET    /ft-api/api/v1/presets/          → list all
 *   POST   /ft-api/api/v1/presets/          → create custom
 *   PUT    /ft-api/api/v1/presets/:id       → update custom
 *   DELETE /ft-api/api/v1/presets/:id       → delete custom
 *   POST   /ft-api/api/v1/presets/:id/fork  → fork built-in → custom
 */

import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Upload,
  Download,
  Copy,
  Pencil,
  Trash2,
  Check,
  X,
  LayoutTemplate,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { SectionTitle } from "./shared";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  listPresets,
  createPreset,
  updatePreset,
  deletePreset,
  forkPreset,
  type WorkspacePresetRecord,
  type CreatePresetPayload,
  type PresetWidgetEntry,
} from "@/services/ftApi";
import { widgetCatalog } from "@/layout/widgetFactory";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type FormMode = "idle" | "create" | "edit" | "fork";

interface PresetFormState {
  name: string;
  description: string;
  selectedWidgets: string[]; // widget component ids
  targetId: string; // preset id being edited/forked (empty for create)
}

const EMPTY_FORM: PresetFormState = {
  name: "",
  description: "",
  selectedWidgets: [],
  targetId: "",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildWidgetEntries(componentIds: string[]): PresetWidgetEntry[] {
  return componentIds.map((id, index) => ({
    id: `${id}-${index}`,
    component: id,
    title:
      widgetCatalog.find((w) => w.id === id)?.name ?? id,
  }));
}

function downloadJson(data: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// WidgetSelector — multi-select grid of widgets from the catalog
// ---------------------------------------------------------------------------

interface WidgetSelectorProps {
  selected: string[];
  onChange: (selected: string[]) => void;
}

function WidgetSelector({ selected, onChange }: WidgetSelectorProps) {
  const [expanded, setExpanded] = useState(false);
  const categories = ["Trading", "Analysis", "Utility"] as const;

  function toggle(id: string) {
    onChange(
      selected.includes(id)
        ? selected.filter((s) => s !== id)
        : [...selected, id],
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-secondary">
          Widgets
          {selected.length > 0 && (
            <span className="ml-1.5 text-accent font-medium">
              ({selected.length} selected)
            </span>
          )}
        </p>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-xs text-text-muted hover:text-text-primary transition-colors"
          aria-expanded={expanded}
          aria-label="Toggle widget list"
        >
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          {expanded ? "Collapse" : "Choose widgets"}
        </button>
      </div>

      {expanded && (
        <div
          className="rounded border border-border-default bg-surface-card overflow-y-auto"
          style={{ maxHeight: "280px" }}
        >
          {categories.map((cat) => {
            const widgets = widgetCatalog.filter((w) => w.category === cat);
            return (
              <div key={cat}>
                <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted bg-surface-base border-b border-border-default sticky top-0">
                  {cat}
                </p>
                <div className="grid grid-cols-2 gap-0">
                  {widgets.map((w) => {
                    const isSelected = selected.includes(w.id);
                    return (
                      <button
                        key={w.id}
                        type="button"
                        onClick={() => toggle(w.id)}
                        aria-pressed={isSelected}
                        title={w.description}
                        className={`flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors border-b border-border-default/50 ${
                          isSelected
                            ? "bg-accent/10 text-accent"
                            : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                        }`}
                      >
                        <span
                          className={`w-3.5 h-3.5 flex-none rounded-sm border transition-colors flex items-center justify-center ${
                            isSelected
                              ? "border-accent bg-accent/20"
                              : "border-border-default"
                          }`}
                          aria-hidden="true"
                        >
                          {isSelected && <Check size={9} className="text-accent" />}
                        </span>
                        {w.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Selected chips */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {selected.map((id) => {
            const name = widgetCatalog.find((w) => w.id === id)?.name ?? id;
            return (
              <span
                key={id}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent border border-accent/20"
              >
                {name}
                <button
                  type="button"
                  onClick={() => toggle(id)}
                  aria-label={`Remove ${name}`}
                  className="hover:text-loss transition-colors"
                >
                  <X size={9} />
                </button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PresetForm — inline create / edit / fork form
// ---------------------------------------------------------------------------

interface PresetFormProps {
  mode: "create" | "edit" | "fork";
  initial: PresetFormState;
  onSubmit: (form: PresetFormState) => void;
  onCancel: () => void;
  isPending: boolean;
}

function PresetForm({
  mode,
  initial,
  onSubmit,
  onCancel,
  isPending,
}: PresetFormProps) {
  const [form, setForm] = useState<PresetFormState>(initial);

  const heading =
    mode === "create"
      ? "New Preset"
      : mode === "fork"
        ? "Fork Preset"
        : "Edit Preset";

  function update(field: keyof PresetFormState, value: string | string[]) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    onSubmit(form);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-accent/30 bg-surface-card p-4 space-y-4 mb-4"
      aria-label={`${heading} form`}
    >
      <p className="text-xs font-semibold text-accent">{heading}</p>

      {/* Name */}
      <div className="space-y-1">
        <label
          htmlFor="preset-name"
          className="block text-xs text-text-secondary"
        >
          Name <span className="text-loss">*</span>
        </label>
        <input
          id="preset-name"
          type="text"
          value={form.name}
          onChange={(e) => update("name", e.target.value)}
          placeholder="e.g. Morning Scalper Setup"
          required
          className="w-full px-3 py-1.5 text-xs font-mono bg-surface-base border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/20 transition-colors"
        />
      </div>

      {/* Description */}
      <div className="space-y-1">
        <label
          htmlFor="preset-description"
          className="block text-xs text-text-secondary"
        >
          Description
        </label>
        <input
          id="preset-description"
          type="text"
          value={form.description}
          onChange={(e) => update("description", e.target.value)}
          placeholder="Brief summary of what this layout is for"
          className="w-full px-3 py-1.5 text-xs font-mono bg-surface-base border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/20 transition-colors"
        />
      </div>

      {/* Widget selector */}
      <WidgetSelector
        selected={form.selectedWidgets}
        onChange={(sel) => update("selectedWidgets", sel)}
      />

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <Button
          type="submit"
          disabled={isPending || !form.name.trim()}
          size="sm"
          className="text-xs"
        >
          {isPending ? "Saving…" : mode === "create" ? "Create" : "Save"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          disabled={isPending}
          className="text-xs text-text-muted"
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// PresetCard — single preset card
// ---------------------------------------------------------------------------

interface PresetCardProps {
  preset: WorkspacePresetRecord;
  onFork: (preset: WorkspacePresetRecord) => void;
  onEdit: (preset: WorkspacePresetRecord) => void;
  onDelete: (preset: WorkspacePresetRecord) => void;
  onExport: (preset: WorkspacePresetRecord) => void;
}

function PresetCard({
  preset,
  onFork,
  onEdit,
  onDelete,
  onExport,
}: PresetCardProps) {
  const isBuiltin = preset.source === "builtin";

  return (
    <div
      className="flex flex-col rounded-lg border border-border-default bg-surface-card p-4 gap-3 hover:border-border-hover transition-colors"
      aria-label={`Preset: ${preset.name}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <LayoutTemplate
            size={15}
            className="flex-none text-accent/70"
            aria-hidden="true"
          />
          <p className="text-xs font-semibold text-text-primary truncate">
            {preset.name}
          </p>
        </div>
        {isBuiltin ? (
          <Badge
            variant="secondary"
            className="text-[10px] shrink-0 bg-surface-hover text-text-muted border-border-default"
          >
            Built-in
          </Badge>
        ) : (
          <Badge
            variant="secondary"
            className="text-[10px] shrink-0 bg-profit/10 text-profit border-profit/20"
          >
            Custom
          </Badge>
        )}
      </div>

      {/* Description */}
      {preset.description && (
        <p className="text-[11px] text-text-muted leading-relaxed line-clamp-2">
          {preset.description}
        </p>
      )}

      {/* Widget count */}
      <p className="text-[10px] text-text-muted">
        {preset.widget_count}{" "}
        {preset.widget_count === 1 ? "widget" : "widgets"}
      </p>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-wrap mt-auto pt-1 border-t border-border-default/50">
        {isBuiltin ? (
          <button
            type="button"
            onClick={() => onFork(preset)}
            title="Create a customisable copy of this preset"
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
            aria-label={`Fork ${preset.name}`}
          >
            <Copy size={11} aria-hidden="true" />
            Fork
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => onEdit(preset)}
              title="Edit this preset"
              className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              aria-label={`Edit ${preset.name}`}
            >
              <Pencil size={11} aria-hidden="true" />
              Edit
            </button>
            <button
              type="button"
              onClick={() => onDelete(preset)}
              title="Delete this preset"
              className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-text-secondary hover:text-loss hover:bg-loss/5 transition-colors"
              aria-label={`Delete ${preset.name}`}
            >
              <Trash2 size={11} aria-hidden="true" />
              Delete
            </button>
          </>
        )}
        <button
          type="button"
          onClick={() => onExport(preset)}
          title="Download preset as JSON"
          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors ml-auto"
          aria-label={`Export ${preset.name}`}
        >
          <Download size={11} aria-hidden="true" />
          Export
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DeleteConfirmDialog — inline confirmation without using Radix Dialog
// ---------------------------------------------------------------------------

interface DeleteConfirmProps {
  preset: WorkspacePresetRecord | null;
  isPending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function DeleteConfirmDialog({
  preset,
  isPending,
  onConfirm,
  onCancel,
}: DeleteConfirmProps) {
  if (!preset) return null;

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={`Confirm delete ${preset.name}`}
      className="rounded-lg border border-loss/30 bg-surface-card p-4 space-y-3 mb-4"
    >
      <p className="text-xs font-semibold text-loss">Delete Preset?</p>
      <p className="text-xs text-text-secondary">
        <span className="text-text-primary font-medium">{preset.name}</span>{" "}
        will be permanently deleted. This cannot be undone.
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={onConfirm}
          disabled={isPending}
          className="text-xs"
          aria-label="Confirm delete"
        >
          {isPending ? "Deleting…" : "Delete"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          disabled={isPending}
          className="text-xs text-text-muted"
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PresetSection — main export
// ---------------------------------------------------------------------------

export function PresetSection() {
  const queryClient = useQueryClient();
  const importRef = useRef<HTMLInputElement>(null);

  const [formMode, setFormMode] = useState<FormMode>("idle");
  const [formState, setFormState] = useState<PresetFormState>(EMPTY_FORM);
  const [deleteTarget, setDeleteTarget] =
    useState<WorkspacePresetRecord | null>(null);
  const [importError, setImportError] = useState<string>("");

  // ---------------------------------------------------------------------------
  // Queries
  // ---------------------------------------------------------------------------

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["presets"],
    queryFn: listPresets,
  });

  const presets: WorkspacePresetRecord[] = data?.presets ?? [];
  const builtinPresets = presets.filter((p) => p.source === "builtin");
  const customPresets = presets.filter((p) => p.source === "custom");

  // ---------------------------------------------------------------------------
  // Mutations
  // ---------------------------------------------------------------------------

  const createMutation = useMutation({
    mutationFn: (payload: CreatePresetPayload) => createPreset(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["presets"] });
      setFormMode("idle");
      setFormState(EMPTY_FORM);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...payload }: { id: string } & CreatePresetPayload) =>
      updatePreset(id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["presets"] });
      setFormMode("idle");
      setFormState(EMPTY_FORM);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deletePreset(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["presets"] });
      setDeleteTarget(null);
    },
  });

  const forkMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      forkPreset(id, name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["presets"] });
      setFormMode("idle");
      setFormState(EMPTY_FORM);
    },
  });

  const anyPending =
    createMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending ||
    forkMutation.isPending;

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  function handleOpenCreate() {
    setDeleteTarget(null);
    setFormState(EMPTY_FORM);
    setFormMode("create");
  }

  function handleOpenEdit(preset: WorkspacePresetRecord) {
    setDeleteTarget(null);
    setFormState({
      name: preset.name,
      description: preset.description,
      selectedWidgets: preset.widgets.map((w) => w.component),
      targetId: preset.id,
    });
    setFormMode("edit");
  }

  function handleOpenFork(preset: WorkspacePresetRecord) {
    setDeleteTarget(null);
    setFormState({
      name: `${preset.name} (copy)`,
      description: preset.description,
      selectedWidgets: preset.widgets.map((w) => w.component),
      targetId: preset.id,
    });
    setFormMode("fork");
  }

  function handleCancel() {
    setFormMode("idle");
    setFormState(EMPTY_FORM);
  }

  function handleFormSubmit(form: PresetFormState) {
    const widgets = buildWidgetEntries(form.selectedWidgets);

    if (formMode === "create") {
      createMutation.mutate({
        name: form.name,
        description: form.description,
        widgets,
      });
    } else if (formMode === "edit") {
      updateMutation.mutate({
        id: form.targetId,
        name: form.name,
        description: form.description,
        widgets,
      });
    } else if (formMode === "fork") {
      forkMutation.mutate({ id: form.targetId, name: form.name });
    }
  }

  const handleExport = useCallback((preset: WorkspacePresetRecord) => {
    const filename = `flinttrade-preset-${preset.id}.json`;
    downloadJson(preset, filename);
  }, []);

  function handleDeleteRequest(preset: WorkspacePresetRecord) {
    setFormMode("idle");
    setDeleteTarget(preset);
  }

  function handleDeleteConfirm() {
    if (!deleteTarget) return;
    deleteMutation.mutate(deleteTarget.id);
  }

  function handleImportClick() {
    setImportError("");
    importRef.current?.click();
  }

  function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const raw: unknown = JSON.parse(ev.target?.result as string);
        if (
          raw === null ||
          typeof raw !== "object" ||
          !("name" in raw) ||
          !("widgets" in raw)
        ) {
          setImportError(
            "Invalid preset file. Expected an object with `name` and `widgets`.",
          );
          return;
        }
        const parsed = raw as { name: string; description?: string; widgets: PresetWidgetEntry[] };
        createMutation.mutate({
          name: parsed.name,
          description: parsed.description ?? "",
          widgets: parsed.widgets,
        });
      } catch {
        setImportError("Failed to parse JSON. Please select a valid preset file.");
      }
    };
    reader.readAsText(file);
    // Reset so the same file can be re-imported
    e.target.value = "";
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  function renderGrid(items: WorkspacePresetRecord[]) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {items.map((preset) => (
          <PresetCard
            key={preset.id}
            preset={preset}
            onFork={handleOpenFork}
            onEdit={handleOpenEdit}
            onDelete={handleDeleteRequest}
            onExport={handleExport}
          />
        ))}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <SectionTitle>Workspace Presets</SectionTitle>

        <div className="flex items-center gap-2 pb-2">
          {/* Hidden file input for import */}
          <input
            ref={importRef}
            type="file"
            accept=".json,application/json"
            onChange={handleImportFile}
            className="sr-only"
            aria-hidden="true"
            tabIndex={-1}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleImportClick}
            className="text-xs gap-1.5"
            aria-label="Import preset from JSON file"
          >
            <Upload size={13} aria-hidden="true" />
            Import
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={handleOpenCreate}
            disabled={formMode !== "idle"}
            className="text-xs gap-1.5"
            aria-label="Create a new workspace preset"
          >
            <Plus size={13} aria-hidden="true" />
            New Preset
          </Button>
        </div>
      </div>

      {/* Import error */}
      {importError && (
        <p className="text-xs text-loss bg-loss/5 border border-loss/20 rounded px-3 py-2">
          {importError}
        </p>
      )}

      {/* Mutation error feedback */}
      {(createMutation.isError ||
        updateMutation.isError ||
        deleteMutation.isError ||
        forkMutation.isError) && (
        <p className="text-xs text-loss bg-loss/5 border border-loss/20 rounded px-3 py-2">
          {String(
            (createMutation.error ??
              updateMutation.error ??
              deleteMutation.error ??
              forkMutation.error) as Error,
          )}
        </p>
      )}

      {/* Inline form */}
      {formMode !== "idle" && (
        <PresetForm
          mode={formMode === "fork" ? "fork" : formMode}
          initial={formState}
          onSubmit={handleFormSubmit}
          onCancel={handleCancel}
          isPending={anyPending}
        />
      )}

      {/* Delete confirmation */}
      <DeleteConfirmDialog
        preset={deleteTarget}
        isPending={deleteMutation.isPending}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Loading */}
      {isLoading && (
        <p className="text-xs text-text-muted">Loading presets…</p>
      )}

      {/* Error */}
      {isError && (
        <p className="text-xs text-loss">
          Failed to load presets:{" "}
          {error instanceof Error ? error.message : "Unknown error"}
        </p>
      )}

      {/* Built-in presets */}
      {!isLoading && builtinPresets.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-semibold text-text-secondary">
            Built-in
            <span className="ml-2 text-text-muted font-normal">
              ({builtinPresets.length})
            </span>
          </p>
          {renderGrid(builtinPresets)}
        </div>
      )}

      {/* Custom presets */}
      {!isLoading && (
        <div className="space-y-3">
          <p className="text-xs font-semibold text-text-secondary">
            Custom
            <span className="ml-2 text-text-muted font-normal">
              ({customPresets.length})
            </span>
          </p>
          {customPresets.length === 0 ? (
            <p className="text-xs text-text-muted py-4 text-center border border-dashed border-border-default rounded-lg">
              No custom presets yet. Click "New Preset" or fork a built-in one.
            </p>
          ) : (
            renderGrid(customPresets)
          )}
        </div>
      )}
    </div>
  );
}
