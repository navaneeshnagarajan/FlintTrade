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
 *    Dockview canvas; the workspaces here store the human-readable metadata
 *    (name, createdAt) and reference back to a tab id.
 */

import { useState, useCallback } from "react";
import {
  Zap, Grid3x3, Star, BarChart3, ShieldAlert, TrendingUp,
  Sigma, Map, Bot, PieChart, Globe, Gauge, Box,
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
import { useWorkspaceLifecycle } from "./hooks/useWorkspaceLifecycle";

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, LucideIcon> = {
  Zap, Grid3x3, Star, BarChart3, ShieldAlert, TrendingUp,
  Sigma, Map, Bot, PieChart, Globe, Gauge,
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
  currentName: string;
  onConfirm: (name: string) => void;
  onCancel: () => void;
}

function RenameDialog({ open, currentName, onConfirm, onCancel }: RenameDialogProps) {
  const [name, setName] = useState(currentName);

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
  onConfirm: () => void;
  onCancel: () => void;
}

function DeleteDialog({ open, workspaceName, onConfirm, onCancel }: DeleteDialogProps) {
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
  const tabs = useLayoutStore((s) => s.tabs);
  const renameTab = useLayoutStore((s) => s.renameTab);
  const removeTab = useLayoutStore((s) => s.removeTab);
  const addTab = useLayoutStore((s) => s.addTab);

  const { cloneWorkspace, newFromTemplate } = useWorkspaceLifecycle();

  // Sub-dialog state
  const [showRename, setShowRename] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [showTemplateClone, setShowTemplateClone] = useState(false);

  const activeTab = tabs.find((t) => t.id === activeTabId);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleSelectPreset = useCallback(
    (presetId: string) => {
      applyPreset(presetId);
      onClose();
    },
    [applyPreset, onClose]
  );

  const handleRenameConfirm = useCallback(
    (name: string) => {
      renameTab(activeTabId, name);
      setShowRename(false);
    },
    [activeTabId, renameTab]
  );

  const handleDeleteConfirm = useCallback(() => {
    removeTab(activeTabId);
    setShowDelete(false);
    onClose();
  }, [activeTabId, removeTab, onClose]);

  const handleCloneCurrent = useCallback(() => {
    if (activeTab) {
      cloneWorkspace(activeTab.id, activeTab.name);
      onClose();
    }
  }, [activeTab, cloneWorkspace, onClose]);

  const handleNewFromTemplate = useCallback(
    (presetId: string) => {
      const preset = WORKSPACE_PRESETS.find((p) => p.id === presetId);
      if (!preset) return;
      newFromTemplate(preset, addTab, applyPreset);
      setShowTemplateClone(false);
      onClose();
    },
    [newFromTemplate, addTab, applyPreset, onClose]
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
                    onClick={() => setShowTemplateClone(true)}
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
                    onClick={() => setShowRename(true)}
                    className="text-xs gap-2 cursor-pointer hover:bg-surface-hover"
                  >
                    <Pencil size={13} className="text-text-muted" />
                    Rename "{activeTab?.name ?? "Workspace"}"
                  </DropdownMenuItem>
                  <DropdownMenuSeparator className="bg-border-default" />
                  <DropdownMenuItem
                    onClick={() => setShowDelete(true)}
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

          {/* Preset grid */}
          <div className="p-4 grid grid-cols-3 gap-3 overflow-y-auto flex-1 min-h-0">
            {WORKSPACE_PRESETS.map((preset) => {
              const Icon: LucideIcon = ICON_MAP[preset.icon] ?? Box;
              return (
                <button
                  key={preset.id}
                  onClick={() => handleSelectPreset(preset.id)}
                  className="flex items-start gap-3 p-4 rounded-lg border border-border-default hover:border-accent/50 hover:bg-surface-hover transition-colors text-left group"
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
        currentName={activeTab?.name ?? "Workspace"}
        onConfirm={handleRenameConfirm}
        onCancel={() => setShowRename(false)}
      />

      {/* Delete confirmation dialog */}
      <DeleteDialog
        open={showDelete}
        workspaceName={activeTab?.name ?? "Workspace"}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setShowDelete(false)}
      />
    </>
  );
}
