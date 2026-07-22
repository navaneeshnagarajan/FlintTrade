import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

vi.mock("@/lib/desktopShell", () => ({
  applyShellUpdate: vi.fn(),
  applySourceUpdate: vi.fn(),
  checkShellUpdate: vi.fn(),
  checkSourceUpdate: vi.fn(),
  getUpdateState: vi.fn(),
  isDesktopShell: vi.fn(() => false),
  onUpdateProgress: vi.fn(),
  openExternalUrl: vi.fn(),
}));

import {
  applyShellUpdate,
  applySourceUpdate,
  checkShellUpdate,
  checkSourceUpdate,
  getUpdateState,
  isDesktopShell,
  onUpdateProgress,
  type UpdateKind,
  type UpdateSnapshot,
  type UpdateStatus,
} from "@/lib/desktopShell";
import { UpdatesSection } from "../UpdatesSection";
import { buildSections } from "../settingsConfig";

const SOURCE_CURRENT = "a".repeat(40);
const SOURCE_TARGET = "b".repeat(40);

function snapshot(
  kind: UpdateKind,
  status: UpdateStatus = "idle",
  overrides: Partial<UpdateSnapshot> = {},
): UpdateSnapshot {
  return {
    attempt: 0,
    currentVersion: kind === "source" ? SOURCE_CURRENT : "0.6.0-beta.13",
    failure: null,
    heartbeatAt: 1,
    kind,
    message: "No update check has run",
    progress: null,
    status,
    version: null,
    ...overrides,
  };
}

function deferred<T>() {
  let reject!: (error: unknown) => void;
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    reject = rejectPromise;
    resolve = resolvePromise;
  });
  return { promise, reject, resolve };
}

const mockIsDesktopShell = vi.mocked(isDesktopShell);
const mockGetUpdateState = vi.mocked(getUpdateState);
const mockOnUpdateProgress = vi.mocked(onUpdateProgress);
const mockCheckSource = vi.mocked(checkSourceUpdate);
const mockApplySource = vi.mocked(applySourceUpdate);
const mockCheckShell = vi.mocked(checkShellUpdate);
const mockApplyShell = vi.mocked(applyShellUpdate);

let progressListener: ((update: Readonly<UpdateSnapshot>) => void) | null;
let unsubscribe: Mock<() => void>;

beforeEach(() => {
  mockIsDesktopShell.mockReturnValue(true);
  mockGetUpdateState.mockImplementation((kind) => Promise.resolve(snapshot(kind)));
  unsubscribe = vi.fn<() => void>();
  progressListener = null;
  mockOnUpdateProgress.mockImplementation((listener) => {
    progressListener = listener;
    return unsubscribe;
  });
  mockCheckSource.mockResolvedValue(
    snapshot("source", "unavailable", {
      attempt: 1,
      message: `Source ${SOURCE_CURRENT.slice(0, 12)} is current`,
    }),
  );
  mockCheckShell.mockResolvedValue(
    snapshot("shell", "unavailable", {
      attempt: 1,
      message: "The Electron shell is current",
    }),
  );
  mockApplySource.mockResolvedValue(
    snapshot("source", "complete", {
      attempt: 2,
      currentVersion: SOURCE_TARGET,
      message: `Source ${SOURCE_TARGET.slice(0, 12)} is active`,
      progress: 100,
      version: SOURCE_TARGET,
    }),
  );
  mockApplyShell.mockResolvedValue(
    snapshot("shell", "complete", {
      attempt: 2,
      currentVersion: "0.6.0-beta.14",
      message: "Shell update installed",
      progress: 100,
      version: "0.6.0-beta.14",
    }),
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("UpdatesSection visibility", () => {
  it("renders nothing in a normal browser", () => {
    mockIsDesktopShell.mockReturnValue(false);
    const { container } = render(<UpdatesSection />);
    expect(container.firstChild).toBeNull();
    expect(mockGetUpdateState).not.toHaveBeenCalled();
  });

  it("is registered only for the desktop shell", () => {
    const desktopIds = buildSections(true).map((section) => section.id);
    const webIds = buildSections(false).map((section) => section.id);
    expect(desktopIds).toContain("updates");
    expect(webIds).toEqual(desktopIds.filter((id) => id !== "updates"));
  });
});

describe("UpdatesSection state", () => {
  it("shows distinct source/runtime and Electron-shell flows with current identifiers", async () => {
    render(<UpdatesSection />);

    expect(await screen.findByRole("heading", { name: "Source and runtime" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Electron shell" })).toBeInTheDocument();
    expect(await screen.findByText(SOURCE_CURRENT.slice(0, 12))).toHaveAttribute("title", SOURCE_CURRENT);
    expect(screen.getByText("v0.6.0-beta.13")).toBeInTheDocument();
    expect(screen.getByText(/stages a sibling checkout, builds the terminal, and verifies isolated health/i)).toBeInTheDocument();
    expect(screen.getByText(/packaged installer handoff/i)).toBeInTheDocument();
    expect(mockGetUpdateState).toHaveBeenCalledWith("source");
    expect(mockGetUpdateState).toHaveBeenCalledWith("shell");
  });

  it("subscribes to progress and unsubscribes on unmount", async () => {
    const { unmount } = render(<UpdatesSection />);
    await screen.findByText(SOURCE_CURRENT.slice(0, 12));
    expect(mockOnUpdateProgress).toHaveBeenCalledOnce();
    unmount();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("ignores a stale progress event from an older attempt", async () => {
    mockGetUpdateState.mockImplementation((kind) =>
      Promise.resolve(snapshot(kind, "unavailable", { attempt: 4, message: `${kind} current` })),
    );
    render(<UpdatesSection />);
    expect(await screen.findByText("source current")).toBeInTheDocument();

    act(() => {
      progressListener?.(snapshot("source", "failed", { attempt: 3, failure: "stale failure", message: "stale failure" }));
    });

    expect(screen.queryByText("stale failure")).not.toBeInTheDocument();
    expect(screen.getByText("source current")).toBeInTheDocument();
  });

  it("surfaces an unavailable initial state instead of inventing a version", async () => {
    mockGetUpdateState.mockImplementation((kind) =>
      Promise.resolve(snapshot(kind, "unavailable", {
        currentVersion: kind === "source" ? null : "0.6.0-beta.13",
        message: kind === "source" ? "Source revision is unavailable" : "Shell updater is unavailable",
      })),
    );
    render(<UpdatesSection />);

    expect(await screen.findByText("Source revision is unavailable")).toBeInTheDocument();
    expect(screen.getAllByText("Not reported")).toHaveLength(1);
    expect(screen.getByText("Shell updater is unavailable")).toBeInTheDocument();
  });

  it("never substitutes the terminal build version for an unreported shell version", async () => {
    mockGetUpdateState.mockImplementation((kind) => Promise.resolve(snapshot(kind, "idle", {
      currentVersion: kind === "shell" ? null : SOURCE_CURRENT,
    })));
    render(<UpdatesSection />);

    expect(await screen.findByText("Not reported")).toBeInTheDocument();
    expect(screen.queryByText("v0.6.0-beta.13")).not.toBeInTheDocument();
  });

  it("does not let a late initial-state rejection replace a newer pushed snapshot", async () => {
    const initialSource = deferred<UpdateSnapshot>();
    mockGetUpdateState.mockImplementation((kind) => (
      kind === "source" ? initialSource.promise : Promise.resolve(snapshot(kind))
    ));
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.13");

    act(() => {
      progressListener?.(snapshot("source", "available", {
        attempt: 2,
        heartbeatAt: 20,
        message: "Authoritative source update",
        version: SOURCE_TARGET,
      }));
    });
    await act(async () => {
      initialSource.reject(new Error("late initial failure"));
      await Promise.resolve();
    });

    expect(screen.getByText("Authoritative source update")).toBeInTheDocument();
    expect(screen.queryByText("late initial failure")).not.toBeInTheDocument();
  });
});

describe("UpdatesSection source/runtime flow", () => {
  it("checks trusted main, then stages, builds, health-checks and restarts", async () => {
    mockCheckSource.mockResolvedValue(
      snapshot("source", "available", {
        attempt: 1,
        message: `Source ${SOURCE_TARGET.slice(0, 12)} is available`,
        version: SOURCE_TARGET,
      }),
    );
    const user = userEvent.setup();
    render(<UpdatesSection />);
    await screen.findByText(SOURCE_CURRENT.slice(0, 12));

    await user.click(screen.getByRole("button", { name: "Check source update" }));

    expect(mockCheckSource).toHaveBeenCalledOnce();
    expect(await screen.findByText(SOURCE_TARGET.slice(0, 12))).toHaveAttribute("title", SOURCE_TARGET);
    const apply = screen.getByRole("button", { name: /stage, verify and restart/i });
    await user.click(apply);

    expect(mockApplySource).toHaveBeenCalledOnce();
    expect(await screen.findByText(`Source ${SOURCE_TARGET.slice(0, 12)} is active`)).toBeInTheDocument();
    expect(screen.getAllByText(SOURCE_TARGET.slice(0, 12))[0]).toHaveAttribute("title", SOURCE_TARGET);
  });

  it("renders build and health progress pushed by Electron", async () => {
    render(<UpdatesSection />);
    await screen.findByText(SOURCE_CURRENT.slice(0, 12));

    act(() => {
      progressListener?.(
        snapshot("source", "applying", {
          attempt: 2,
          message: "Building the candidate terminal",
          progress: 58,
          version: SOURCE_TARGET,
        }),
      );
    });

    expect(screen.getByRole("status")).toHaveTextContent("Building the candidate terminal");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "58");
  });

  it("reports a current source honestly without offering apply", async () => {
    const user = userEvent.setup();
    render(<UpdatesSection />);
    await screen.findByText(SOURCE_CURRENT.slice(0, 12));

    await user.click(screen.getByRole("button", { name: "Check source update" }));

    expect(await screen.findByText(`Source ${SOURCE_CURRENT.slice(0, 12)} is current`)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /stage, verify and restart/i })).not.toBeInTheDocument();
  });

  it("surfaces a redacted check failure and allows retry", async () => {
    mockCheckSource.mockRejectedValueOnce(new Error("Could not resolve trusted main."));
    const user = userEvent.setup();
    render(<UpdatesSection />);
    await screen.findByText(SOURCE_CURRENT.slice(0, 12));

    await user.click(screen.getByRole("button", { name: "Check source update" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not resolve trusted main.");
    expect(screen.getByRole("button", { name: "Check source update" })).toBeEnabled();
  });

  it("does not let a late action rejection replace authoritative pushed progress", async () => {
    const check = deferred<UpdateSnapshot>();
    mockCheckSource.mockReturnValueOnce(check.promise);
    const user = userEvent.setup();
    render(<UpdatesSection />);
    await screen.findByText(SOURCE_CURRENT.slice(0, 12));

    await user.click(screen.getByRole("button", { name: "Check source update" }));
    act(() => {
      progressListener?.(snapshot("source", "available", {
        attempt: 2,
        heartbeatAt: 20,
        message: "Authoritative checked source",
        version: SOURCE_TARGET,
      }));
    });
    await act(async () => {
      check.reject(new Error("late transport failure"));
      await Promise.resolve();
    });

    expect(screen.getByText("Authoritative checked source")).toBeInTheDocument();
    expect(screen.queryByText("late transport failure")).not.toBeInTheDocument();
  });
});

describe("UpdatesSection Electron-shell flow", () => {
  it("checks releases and hands an available shell update back for install and relaunch", async () => {
    mockCheckShell.mockResolvedValue(
      snapshot("shell", "available", {
        attempt: 1,
        message: "Electron shell v0.6.0-beta.14 is available",
        version: "0.6.0-beta.14",
      }),
    );
    const user = userEvent.setup();
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.13");

    await user.click(screen.getByRole("button", { name: "Check shell update" }));
    expect(await screen.findByText("v0.6.0-beta.14")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Install and relaunch" }));
    expect(mockApplyShell).toHaveBeenCalledOnce();
    expect(await screen.findByText("Shell update installed")).toBeInTheDocument();
  });

  it("shows the shell-owned unavailable result without fetching renderer manifests", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.13");

    await user.click(screen.getByRole("button", { name: "Check shell update" }));

    expect(await screen.findByText("The Electron shell is current")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Install and relaunch" })).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("keeps source and shell availability independent", async () => {
    mockGetUpdateState.mockImplementation((kind) =>
      Promise.resolve(
        snapshot(kind, "available", {
          attempt: 1,
          version: kind === "source" ? SOURCE_TARGET : "0.6.0-beta.14",
        }),
      ),
    );
    render(<UpdatesSection />);

    expect(await screen.findByRole("button", { name: /stage, verify and restart/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install and relaunch" })).toBeInTheDocument();
  });
});
