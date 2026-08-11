/**
 * PresetPicker — workspace template selector + lifecycle management.
 *
 * Two concerns handled here:
 *
 * 1. Preset picker (original) — dialog listing built-in workspace presets.
 *    Selecting a preset clears the canvas and applies the chosen layout.
 *
 * 2. Workspace lifecycle (new) — CRUD operations on named workspaces:
 *    - New from Template — clones a preset as a named workspace
 *    - Clone Current     — duplicates the active workspace with a new name
 *    - Rename            — inline rename via Dialog
 *    - Delete            — with confirmation Dialog
 *
 *    Workspace data is persisted to localStorage under `flinttrade:workspaces`.
 *    The layoutStore `tabs` are considered the primary source of truth for the
 *    workspace canvas; the workspaces here store the human-readable metadata
 *    (name, createdAt) and reference back to a tab id.
 */

import { useState, useCallback, useEffect } from "react";
import {
  Zap, Grid3x3, Star, BarChart3, ShieldAlert, TrendingUp,
  Sigma, Map, Bot, PieChart, Globe, Gauge, Box,
  Crosshair, LayoutDashboard, LayoutGrid, Columns3,
  Plus, Copy, Pencil, Trash2, MoreHorizontal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useLayoutStore } from "@/stores/layoutStore";
import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";
import {
  reconcileWorkspaceStore,
  useWorkspaceLifecycle,
  WorkspaceStorageError,
} from "./hooks/useWorkspaceLifecycle";

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, LucideIcon> = {
  Zap, Grid3x3, Star, BarChart3, ShieldAlert, TrendingUp,
  Sigma, Map, Bot, PieChart, Globe, Gauge,
  Crosshair, LayoutDashboard, LayoutGrid, Columns3,
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface PresetPickerProps {
  isOpen: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Dialogs — Rename
// ---------------------------------------------------------------------------

interface RenameDialogProps {
  open: boolean;
  workspaceId: string;
  currentName: string;
  error: string | null;
  onConfirm: (name: string) => void;
  onCancel: () => void;
}

function RenameDialog({
  open,
  workspaceId,
  currentName,
  error,
  onConfirm,
  onCancel,
}: RenameDialogProps) {
  const [name, setName] = useState(currentName);
  useEffect(() => {
    setName(currentName);
  }, [open, workspaceId, currentName]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (trimmed) onConfirm(trimmed);
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent className="sm:max-w-sm bg-surface-card border-border-default">
        <DialogHeader>
          <DialogTitle className="text-sm font-semibold text-text-primary">
            Rename Workspace
          </DialogTitle>
          <DialogDescription className="text-xs text-text-muted">
            Enter a new name for this workspace.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="rounded border border-red-800 bg-red-950/60 px-3 py-2 text-xs text-red-200">
            {error}
          </p>
        )}
        <form onSubmit={handleSubmit}>
          <div className="py-2">
            <Label htmlFor="workspace-name" className="text-xs text-text-muted mb-1 block">
              Name
            </Label>
            <Input
              id="workspace-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              maxLength={64}
              className="h-8 text-sm bg-surface-base border-border-default text-text-primary"
            />
          </div>
          <DialogFooter className="mt-3 gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onCancel}
              className="h-7 text-xs text-text-muted hover:text-text-primary"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={!name.trim()}
              className="h-7 text-xs"
            >
              Rename
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Dialogs — Delete confirmation
// ---------------------------------------------------------------------------

interface DeleteDialogProps {
  open: boolean;
  workspaceName: string;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

function DeleteDialog({ open, workspaceName, error, onConfirm, onCancel }: DeleteDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent className="sm:max-w-sm bg-surface-card border-border-default">
        <DialogHeader>
          <DialogTitle className="text-sm font-semibold text-text-primary">
            Delete Workspace
          </DialogTitle>
          <DialogDescription className="text-xs text-text-muted">
            Delete <span className="text-text-primary font-medium">"{workspaceName}"</span>?
            This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="rounded border border-red-800 bg-red-950/60 px-3 py-2 text-xs text-red-200">
            {error}
          </p>
        )}
        <DialogFooter className="mt-4 gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}
            className="h-7 text-xs text-text-muted hover:text-text-primary"
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={onConfirm}
            className="h-7 text-xs bg-red-900 hover:bg-red-800 text-red-100"
          >
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Main PresetPicker component
// ---------------------------------------------------------------------------

export default function PresetPicker({ isOpen, onClose }: PresetPickerProps) {
  const applyPreset = useLayoutStore((s) => s.applyPreset);
  const activeTabId = useLayoutStore((s) => s.activeTabId);
  const layoutStorageError = useLayoutStore((s) => s.layoutStorageError);
  const tabs = useLayoutStore((s) => s.tabs);
  const renameTab = useLayoutStore((s) => s.renameTab);
  const removeTab = useLayoutStore((s) => s.removeTab);
  const addTab = useLayoutStore((s) => s.addTab);
  const commitTabCreation = useLayoutStore((s) => s.commitTabCreation);
  const getTabLayout = useLayoutStore((s) => s.getTabLayout);
  const workspaceApi = useLayoutStore((s) => s.workspaceApi);
  const workspaceApiTabId = useLayoutStore((s) => s.workspaceApiTabId);

  const { cloneWorkspace, newFromTemplate, renameWorkspace, deleteWorkspace } = useWorkspaceLifecycle();

  // Sub-dialog state
  const [showRename, setShowRename] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [showTemplateClone, setShowTemplateClone] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [reconcileError, setReconcileError] = useState<string | null>(null);

  const activeTab = tabs.find((t) => t.id === activeTabId);
  const workspaceReady = layoutStorageError === null
    && workspaceApi !== null
    && workspaceApiTabId === activeTabId;
  const visibleError = workspaceError ?? layoutStorageError?.message ?? reconcileError;

  useEffect(() => {
    if (layoutStorageError) {
      setReconcileError(layoutStorageError.message);
      return;
    }
    try {
      const { metadataLessTabIds } = reconcileWorkspaceStore(tabs);
      for (const tabId of metadataLessTabIds) removeTab(tabId);
      setReconcileError(null);
    } catch (error) {
      const message = error instanceof WorkspaceStorageError
        ? error.message
        : `Workspace metadata could not be reconciled: ${error instanceof Error ? error.message : "unknown storage error"}`;
      setReconcileError(message);
    }
  }, [tabs, layoutStorageError, removeTab]);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleSelectPreset = useCallback(
    (presetId: string) => {
      if (!workspaceReady) {
        setWorkspaceError("Workspace is still loading. Try again in a moment.");
        return;
      }
      try {
        applyPreset(presetId);
      } catch (error) {
        setWorkspaceError(
          error instanceof Error ? error.message : "Workspace template could not be applied.",
        );
        return;
      }
      setWorkspaceError(null);
      onClose();
    },
    [workspaceReady, applyPreset, onClose]
  );

  const handleRenameConfirm = useCallback(
    (name: string) => {
      const result = renameWorkspace(activeTabId, activeTab?.name ?? "Workspace", name, renameTab);
      if (!result.ok) {
        setWorkspaceError(result.error);
        return;
      }
      setWorkspaceError(null);
      setShowRename(false);
    },
    [activeTabId, activeTab?.name, renameTab, renameWorkspace]
  );

  const handleDeleteConfirm = useCallback(() => {
    if (!activeTab || tabs.length <= 1) return;
    const layout = workspaceApi && workspaceApiTabId === activeTabId
      ? workspaceApi.toJSON() as unknown as Record<string, unknown>
      : getTabLayout(activeTabId);
    const result = deleteWorkspace(
      activeTabId,
      activeTab.name,
      layout,
      removeTab,
      addTab,
    );
    if (!result.ok) {
      setWorkspaceError(result.error);
      return;
    }
    setWorkspaceError(null);
    setShowDelete(false);
    onClose();
  }, [activeTab, tabs.length, activeTabId, workspaceApi, workspaceApiTabId, getTabLayout, deleteWorkspace, removeTab, addTab, onClose]);

  const handleCloneCurrent = useCallback(() => {
    if (activeTab) {
      const sourceLayout = workspaceApi && workspaceApiTabId === activeTab.id
        ? workspaceApi.toJSON() as unknown as Record<string, unknown>
        : getTabLayout(activeTab.id);
      const result = cloneWorkspace(
        activeTab.id,
        activeTab.name,
        addTab,
        removeTab,
        sourceLayout,
        commitTabCreation,
      );
      if (!result.ok) {
        setWorkspaceError(result.error);
        return;
      }
      setWorkspaceError(null);
      onClose();
    }
  }, [activeTab, cloneWorkspace, addTab, removeTab, workspaceApi, workspaceApiTabId, getTabLayout, commitTabCreation, onClose]);

  const handleNewFromTemplate = useCallback(
    (presetId: string) => {
      const preset = WORKSPACE_PRESETS.find((p) => p.id === presetId);
      if (!preset) return;
      const result = newFromTemplate(preset, addTab, removeTab, commitTabCreation);
      if (!result.ok) {
        setWorkspaceError(result.error);
        return;
      }
      setWorkspaceError(null);
      setShowTemplateClone(false);
      onClose();
    },
    [newFromTemplate, addTab, removeTab, commitTabCreation, onClose]
  );

  // ---------------------------------------------------------------------------
  // Render — template clone sub-dialog
  // ---------------------------------------------------------------------------

  if (showTemplateClone) {
    return (
      <Dialog open onOpenChange={(o) => { if (!o) setShowTemplateClone(false); }}>
        <DialogContent className="sm:max-w-3xl max-h-[85vh] flex flex-col bg-surface-card border-border-default p-0 animate-fade-in-scale">
          <DialogHeader className="px-6 pt-5 pb-4 border-b border-border-default shrink-0">
            <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
              New Workspace from Template
            </DialogTitle>
            <DialogDescription className="text-xs text-text-muted mt-0.5">
              Creates a new named workspace tab using the chosen template layout.
            </DialogDescription>
          </DialogHeader>
          {visibleError && (
            <p role="alert" className="mx-4 rounded border border-red-800 bg-red-950/60 px-3 py-2 text-xs text-red-200">
              {visibleError}
            </p>
          )}
          <div className="p-4 grid grid-cols-3 gap-3 overflow-y-auto flex-1 min-h-0">
            {WORKSPACE_PRESETS.map((preset) => {
              const Icon: LucideIcon = ICON_MAP[preset.icon] ?? Box;
              return (
                <button
                  key={preset.id}
                  onClick={() => handleNewFromTemplate(preset.id)}
                  className="flex items-start gap-3 p-4 rounded-lg border border-border-default hover:border-accent/50 hover:bg-surface-hover transition-colors text-left group"
                >
                  <div className="mt-0.5 shrink-0 p-2 rounded-md bg-surface-hover group-hover:bg-accent/10 transition-colors">
                    <Icon size={18} className="text-text-secondary group-hover:text-accent transition-colors" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-text-primary leading-tight">{preset.name}</p>
                    <p className="text-xs text-text-muted mt-1 leading-snug">{preset.description}</p>
                  </div>
                </button>
              );
            })}
          </div>
          <div className="px-6 pb-4 shrink-0 flex justify-end border-t border-border-default pt-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowTemplateClone(false)}
              className="h-7 text-xs text-text-muted hover:text-text-primary"
            >
              Cancel
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  // ---------------------------------------------------------------------------
  // Render — main preset picker
  // ---------------------------------------------------------------------------

  return (
    <>
      <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
        <DialogContent className="sm:max-w-3xl max-h-[85vh] flex flex-col bg-surface-card border-border-default p-0 animate-fade-in-scale">
          {/* Header with lifecycle menu */}
          <DialogHeader className="px-6 pt-5 pb-4 border-b border-border-default shrink-0">
            <div className="flex items-center justify-between">
              <div>
                <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
                  Choose a Workspace Template
                </DialogTitle>
                <DialogDescription className="text-xs text-text-muted mt-0.5">
                  Selecting a template replaces the current layout. Your saved workspaces
                  are not affected.
                </DialogDescription>
              </div>

              {/* Workspace lifecycle dropdown */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-text-muted hover:text-text-primary shrink-0"
                    aria-label="Workspace actions"
                  >
                    <MoreHorizontal size={15} />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  className="w-52 bg-surface-card border-border-default text-text-primary"
                >
                  <DropdownMenuItem
                    onClick={() => { setWorkspaceError(null); setShowTemplateClone(true); }}
                    className="text-xs gap-2 cursor-pointer hover:bg-surface-hover"
                  >
                    <Plus size={13} className="text-text-muted" />
                    New from Template
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={handleCloneCurrent}
                    className="text-xs gap-2 cursor-pointer hover:bg-surface-hover"
                  >
                    <Copy size={13} className="text-text-muted" />
                    Clone Current
                  </DropdownMenuItem>
                  <DropdownMenuSeparator className="bg-border-default" />
                  <DropdownMenuItem
                    onClick={() => { setWorkspaceError(null); setShowRename(true); }}
                    className="text-xs gap-2 cursor-pointer hover:bg-surface-hover"
                  >
                    <Pencil size={13} className="text-text-muted" />
                    Rename "{activeTab?.name ?? "Workspace"}"
                  </DropdownMenuItem>
                  <DropdownMenuSeparator className="bg-border-default" />
                  <DropdownMenuItem
                    onClick={() => { setWorkspaceError(null); setShowDelete(true); }}
                    disabled={tabs.length <= 1}
                    className="text-xs gap-2 cursor-pointer text-red-400 hover:text-red-300 hover:bg-red-950 focus:text-red-300 focus:bg-red-950 disabled:opacity-40"
                  >
                    <Trash2 size={13} />
                    Delete "{activeTab?.name ?? "Workspace"}"
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </DialogHeader>

          {visibleError && (
            <p role="alert" className="mx-4 rounded border border-red-800 bg-red-950/60 px-3 py-2 text-xs text-red-200">
              {visibleError}
            </p>
          )}

          {/* Preset grid */}
          <div className="p-4 grid grid-cols-3 gap-3 overflow-y-auto flex-1 min-h-0">
            {WORKSPACE_PRESETS.map((preset) => {
              const Icon: LucideIcon = ICON_MAP[preset.icon] ?? Box;
              return (
                <button
                  key={preset.id}
                  disabled={!workspaceReady}
                  onClick={() => handleSelectPreset(preset.id)}
                  className="flex items-start gap-3 p-4 rounded-lg border border-border-default hover:border-accent/50 hover:bg-surface-hover transition-colors text-left group disabled:cursor-wait disabled:opacity-50"
                >
                  <div className="mt-0.5 shrink-0 p-2 rounded-md bg-surface-hover group-hover:bg-accent/10 transition-colors">
                    <Icon
                      size={18}
                      className="text-text-secondary group-hover:text-accent transition-colors"
                    />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-text-primary leading-tight">
                      {preset.name}
                    </p>
                    <p className="text-xs text-text-muted mt-1 leading-snug">
                      {preset.description}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
        </DialogContent>
      </Dialog>

      {/* Rename dialog */}
      <RenameDialog
        open={showRename}
        workspaceId={activeTabId}
        currentName={activeTab?.name ?? "Workspace"}
        error={visibleError}
        onConfirm={handleRenameConfirm}
        onCancel={() => { setWorkspaceError(null); setShowRename(false); }}
      />

      {/* Delete confirmation dialog */}
      <DeleteDialog
        open={showDelete}
        workspaceName={activeTab?.name ?? "Workspace"}
        error={visibleError}
        onConfirm={handleDeleteConfirm}
        onCancel={() => { setWorkspaceError(null); setShowDelete(false); }}
      />
    </>
  );
}
