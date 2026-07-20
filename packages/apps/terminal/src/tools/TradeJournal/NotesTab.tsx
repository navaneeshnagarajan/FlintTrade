/**
 * NotesTab — backend-persisted daily trading notes.
 *
 * Notes key on the IST trading day (Asia/Kolkata) and live in the journal
 * store (`/api/v1/journal/notes/<date>`), loaded through TanStack Query and
 * saved through a debounced mutation. The header label is honest about save
 * state: "auto-saved" only after the last PUT succeeded, "saving…" while an
 * edit is pending or in flight, and "not saved — backend unreachable" on
 * failure. When the note load itself fails, editing is disabled behind a
 * Retry affordance so keystrokes can never overwrite an unloaded note.
 * Legacy localStorage notes are imported once on mount (skipped in Explore
 * mode); the current IST day is never imported while the tab is mounted, and
 * each key is removed only after its PUT succeeds.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { useModeStore } from "@/stores/modeStore";
import { getDailyNote, putDailyNote } from "@/services/ftApi.journal";
import { NOTES_KEY, istDayKey } from "./utils";

/** Quiet period between the last keystroke and the auto-save PUT. */
const SAVE_DEBOUNCE_MS = 800;

/** Legacy localStorage key prefix: ``flinttrade_journal_notes_<YYYY-MM-DD>``. */
const LEGACY_NOTE_PREFIX = `${NOTES_KEY}_`;

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

function readLegacyNoteKeys(): string[] {
  const keys: string[] = [];
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key && key.startsWith(LEGACY_NOTE_PREFIX)) keys.push(key);
    }
  } catch {
    // Storage unavailable — nothing to import.
  }
  return keys;
}

/**
 * One-time import of legacy localStorage notes into the backend.
 *
 * The current IST day is NEVER imported while the tab is mounted: that day is
 * simultaneously editable in this component, so importing it races the
 * debounced save in both directions (the legacy PUT can replace freshly typed
 * keystrokes, or the draft save can overwrite the just-imported note whose
 * localStorage copy was already removed). Today's key survives untouched and
 * imports on a later mount once the day has passed.
 *
 * Every other date is re-checked with ``getDailyNote`` IMMEDIATELY before its
 * own PUT — not against a mount-time list snapshot — so backend content
 * written after the import started is never overwritten. A localStorage key
 * is removed ONLY after its own PUT succeeds; failures leave the key in place
 * so the import retries on the next mount. Returns true when anything was
 * imported (the caller invalidates the notes queries).
 */
async function importLegacyNotes(): Promise<boolean> {
  const keys = readLegacyNoteKeys();
  if (keys.length === 0) return false;

  const today = istDayKey();
  let imported = false;
  for (const key of keys) {
    const date = key.slice(LEGACY_NOTE_PREFIX.length);
    if (!DAY_RE.test(date)) continue;
    if (date === today) continue; // Editable in this tab right now — never race the editor.
    let content: string | null = null;
    try {
      content = localStorage.getItem(key);
    } catch {
      continue;
    }
    if (!content || !content.trim()) continue;
    try {
      // Re-check right before the PUT — never overwrite backend content.
      const existing = await getDailyNote(date);
      if (existing.content.trim()) continue;
    } catch {
      continue; // Backend unreachable — leave the key; retry on the next mount.
    }
    try {
      await putDailyNote(date, content);
      imported = true;
      try {
        localStorage.removeItem(key);
      } catch {
        // Removal failure is harmless — the upsert makes a re-import a no-op.
      }
    } catch {
      // Leave the key in place; the import retries on the next mount.
    }
  }
  return imported;
}

type SaveState = "idle" | "pending" | "saved" | "error";

export function NotesTab() {
  const isExploreMode = useModeStore((s) => s.mode === "explore");
  const queryClient = useQueryClient();

  // IST trading day, recomputed each minute so a panel left open across the
  // midnight-IST boundary rolls over to the new day.
  const [day, setDay] = useState(istDayKey);
  useEffect(() => {
    const id = setInterval(() => {
      setDay((prev) => {
        const next = istDayKey();
        return next === prev ? prev : next;
      });
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  const noteQuery = useQuery({
    queryKey: ["journalNotes", day],
    queryFn: () => getDailyNote(day),
    enabled: !isExploreMode,
  });

  // Draft typed since the last load; null = show the backend content.
  const [draft, setDraft] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<{ noteDay: string; content: string } | null>(null);

  const saveMutation = useMutation({
    mutationFn: ({ noteDay, content }: { noteDay: string; content: string }) =>
      putDailyNote(noteDay, content),
    onSuccess: (saved, variables) => {
      queryClient.setQueryData(["journalNotes", saved.date], saved);
      if (!variables.content.trim()) {
        // A deliberately cleared day must stay cleared: drop any retained
        // legacy localStorage copy so a later import cannot resurrect it.
        try {
          localStorage.removeItem(`${LEGACY_NOTE_PREFIX}${variables.noteDay}`);
        } catch {
          // Storage unavailable — nothing to remove.
        }
      }
      // A newer edit may already be waiting — stay "saving…" if so.
      if (!pendingRef.current) setSaveState("saved");
    },
    onError: () => {
      if (!pendingRef.current) setSaveState("error");
    },
  });
  const { mutate: mutateSave } = saveMutation;

  const flushPendingSave = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const pending = pendingRef.current;
    if (pending) {
      pendingRef.current = null;
      mutateSave(pending);
    }
  }, [mutateSave]);

  // Flush any pending debounce on unmount, and when the IST day rolls over
  // (the pending payload stays bound to the day it was typed on).
  useEffect(() => flushPendingSave, [day, flushPendingSave]);

  // A new day is a fresh note: drop the old draft and save-state claims.
  useEffect(() => {
    setDraft(null);
    setSaveState("idle");
  }, [day]);

  const scheduleSave = useCallback(
    (content: string) => {
      setDraft(content);
      if (isExploreMode) return; // Explore mode: ephemeral, no backend writes.
      setSaveState("pending");
      pendingRef.current = { noteDay: day, content };
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        const pending = pendingRef.current;
        pendingRef.current = null;
        if (pending) mutateSave(pending);
      }, SAVE_DEBOUNCE_MS);
    },
    [day, isExploreMode, mutateSave],
  );

  const clearNote = useCallback(() => {
    setDraft("");
    if (isExploreMode) return;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    pendingRef.current = null;
    setSaveState("pending");
    mutateSave({ noteDay: day, content: "" });
  }, [day, isExploreMode, mutateSave]);

  // One-time legacy import (skipped in Explore mode; runs once on the first
  // non-Explore render).
  const importAttemptedRef = useRef(false);
  useEffect(() => {
    if (isExploreMode || importAttemptedRef.current) return;
    importAttemptedRef.current = true;
    void importLegacyNotes().then((imported) => {
      if (imported) {
        void queryClient.invalidateQueries({ queryKey: ["journalNotes"] });
      }
    });
  }, [isExploreMode, queryClient]);

  const content = draft ?? noteQuery.data?.content ?? "";
  const wordCount = content.trim() ? content.trim().split(/\s+/).length : 0;

  // The day's note failed to load and has never loaded: editing must stay
  // locked, or fresh keystrokes would silently PUT over the unloaded backend
  // note once the backend recovers. A successful load (data present for this
  // day's query key) makes editing safe again.
  const noteLoadFailed =
    !isExploreMode && noteQuery.isError && noteQuery.data === undefined;

  let saveLabel = "";
  if (isExploreMode) {
    saveLabel = "Explore mode — notes are not saved";
  } else if (saveState === "pending" || saveMutation.isPending) {
    saveLabel = "saving…";
  } else if (saveState === "error" || (saveState === "idle" && noteQuery.isError)) {
    saveLabel = "not saved — backend unreachable";
  } else if (saveState === "saved") {
    saveLabel = "auto-saved";
  }

  return (
    <div className="flex flex-col gap-2 p-3 h-full">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-muted">Daily notes — {day}</span>
        <span className="text-xs text-text-muted">
          {wordCount} words
          {saveLabel ? ` · ${saveLabel}` : ""}
        </span>
      </div>
      {noteLoadFailed && (
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <span>
            Could not load the note for this day — editing is disabled so it
            cannot be overwritten.
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs"
            onClick={() => void noteQuery.refetch()}
          >
            Retry
          </Button>
        </div>
      )}
      <Textarea
        className="flex-1 text-sm leading-relaxed"
        placeholder={
          "Write your trading notes for today...\n\n- Market observations\n- Strategy notes\n- Lessons learned\n- Plan for tomorrow"
        }
        value={content}
        disabled={(!isExploreMode && noteQuery.isPending) || noteLoadFailed}
        onChange={(e) => scheduleSave(e.target.value)}
      />
      {content && (
        <Button
          variant="ghost"
          size="sm"
          className="self-end text-xs text-text-muted hover:text-loss h-6"
          onClick={clearNote}
        >
          Clear
        </Button>
      )}
    </div>
  );
}
