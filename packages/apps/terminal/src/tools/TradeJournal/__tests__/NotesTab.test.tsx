/**
 * NotesTab.test.tsx
 *
 * Tests for the backend-persisted daily notes tab: IST day keying, load via
 * TanStack Query, debounced auto-save with an honest save-state label, and
 * the one-time legacy localStorage import.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const runtime = { mode: "live" };
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: runtime.mode }),
}));

const mockGetDailyNote = vi.fn();
const mockPutDailyNote = vi.fn();
const mockListDailyNotes = vi.fn();
vi.mock("@/services/ftApi.journal", () => ({
  getDailyNote: (date: string) => mockGetDailyNote(date) as Promise<unknown>,
  putDailyNote: (date: string, content: string) =>
    mockPutDailyNote(date, content) as Promise<unknown>,
  listDailyNotes: () => mockListDailyNotes() as Promise<unknown>,
}));

vi.mock("@/components/ui/textarea", () => ({
  Textarea: ({ ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea {...props} />
  ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, onClick, disabled }: {
    children: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
  }) => (
    <button onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
}));

// ---------------------------------------------------------------------------
// localStorage mock (needs key()/length for the legacy-note scan)
// ---------------------------------------------------------------------------

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
    key: (i: number) => Object.keys(store)[i] ?? null,
    get length() { return Object.keys(store).length; },
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import { NotesTab } from "../NotesTab";
import { istDayKey } from "../utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const NOTE_PLACEHOLDER = /write your trading notes/i;

function renderNotes() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <NotesTab />
    </QueryClientProvider>,
  );
}

async function getEnabledTextarea(): Promise<HTMLTextAreaElement> {
  const textarea = screen.getByPlaceholderText(NOTE_PLACEHOLDER) as HTMLTextAreaElement;
  await waitFor(() => expect(textarea).not.toBeDisabled());
  return textarea;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("istDayKey", () => {
  it("keys by the IST (Asia/Kolkata) calendar day, not the UTC date", () => {
    // 20:00 UTC is 01:30 IST the NEXT day — toISOString() would say 07-19.
    expect(istDayKey(new Date("2026-07-19T20:00:00Z"))).toBe("2026-07-20");
    // 05:00 UTC is 10:30 IST the same day.
    expect(istDayKey(new Date("2026-07-19T05:00:00Z"))).toBe("2026-07-19");
  });
});

describe("NotesTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    runtime.mode = "live";
    // Per-date default: no backend content for any day (the import's pre-PUT
    // re-check and the day query both go through this).
    mockGetDailyNote.mockImplementation((date: string) =>
      Promise.resolve({ date, content: "", updated_at: null }),
    );
    mockListDailyNotes.mockResolvedValue([]);
    mockPutDailyNote.mockImplementation((date: string, content: string) =>
      Promise.resolve({ date, content, updated_at: "2026-07-20T10:00:00" }),
    );
  });

  it("loads today's IST note from the backend", async () => {
    const day = istDayKey();
    mockGetDailyNote.mockResolvedValue({
      date: day,
      content: "hello world",
      updated_at: "2026-07-20T09:00:00",
    });

    renderNotes();

    await waitFor(() =>
      expect(screen.getByPlaceholderText(NOTE_PLACEHOLDER)).toHaveValue("hello world"),
    );
    expect(mockGetDailyNote).toHaveBeenCalledWith(day);
    expect(screen.getByText(`Daily notes — ${day}`)).toBeInTheDocument();
    expect(screen.getByText(/2 words/)).toBeInTheDocument();
    // No save has happened yet — the label must not claim one.
    expect(screen.queryByText(/auto-saved/)).not.toBeInTheDocument();
  });

  it("debounces the save and only claims auto-saved after the PUT succeeds", async () => {
    const day = istDayKey();
    renderNotes();
    const textarea = await getEnabledTextarea();

    fireEvent.change(textarea, { target: { value: "note one" } });

    // Debounced: shows "saving…" immediately, but no PUT yet.
    expect(screen.getByText(/saving…/)).toBeInTheDocument();
    expect(mockPutDailyNote).not.toHaveBeenCalled();

    await waitFor(
      () => expect(mockPutDailyNote).toHaveBeenCalledWith(day, "note one"),
      { timeout: 3000 },
    );
    await waitFor(() =>
      expect(screen.getByText(/auto-saved/)).toBeInTheDocument(),
    );
  });

  it("reports an unreachable backend honestly instead of claiming auto-saved", async () => {
    mockPutDailyNote.mockRejectedValue(new Error("backend down"));
    renderNotes();
    const textarea = await getEnabledTextarea();

    fireEvent.change(textarea, { target: { value: "doomed note" } });

    await waitFor(
      () =>
        expect(
          screen.getByText(/not saved — backend unreachable/),
        ).toBeInTheDocument(),
      { timeout: 3000 },
    );
    expect(screen.queryByText(/auto-saved/)).not.toBeInTheDocument();
  });

  it("imports legacy localStorage notes and removes each key only after its PUT succeeds", async () => {
    localStorageMock.setItem("flinttrade_journal_notes_2026-07-01", "legacy note");
    // The backend already holds content for 07-02 — must not be overwritten.
    // Only the per-date getDailyNote re-check reports it (the list mock stays
    // empty), pinning that the guard runs immediately before each PUT rather
    // than against a stale mount-time list snapshot.
    localStorageMock.setItem("flinttrade_journal_notes_2026-07-02", "shadowed local note");
    mockGetDailyNote.mockImplementation((date: string) =>
      Promise.resolve({
        date,
        content: date === "2026-07-02" ? "server copy" : "",
        updated_at: date === "2026-07-02" ? "2026-07-02T16:00:00" : null,
      }),
    );

    renderNotes();

    await waitFor(() =>
      expect(mockPutDailyNote).toHaveBeenCalledWith("2026-07-01", "legacy note"),
    );
    await waitFor(() =>
      expect(localStorageMock.getItem("flinttrade_journal_notes_2026-07-01")).toBeNull(),
    );
    // Each import PUT is preceded by its own getDailyNote re-check.
    expect(mockGetDailyNote).toHaveBeenCalledWith("2026-07-01");
    expect(mockGetDailyNote).toHaveBeenCalledWith("2026-07-02");
    // Backend content wins: no PUT for 07-02, and the local copy is preserved.
    expect(mockPutDailyNote).not.toHaveBeenCalledWith("2026-07-02", expect.anything());
    expect(localStorageMock.getItem("flinttrade_journal_notes_2026-07-02")).toBe(
      "shadowed local note",
    );
  });

  it("never imports the current IST day's key while the tab is mounted", async () => {
    const day = istDayKey();
    localStorageMock.setItem(`flinttrade_journal_notes_${day}`, "todays legacy note");
    localStorageMock.setItem("flinttrade_journal_notes_2026-01-05", "older legacy note");

    renderNotes();

    // The older key imports…
    await waitFor(() =>
      expect(mockPutDailyNote).toHaveBeenCalledWith("2026-01-05", "older legacy note"),
    );
    // …but the editable current day never does — importing it would race the
    // debounced editor save in both directions. The key survives untouched
    // for a later mount, once the day has passed.
    expect(mockPutDailyNote).not.toHaveBeenCalledWith(day, "todays legacy note");
    expect(localStorageMock.getItem(`flinttrade_journal_notes_${day}`)).toBe(
      "todays legacy note",
    );
  });

  it("removes the day's legacy key on a successful clear so it cannot be resurrected", async () => {
    const day = istDayKey();
    // A retained legacy copy for today (the import deliberately skips it).
    localStorageMock.setItem(`flinttrade_journal_notes_${day}`, "stale legacy copy");
    mockGetDailyNote.mockImplementation((date: string) =>
      Promise.resolve({
        date,
        content: date === day ? "fresh note" : "",
        updated_at: date === day ? "2026-07-20T09:00:00" : null,
      }),
    );

    renderNotes();
    await waitFor(() =>
      expect(screen.getByPlaceholderText(NOTE_PLACEHOLDER)).toHaveValue("fresh note"),
    );

    fireEvent.click(screen.getByText("Clear"));

    await waitFor(() => expect(mockPutDailyNote).toHaveBeenCalledWith(day, ""));
    // The deliberate clear also drops the legacy key — a later import must
    // never resurrect content the user explicitly deleted.
    await waitFor(() =>
      expect(localStorageMock.getItem(`flinttrade_journal_notes_${day}`)).toBeNull(),
    );
  });

  it("disables editing behind a Retry affordance while the note load is in error", async () => {
    mockGetDailyNote.mockImplementation((date: string) =>
      Promise.resolve({ date, content: "recovered note", updated_at: "2026-07-20T09:00:00" }),
    );
    mockGetDailyNote.mockRejectedValueOnce(new Error("backend down"));

    renderNotes();

    // Load failed: editing stays locked (typing would PUT over the unloaded
    // backend note once it recovers) and a Retry affordance is offered.
    const retryBtn = await screen.findByText("Retry");
    const textarea = screen.getByPlaceholderText(NOTE_PLACEHOLDER);
    expect(textarea).toBeDisabled();

    fireEvent.click(retryBtn);

    await waitFor(() => expect(textarea).toHaveValue("recovered note"));
    expect(textarea).not.toBeDisabled();
  });

  it("keeps the legacy key when its import PUT fails", async () => {
    localStorageMock.setItem("flinttrade_journal_notes_2026-07-01", "legacy note");
    mockPutDailyNote.mockRejectedValue(new Error("backend down"));

    renderNotes();

    await waitFor(() =>
      expect(mockPutDailyNote).toHaveBeenCalledWith("2026-07-01", "legacy note"),
    );
    await waitFor(() =>
      expect(localStorageMock.getItem("flinttrade_journal_notes_2026-07-01")).toBe(
        "legacy note",
      ),
    );
  });

  it("skips backend traffic and the import in Explore mode with an honest label", async () => {
    runtime.mode = "explore";
    localStorageMock.setItem("flinttrade_journal_notes_2026-07-01", "legacy note");

    renderNotes();

    const textarea = screen.getByPlaceholderText(NOTE_PLACEHOLDER);
    fireEvent.change(textarea, { target: { value: "explore scribbles" } });
    expect(textarea).toHaveValue("explore scribbles");

    expect(
      screen.getByText(/Explore mode — notes are not saved/),
    ).toBeInTheDocument();

    // Allow any (incorrect) query or import kick-off to surface.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mockGetDailyNote).not.toHaveBeenCalled();
    expect(mockListDailyNotes).not.toHaveBeenCalled();
    expect(mockPutDailyNote).not.toHaveBeenCalled();
    expect(localStorageMock.getItem("flinttrade_journal_notes_2026-07-01")).toBe(
      "legacy note",
    );
  });
});
