/**
 * Per-fill screenshot annotations — ported from the Trade Journal tool's
 * TradeLogTab (merge 2.11) with keys, query keys and behaviour unchanged so
 * the two surfaces share one cache and one backend store:
 *   - stable trade key ``timestamp|symbol|orderid-or-na``;
 *   - legacy ``timestamp-symbol-idx`` fallback lookup;
 *   - one-time legacy localStorage import (failure-retaining rewrite, 4xx
 *     rejection surfacing, silent transient retry);
 *   - metadata-only list + lazy per-id byte fetch per thumbnail.
 */

import { useCallback, useRef } from "react";
import { z } from "zod";
import { useQuery } from "@tanstack/react-query";
import { Camera, ImageOff } from "lucide-react";
import { safeParse } from "@/lib/safeParse";
import {
  addJournalScreenshot,
  getJournalScreenshot,
  type JournalScreenshot,
  type JournalScreenshotMeta,
} from "@/services/ftApi.journal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// ---------------------------------------------------------------------------
// Legacy localStorage import
// ---------------------------------------------------------------------------

/** Legacy localStorage map key from the pre-backend era (import source only). */
export const SCREENSHOTS_KEY = "flinttrade_journal_screenshots";

/** Max file size: 2 MiB (matches the backend's decoded-size cap). */
const MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024;

/** Outcome of one legacy-screenshot import pass. */
export interface LegacyScreenshotImportResult {
  /** True when at least one entry was uploaded (caller invalidates the query). */
  imported: boolean;
  /** Entries the backend permanently rejected (4xx) — surfaced to the user. */
  rejectedCount: number;
}

/**
 * True for errors carrying a 4xx HTTP status (the ``FtApiError`` shape) — a
 * permanent backend refusal (size cap, non-allowlisted image type) rather
 * than a transient failure worth retrying silently.
 */
function isPermanentRejection(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  const status = (err as { status?: unknown }).status;
  return typeof status === "number" && status >= 400 && status < 500;
}

/**
 * One-time import of the legacy localStorage screenshot map to the backend.
 *
 * Each entry is POSTed with its old key verbatim as ``trade_key``. After the
 * pass the map is rewritten to hold ONLY the entries that failed (and removed
 * outright when none did), so already-imported entries are never re-uploaded
 * on later mounts — the backend dedupes on ``(trade_key, content_sha256)``,
 * so a retried failure remains safe. Entries the backend permanently rejects
 * (4xx — e.g. an image type outside the allowlist or over the size cap) stay
 * in the map for recovery and are counted so the caller can surface them;
 * transient failures retry silently on the next mount.
 */
export async function importLegacyScreenshots(): Promise<LegacyScreenshotImportResult> {
  const nothing: LegacyScreenshotImportResult = { imported: false, rejectedCount: 0 };
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(SCREENSHOTS_KEY);
  } catch {
    return nothing;
  }
  if (!raw) return nothing;
  const map = safeParse(raw, z.record(z.string(), z.string()));
  if (!map) return nothing;

  const failed: Record<string, string> = {};
  let rejectedCount = 0;
  let anySucceeded = false;
  for (const [tradeKey, dataUrl] of Object.entries(map)) {
    try {
      await addJournalScreenshot(tradeKey, dataUrl);
      anySucceeded = true;
    } catch (err) {
      failed[tradeKey] = dataUrl;
      if (isPermanentRejection(err)) rejectedCount += 1;
    }
  }
  try {
    if (Object.keys(failed).length === 0) {
      localStorage.removeItem(SCREENSHOTS_KEY);
    } else {
      // Keep only the failures so retries never re-send succeeded entries.
      localStorage.setItem(SCREENSHOTS_KEY, JSON.stringify(failed));
    }
  } catch {
    // Storage write failure is harmless — dedupe makes a re-import a no-op.
  }
  return { imported: anySucceeded, rejectedCount };
}

// ---------------------------------------------------------------------------
// Screenshot cell components
// ---------------------------------------------------------------------------

/**
 * Thumbnail for one attached screenshot. The metadata list carries no image
 * bytes, so each rendered thumbnail lazily fetches its own row via
 * ``GET /screenshots/<id>``. Screenshot bytes are immutable (rows are only
 * ever created or deleted), so the query never goes stale.
 */
export function ScreenshotThumbnail({
  shot,
  onView,
}: {
  shot: JournalScreenshotMeta;
  onView: (shot: JournalScreenshot) => void;
}) {
  const dataQuery = useQuery({
    queryKey: ["journalScreenshot", shot.id],
    queryFn: () => getJournalScreenshot(shot.id),
    staleTime: Infinity,
  });

  if (dataQuery.isError) {
    return (
      <Button
        variant="ghost"
        size="icon"
        onClick={() => void dataQuery.refetch()}
        className="flex items-center justify-center w-10 h-7 p-0 rounded border border-border-default text-loss hover:border-border-hover transition-colors"
        aria-label="Screenshot failed to load"
        title="Screenshot failed to load — click to retry"
      >
        <ImageOff size={11} />
      </Button>
    );
  }

  const row = dataQuery.data;
  if (!row) {
    return (
      <div
        className="w-10 h-7 rounded border border-border-default bg-surface-elevated animate-pulse"
        role="status"
        aria-label="Loading screenshot"
      />
    );
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => onView(row)}
      className="flex items-center justify-center w-10 h-7 p-0 rounded overflow-hidden border border-border-default hover:border-accent transition-colors group"
      aria-label="View screenshot"
      title="Click to view screenshot"
    >
      <img
        src={row.data_url}
        alt="Trade screenshot thumbnail"
        className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity"
      />
    </Button>
  );
}

export interface ScreenshotCellProps {
  shot: JournalScreenshotMeta | undefined;
  /** True when attaching is blocked (Explore sample, or no journal record). */
  attachDisabled: boolean;
  /** Tooltip explaining why attaching is blocked. */
  disabledReason: string;
  onAttach: (dataUrl: string) => void;
  onView: (shot: JournalScreenshot) => void;
}

export function ScreenshotCell({
  shot,
  attachDisabled,
  disabledReason,
  onAttach,
  onView,
}: ScreenshotCellProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      if (file.size > MAX_FILE_SIZE_BYTES) {
        alert("Screenshot must be under 2 MB.");
        return;
      }
      if (!file.type.startsWith("image/")) {
        alert("Only image files are supported.");
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        if (typeof reader.result === "string") {
          onAttach(reader.result);
        }
      };
      reader.readAsDataURL(file);
      // Reset input so the same file can be re-attached
      e.target.value = "";
    },
    [onAttach],
  );

  if (shot) {
    return <ScreenshotThumbnail shot={shot} onView={onView} />;
  }

  return (
    <>
      <Input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFile}
        aria-label="Attach screenshot"
      />
      <Button
        variant="ghost"
        size="icon"
        disabled={attachDisabled}
        onClick={() => inputRef.current?.click()}
        className="flex items-center justify-center w-8 h-7 p-0 rounded border border-dashed border-border-default text-text-disabled hover:text-text-muted hover:border-border-hover transition-colors"
        aria-label="Attach screenshot"
        title={attachDisabled ? disabledReason : "Attach screenshot"}
      >
        <Camera size={11} />
      </Button>
    </>
  );
}
