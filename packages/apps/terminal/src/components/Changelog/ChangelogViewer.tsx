/**
 * ChangelogViewer — In-app modal that renders the project changelog.md.
 *
 * Parses the markdown into navigable sections keyed by version heading.
 * Highlights the latest version with a "New in v0.x" banner.
 * Auto-opens on the first load of a new version (compares stored vs current).
 *
 * Data source:
 *  - Dev/prod: GET /ft-api/v1/changelog from the backend.
 *
 * Since Vite externalises "marked" for the Glide Data Grid peer dep, we use
 * a minimal inline renderer instead of the marked package.
 */

import {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
} from "react";
import {
  ChevronDown,
  ChevronRight,
  GitCommit,
  Sparkles,
  X,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { APP_VERSION } from "@/lib/appVersion";

// ---------------------------------------------------------------------------
// Version storage
// ---------------------------------------------------------------------------

const VERSION_KEY = "flinttrade_last_seen_version";

export function getLastSeenVersion(): string | null {
  try {
    return localStorage.getItem(VERSION_KEY);
  } catch {
    return null;
  }
}

export function markVersionSeen(version: string): void {
  try {
    localStorage.setItem(VERSION_KEY, version);
  } catch {
    // noop
  }
}

// ---------------------------------------------------------------------------
// Markdown parser — section-level only (no need for full render)
// ---------------------------------------------------------------------------

export interface ChangelogSection {
  version: string;
  date: string | null;
  isUnreleased: boolean;
  /** Raw markdown body for this version section */
  rawBody: string;
}

/**
 * Splits changelog.md content into per-version sections.
 * Recognises "## [Version]" and "## [Unreleased]" headings.
 */
export function parseChangelog(content: string): ChangelogSection[] {
  const lines = content.split("\n");
  const sections: ChangelogSection[] = [];
  let current: ChangelogSection | null = null;
  const bodyLines: string[] = [];

  function flush() {
    if (current) {
      sections.push({ ...current, rawBody: bodyLines.join("\n").trim() });
      bodyLines.length = 0;
    }
  }

  for (const line of lines) {
    // Match "## [Unreleased] — label" or "## [0.5.0] — 2025-01-01"
    const sectionMatch = /^##\s+\[([^\]]+)\](?:\s+[-—–]\s+(.+))?/.exec(line);
    if (sectionMatch) {
      flush();
      const versionTag = sectionMatch[1].trim();
      const rest = sectionMatch[2]?.trim() ?? null;
      const isUnreleased = versionTag.toLowerCase() === "unreleased";

      // Extract date from rest (YYYY-MM-DD pattern)
      const dateMatch = rest ? /\d{4}-\d{2}-\d{2}/.exec(rest) : null;
      const date = dateMatch ? dateMatch[0] : rest;

      current = {
        version: isUnreleased ? "Unreleased" : versionTag,
        date,
        isUnreleased,
        rawBody: "",
      };
    } else if (current) {
      bodyLines.push(line);
    }
  }
  flush();

  return sections;
}

// ---------------------------------------------------------------------------
// Minimal markdown-to-JSX renderer (headings + lists + code + bold)
// ---------------------------------------------------------------------------

function renderMarkdownLine(line: string, key: number) {
  // ### heading
  if (/^###\s/.test(line)) {
    return (
      <h4
        key={key}
        className="text-xs font-semibold text-text-secondary uppercase tracking-wider mt-3 mb-1"
      >
        {line.replace(/^###\s+/, "")}
      </h4>
    );
  }
  // ## heading
  if (/^##\s/.test(line)) {
    return (
      <h3 key={key} className="text-sm font-semibold text-text-primary mt-4 mb-1">
        {line.replace(/^##\s+/, "")}
      </h3>
    );
  }
  // List item — "- text" or "* text"
  if (/^[-*]\s/.test(line)) {
    const text = line.replace(/^[-*]\s+/, "");
    return (
      <li
        key={key}
        className="text-xs text-text-secondary leading-relaxed ml-2 list-disc list-inside"
      >
        <InlineMarkdown text={text} />
      </li>
    );
  }
  // Empty line
  if (line.trim() === "") {
    return <div key={key} className="h-1" />;
  }
  // Paragraph
  return (
    <p key={key} className="text-xs text-text-secondary leading-relaxed">
      <InlineMarkdown text={line} />
    </p>
  );
}

/** Renders inline bold (`**text**`) and inline code (`` `code` ``). */
function InlineMarkdown({ text }: { text: string }) {
  // Split on **bold** and `code` patterns
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let i = 0;

  while (remaining.length > 0) {
    const boldIdx = remaining.indexOf("**");
    const codeIdx = remaining.indexOf("`");

    if (boldIdx === -1 && codeIdx === -1) {
      parts.push(<span key={i++}>{remaining}</span>);
      break;
    }

    const nextIdx =
      boldIdx === -1
        ? codeIdx
        : codeIdx === -1
          ? boldIdx
          : Math.min(boldIdx, codeIdx);

    // Push text before
    if (nextIdx > 0) {
      parts.push(<span key={i++}>{remaining.slice(0, nextIdx)}</span>);
    }

    if (nextIdx === boldIdx) {
      const endIdx = remaining.indexOf("**", boldIdx + 2);
      if (endIdx === -1) {
        parts.push(<span key={i++}>{remaining.slice(boldIdx)}</span>);
        break;
      }
      parts.push(
        <strong key={i++} className="font-semibold text-text-primary">
          {remaining.slice(boldIdx + 2, endIdx)}
        </strong>,
      );
      remaining = remaining.slice(endIdx + 2);
    } else {
      const endIdx = remaining.indexOf("`", codeIdx + 1);
      if (endIdx === -1) {
        parts.push(<span key={i++}>{remaining.slice(codeIdx)}</span>);
        break;
      }
      parts.push(
        <code
          key={i++}
          className="font-mono text-[10px] bg-glass-l2 px-1 py-0.5 rounded text-text-primary"
        >
          {remaining.slice(codeIdx + 1, endIdx)}
        </code>,
      );
      remaining = remaining.slice(endIdx + 1);
    }
  }

  return <>{parts}</>;
}

// ---------------------------------------------------------------------------
// Section accordion
// ---------------------------------------------------------------------------

interface SectionAccordionProps {
  section: ChangelogSection;
  defaultOpen: boolean;
}

function SectionAccordion({ section, defaultOpen }: SectionAccordionProps) {
  const [open, setOpen] = useState(defaultOpen);

  const lines = section.rawBody.split("\n");

  return (
    <div className="border border-border-default rounded-glass-inner overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className={cn(
          "w-full flex items-center justify-between gap-3 px-4 py-3",
          "text-left transition-colors hover:bg-glass-l1",
          open && "bg-glass-l1",
        )}
        aria-expanded={open}
        aria-controls={`changelog-section-${section.version}`}
      >
        <div className="flex items-center gap-2 min-w-0">
          {section.isUnreleased ? (
            <Sparkles size={14} className="text-accent shrink-0" aria-hidden="true" />
          ) : (
            <GitCommit size={14} className="text-text-muted shrink-0" aria-hidden="true" />
          )}
          <span className="text-sm font-semibold text-text-primary font-mono">
            v{section.version}
          </span>
          {section.isUnreleased && (
            <Badge
              variant="outline"
              className="text-[10px] h-4 px-1.5 border-accent/40 text-accent"
            >
              Latest
            </Badge>
          )}
          {section.date && (
            <span className="text-xs text-text-muted ml-1">{section.date}</span>
          )}
        </div>
        {open ? (
          <ChevronDown size={14} className="text-text-muted shrink-0" aria-hidden="true" />
        ) : (
          <ChevronRight size={14} className="text-text-muted shrink-0" aria-hidden="true" />
        )}
      </button>

      {open && (
        <div
          id={`changelog-section-${section.version}`}
          className="px-4 pb-4 pt-1 border-t border-border-default/50"
        >
          <div className="space-y-0.5">
            {lines.map((line, i) => renderMarkdownLine(line, i))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function fetchChangelog(): Promise<string> {
  // In development, Vite serves files from publicDir or via the dev server.
  // changelog.md is at the repo root — we expose it via a custom endpoint.
  const res = await fetch("/ft-api/v1/changelog");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.text();
}

// ---------------------------------------------------------------------------
// Hook — auto-show on version bump
// ---------------------------------------------------------------------------

export function useChangelogAutoOpen(currentVersion: string): {
  isOpen: boolean;
  open: () => void;
  close: () => void;
} {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const last = getLastSeenVersion();
    if (last !== currentVersion) {
      setIsOpen(true);
    }
  }, [currentVersion]);

  const close = useCallback(() => {
    setIsOpen(false);
    markVersionSeen(currentVersion);
  }, [currentVersion]);

  const open = useCallback(() => setIsOpen(true), []);

  return { isOpen, open, close };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export interface ChangelogViewerProps {
  isOpen: boolean;
  onClose: () => void;
  /** Current app version string without the leading v, e.g. "0.6.0-alpha" */
  currentVersion?: string;
}

export default function ChangelogViewer({
  isOpen,
  onClose,
  currentVersion = APP_VERSION,
}: ChangelogViewerProps) {
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchedRef = useRef(false);

  // Fetch once when opened
  useEffect(() => {
    if (!isOpen || fetchedRef.current) return;
    fetchedRef.current = true;
    setLoading(true);
    setError(null);
    fetchChangelog()
      .then((text) => {
        setContent(text);
        setLoading(false);
      })
      .catch(() => {
        setError("Could not load changelog.");
        setLoading(false);
      });
  }, [isOpen]);

  const sections = useMemo(() => parseChangelog(content), [content]);

  const handleClose = useCallback(() => {
    markVersionSeen(currentVersion);
    onClose();
  }, [currentVersion, onClose]);

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) handleClose(); }}>
      <DialogContent
        className="sm:max-w-2xl max-h-[85vh] flex flex-col bg-surface-card border-border-default p-0 animate-fade-in-scale"
        aria-describedby="changelog-desc"
      >
        <DialogHeader className="px-6 pt-5 pb-3 border-b border-border-default">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <GitCommit
                className="w-4 h-4 text-text-muted shrink-0"
                aria-hidden="true"
              />
              <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
                What&rsquo;s New in FlintTrade
              </DialogTitle>
            </div>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleClose}
              className="h-7 w-7 p-0 text-text-muted hover:text-text-primary"
              aria-label="Close changelog"
            >
              <X size={14} />
            </Button>
          </div>
          <p id="changelog-desc" className="text-xs text-text-muted mt-0.5">
            Version history for FlintTrade v{currentVersion}
          </p>
        </DialogHeader>

        <div className="overflow-y-auto flex-1 min-h-0 px-6 py-4">
          {loading && (
            <div className="flex items-center justify-center py-16" aria-live="polite">
              <span className="text-sm text-text-muted animate-pulse">
                Loading changelog…
              </span>
            </div>
          )}

          {error && !loading && (
            <div
              className="flex items-center justify-center py-16 text-text-muted"
              role="alert"
            >
              <p className="text-sm">{error}</p>
            </div>
          )}

          {!loading && !error && sections.length === 0 && (
            <div className="flex items-center justify-center py-16 text-text-muted">
              <p className="text-sm">No changelog entries found.</p>
            </div>
          )}

          {!loading && !error && sections.length > 0 && (
            <div className="space-y-2">
              {sections.map((section, i) => (
                <SectionAccordion
                  key={section.version}
                  section={section}
                  defaultOpen={i === 0}
                />
              ))}
            </div>
          )}
        </div>

        <div className="px-6 py-3 border-t border-border-default flex items-center justify-between">
          <p className="text-xs text-text-muted">
            Full history at{" "}
            <a
              href="https://github.com/navaneeshnagarajan/FlintTrade/blob/main/changelog.md"
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:underline"
            >
              changelog.md
            </a>
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={handleClose}
            className="h-7 px-3 text-xs border-border-default"
          >
            Got it
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
