/**
 * ObsidianWidget — browse the operator's Obsidian vault from the terminal.
 *
 * Read-only over VAULT CONTENT — /api/v1/ai/obsidian/* (status, notes, note,
 * search). The same vault the AI agent reads for context and journals
 * decisions into. Nothing here writes a note, and nothing touches the order
 * path.
 *
 * It is NOT read-only over CONFIGURATION: when the vault path is unset the
 * widget offers a path field and calls saveObsidianVaultPath, which writes
 * host-level config. The docstring used to claim "nothing here writes",
 * full stop, which was wrong about that one mutation.
 *
 * When the path is unset the status reports not-configured and the widget
 * shows a setup hint — it never fabricates notes.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookText, Search, ChevronLeft, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getObsidianStatus,
  listObsidianNotes,
  readObsidianNote,
  saveObsidianVaultPath,
  searchObsidianNotes,
} from "@/services/ftApi.ai";

export default function ObsidianWidget() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [vaultPathDraft, setVaultPathDraft] = useState("");
  const [savePathError, setSavePathError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ["obsidian", "status"],
    queryFn: getObsidianStatus,
    refetchInterval: 60_000,
  });

  const savePathMutation = useMutation({
    mutationFn: () => saveObsidianVaultPath(vaultPathDraft.trim()),
    onSuccess: () => {
      setSavePathError(null);
      void queryClient.invalidateQueries({ queryKey: ["obsidian"] });
    },
    onError: (err) => {
      setSavePathError(err instanceof Error ? err.message : "Could not save the path");
    },
  });
  const available = statusQuery.data?.available ?? false;

  const notesQuery = useQuery({
    queryKey: ["obsidian", "notes"],
    queryFn: listObsidianNotes,
    enabled: available && submitted === "",
  });
  const searchQuery = useQuery({
    queryKey: ["obsidian", "search", submitted],
    queryFn: () => searchObsidianNotes(submitted),
    enabled: available && submitted !== "",
  });
  const noteQuery = useQuery({
    queryKey: ["obsidian", "note", selected],
    queryFn: () => readObsidianNote(selected as string),
    enabled: selected !== null,
  });

  // --- Initial status load: don't flash "empty" before we know the vault state. ---
  if (statusQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <p className="text-xs text-text-muted">Connecting to vault…</p>
      </div>
    );
  }

  // --- Not configured / unavailable: honest setup hints, no fake notes. ---
  if (statusQuery.isSuccess && !statusQuery.data.configured) {
    return (
      <div className="flex flex-col h-full items-center justify-center p-4 text-center gap-2">
        <BookText size={20} className="text-text-muted" aria-hidden="true" />
        <p className="text-xs text-text-secondary">Obsidian vault not configured.</p>
        <p className="text-xxs text-text-muted">
          Enter the absolute path of your vault folder — it persists in the
          workspace (no restart needed).
        </p>
        <div className="flex w-full max-w-xs items-center gap-2">
          <Input
            value={vaultPathDraft}
            onChange={(e) => setVaultPathDraft(e.target.value)}
            placeholder="/path/to/your/vault"
            aria-label="Obsidian vault path"
            className="h-7 text-xxs"
          />
          <Button
            size="sm"
            variant="default"
            className="h-7 px-2 text-xxs"
            onClick={() => savePathMutation.mutate()}
            disabled={savePathMutation.isPending || !vaultPathDraft.trim()}
          >
            {savePathMutation.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
        {savePathError && (
          <p role="alert" className="text-xxs text-loss">
            {savePathError}
          </p>
        )}
      </div>
    );
  }
  if (statusQuery.isSuccess && statusQuery.data.configured && !available) {
    return (
      <div className="flex flex-col h-full items-center justify-center p-4 text-center gap-2">
        <BookText size={20} className="text-loss" aria-hidden="true" />
        <p className="text-xs text-text-secondary">Vault path not found.</p>
        <p className="text-xxs text-text-muted font-mono break-all">{statusQuery.data.vault_path}</p>
      </div>
    );
  }

  // --- Note viewer ---
  if (selected !== null) {
    return (
      <div className="flex flex-col h-full p-3 gap-2" data-testid="obsidian-widget">
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xxs"
            onClick={() => setSelected(null)}
            aria-label="Back to notes"
          >
            <ChevronLeft size={12} className="mr-1" aria-hidden="true" /> Back
          </Button>
          <span className="text-xs font-medium text-text-primary truncate">{selected}</span>
        </div>
        <div className="flex-1 overflow-y-auto rounded border border-border-default bg-surface-base p-3">
          {noteQuery.isLoading ? (
            <p className="text-xxs text-text-muted">Loading note…</p>
          ) : noteQuery.isError ? (
            <p className="text-xxs text-loss">Could not read this note.</p>
          ) : (
            <pre className="whitespace-pre-wrap text-xs font-mono text-text-secondary">
              {noteQuery.data?.content}
            </pre>
          )}
        </div>
      </div>
    );
  }

  // --- List / search ---
  const hits = searchQuery.data ?? [];
  const notes = notesQuery.data ?? [];

  return (
    <div className="flex flex-col h-full p-3 gap-3" data-testid="obsidian-widget">
      <div className="flex items-center gap-2">
        <BookText size={14} className="text-accent" aria-hidden="true" />
        <span className="text-sm font-semibold text-text-primary">Obsidian Vault</span>
      </div>

      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query.trim());
        }}
      >
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search notes…"
          aria-label="Search notes"
          className="h-7 text-xs"
        />
        <Button type="submit" size="sm" variant="outline" className="h-7 px-2" aria-label="Search">
          <Search size={12} aria-hidden="true" />
        </Button>
        {submitted !== "" && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xxs"
            onClick={() => {
              setQuery("");
              setSubmitted("");
            }}
          >
            Clear
          </Button>
        )}
      </form>

      <div className="flex-1 overflow-y-auto space-y-1" aria-label="Vault notes">
        {submitted !== "" ? (
          searchQuery.isLoading ? (
            <p className="text-xs text-text-muted py-2">Searching…</p>
          ) : hits.length === 0 ? (
            <p className="text-xs text-text-muted py-2">No notes match “{submitted}”.</p>
          ) : (
            hits.map((h) => (
              <button
                key={h.path}
                type="button"
                onClick={() => setSelected(h.path)}
                className="w-full text-left rounded border border-border-default bg-surface-base px-2 py-1.5 hover:bg-surface-card"
              >
                <p className="text-xs text-text-primary truncate flex items-center gap-1">
                  <FileText size={11} className="shrink-0 text-text-muted" aria-hidden="true" /> {h.path}
                </p>
                {h.snippet && <p className="text-xxs text-text-muted truncate mt-0.5">{h.snippet}</p>}
              </button>
            ))
          )
        ) : notesQuery.isLoading ? (
          <p className="text-xs text-text-muted py-2">Loading notes…</p>
        ) : notes.length === 0 ? (
          <p className="text-xs text-text-muted py-2">Vault is empty.</p>
        ) : (
          notes.map((path) => (
            <button
              key={path}
              type="button"
              onClick={() => setSelected(path)}
              className="w-full text-left rounded border border-border-default bg-surface-base px-2 py-1.5 hover:bg-surface-card text-xs text-text-primary truncate flex items-center gap-1"
            >
              <FileText size={11} className="shrink-0 text-text-muted" aria-hidden="true" /> {path}
            </button>
          ))
        )}
      </div>
    </div>
  );
}
