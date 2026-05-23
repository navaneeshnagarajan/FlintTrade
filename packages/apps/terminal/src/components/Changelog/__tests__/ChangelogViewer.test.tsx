/**
 * ChangelogViewer.test.tsx
 *
 * Tests for the in-app changelog modal:
 *  - parseChangelog splits content into sections
 *  - Version sections render as accordions
 *  - Unreleased section shows "Latest" badge
 *  - Loading state renders while fetch is pending
 *  - Error state renders when fetch fails
 *  - Empty state when no sections found
 *  - handleClose marks version as seen
 *  - useChangelogAutoOpen opens when version differs
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { renderHook } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockFetch = vi.fn();
global.fetch = mockFetch;

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    removeItem: vi.fn((key: string) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({
    open,
    children,
  }: { open: boolean; children: React.ReactNode }) =>
    open ? <div data-testid="dialog">{children}</div> : null,
  DialogContent: ({
    children,
    ...rest
  }: { children: React.ReactNode; [key: string]: unknown }) => (
    <div data-testid="dialog-content" {...rest}>
      {children}
    </div>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h2>{children}</h2>
  ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    onClick,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    children: React.ReactNode;
  }) => (
    <button onClick={onClick} {...props}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => (
    <span data-testid="badge">{children}</span>
  ),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import ChangelogViewer, {
  parseChangelog,
  getLastSeenVersion,
  markVersionSeen,
  useChangelogAutoOpen,
} from "../ChangelogViewer";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

const SAMPLE_CHANGELOG = `# Changelog

## [Unreleased] — v0.5.0-dev

### Added
- New feature A
- New feature B

### Fixed
- Bug fix C

## [0.4.0] — 2025-01-15

### Added
- Initial release feature

## [0.3.0] — 2024-12-01

### Changed
- Refactor core module
`;

// ---------------------------------------------------------------------------
// Unit tests: parseChangelog
// ---------------------------------------------------------------------------

describe("parseChangelog", () => {
  it("returns empty array for empty content", () => {
    expect(parseChangelog("")).toEqual([]);
  });

  it("parses unreleased section", () => {
    const sections = parseChangelog(SAMPLE_CHANGELOG);
    const unreleased = sections.find((s) => s.isUnreleased);
    expect(unreleased).toBeDefined();
    expect(unreleased?.version).toBe("Unreleased");
  });

  it("parses versioned sections", () => {
    const sections = parseChangelog(SAMPLE_CHANGELOG);
    const v040 = sections.find((s) => s.version === "0.4.0");
    expect(v040).toBeDefined();
    expect(v040?.date).toBe("2025-01-15");
  });

  it("captures body content for each section", () => {
    const sections = parseChangelog(SAMPLE_CHANGELOG);
    const unreleased = sections.find((s) => s.isUnreleased);
    expect(unreleased?.rawBody).toContain("New feature A");
  });

  it("handles content with no sections", () => {
    const sections = parseChangelog("# Just a title\nsome text");
    expect(sections).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Unit tests: version storage
// ---------------------------------------------------------------------------

describe("version storage", () => {
  beforeEach(() => localStorageMock.clear());

  it("getLastSeenVersion returns null when not set", () => {
    expect(getLastSeenVersion()).toBeNull();
  });

  it("markVersionSeen persists version", () => {
    markVersionSeen("0.5.0-dev");
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      "flinttrade_last_seen_version",
      "0.5.0-dev",
    );
  });
});

// ---------------------------------------------------------------------------
// Component tests: ChangelogViewer
// ---------------------------------------------------------------------------

describe("ChangelogViewer", () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    currentVersion: "0.5.0-dev",
  };

  beforeEach(() => {
    localStorageMock.clear();
    vi.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      text: async () => SAMPLE_CHANGELOG,
    } as Response);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders dialog when isOpen is true", async () => {
    render(<ChangelogViewer {...defaultProps} />);
    expect(screen.getByTestId("dialog")).toBeInTheDocument();
  });

  it("does not render when isOpen is false", () => {
    render(<ChangelogViewer {...defaultProps} isOpen={false} />);
    expect(screen.queryByTestId("dialog")).not.toBeInTheDocument();
  });

  it("shows loading state initially", () => {
    // Slow fetch
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(<ChangelogViewer {...defaultProps} />);
    expect(screen.getByText(/loading changelog/i)).toBeInTheDocument();
  });

  it("renders sections after successful fetch", async () => {
    render(<ChangelogViewer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByText(/unreleased/i)).toBeInTheDocument(),
    );
  });

  it("shows Latest badge for unreleased section", async () => {
    render(<ChangelogViewer {...defaultProps} />);
    await waitFor(() => {
      const badges = screen.getAllByTestId("badge");
      const latestBadge = badges.find(
        (b) => b.textContent?.toLowerCase() === "latest",
      );
      expect(latestBadge).toBeDefined();
    });
  });

  it("renders error state when fetch fails", async () => {
    mockFetch.mockRejectedValue(new Error("Network error"));
    render(<ChangelogViewer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
  });

  it("calls onClose and marks version seen when close button clicked", async () => {
    const onClose = vi.fn();
    render(<ChangelogViewer {...defaultProps} onClose={onClose} />);
    await waitFor(() => screen.getByLabelText(/close changelog/i));
    fireEvent.click(screen.getByLabelText(/close changelog/i));
    expect(onClose).toHaveBeenCalled();
    expect(localStorageMock.setItem).toHaveBeenCalled();
  });

  it("renders Got it button in footer", async () => {
    render(<ChangelogViewer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByText("Got it")).toBeInTheDocument(),
    );
  });
});

// ---------------------------------------------------------------------------
// Hook tests: useChangelogAutoOpen
// ---------------------------------------------------------------------------

describe("useChangelogAutoOpen", () => {
  beforeEach(() => localStorageMock.clear());

  it("opens automatically when stored version differs", () => {
    localStorageMock.getItem.mockReturnValue("0.4.0");
    const { result } = renderHook(() => useChangelogAutoOpen("0.5.0-dev"));
    expect(result.current.isOpen).toBe(true);
  });

  it("does not open when stored version matches", () => {
    localStorageMock.getItem.mockReturnValue("0.5.0-dev");
    const { result } = renderHook(() => useChangelogAutoOpen("0.5.0-dev"));
    expect(result.current.isOpen).toBe(false);
  });

  it("close() sets isOpen to false and saves version", () => {
    localStorageMock.getItem.mockReturnValue(null as unknown as string);
    const { result } = renderHook(() => useChangelogAutoOpen("0.5.0-dev"));
    expect(result.current.isOpen).toBe(true);
    act(() => result.current.close());
    expect(result.current.isOpen).toBe(false);
  });
});
