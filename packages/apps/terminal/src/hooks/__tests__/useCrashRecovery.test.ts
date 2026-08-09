/**
 * Tests for useCrashRecovery
 *
 * Strategy:
 *   - localStorage is mocked via vitest's built-in fake storage (vi.stubGlobal).
 *   - useBrokerConnected is mocked to control whether positions are fetched.
 *   - getPositionbook is mocked to return controlled position lists.
 *   - renderHook renders the hook; act() wraps state mutations.
 *
 * Arrange-Act-Assert pattern throughout.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// localStorage mock — must be set up before any import that reads it.
// ---------------------------------------------------------------------------

const _store: Record<string, string> = {};
const localStorageMock = {
  getItem: vi.fn((key: string) => _store[key] ?? null),
  setItem: vi.fn((key: string, value: string) => {
    _store[key] = value;
  }),
  removeItem: vi.fn((key: string) => {
    delete _store[key];
  }),
  clear: vi.fn(() => {
    Object.keys(_store).forEach((k) => delete _store[k]);
  }),
};

vi.stubGlobal("localStorage", localStorageMock);

// ---------------------------------------------------------------------------
// Module-level state for mocks
// ---------------------------------------------------------------------------

let _isConnected = false;
let _positions: Array<{ quantity: number }> = [];

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => _isConnected,
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadContext: () => ({
    identity: {
      mode: "live",
      scopeKey: "live:openalgo:default",
      brokerType: "openalgo",
      accountId: "default",
    },
    enabled: _isConnected,
    host: "",
    apiKey: "",
  }),
}));

vi.mock("@/services/api", () => ({
  getPositionbook: () => Promise.resolve(_positions),
}));

// Mock TanStack Query — we control the return value directly
vi.mock("@tanstack/react-query", () => ({
  useQuery: ({
    enabled,
  }: {
    queryFn?: () => Promise<unknown>;
    enabled?: boolean;
  }) => {
    if (!enabled) return { data: undefined };
    // Synchronously resolve for test simplicity
    return { data: _positions };
  },
}));

vi.mock("@/services/queryKeys", () => ({
  queryKeys: {
    positions: { list: (scope: string) => ["positions", "list", scope] },
  },
}));

vi.mock("@/hooks/useDataScope", () => ({
  useDataScope: () => "live:openalgo:default",
}));

// ---------------------------------------------------------------------------
// Import the hook after all mocks
// ---------------------------------------------------------------------------

import { useCrashRecovery } from "../useCrashRecovery";

const SESSION_FLAG_KEY = "flinttrade:session_active";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function clearStorage() {
  localStorageMock.clear();
  localStorageMock.getItem.mockImplementation((key: string) => _store[key] ?? null);
  localStorageMock.setItem.mockImplementation((key: string, value: string) => {
    _store[key] = value;
  });
}

// ---------------------------------------------------------------------------
// Clean session — no previous crash
// ---------------------------------------------------------------------------

describe("useCrashRecovery — clean session (no prior crash)", () => {
  beforeEach(() => {
    clearStorage();
    _isConnected = false;
    _positions = [];
  });

  it("didCrash is false when flag is absent", () => {
    // Arrange — localStorage has no flag

    // Act
    const { result } = renderHook(() => useCrashRecovery());

    // Assert
    expect(result.current.didCrash).toBe(false);
  });

  it("didCrash is false when flag is 'false' (clean exit)", () => {
    // Arrange — previous session exited cleanly
    _store[SESSION_FLAG_KEY] = "false";

    // Act
    const { result } = renderHook(() => useCrashRecovery());

    // Assert
    expect(result.current.didCrash).toBe(false);
  });

  it("sets the session flag to 'true' on mount", () => {
    // Arrange — no prior flag

    // Act
    renderHook(() => useCrashRecovery());

    // Assert — current session is now active
    expect(localStorageMock.setItem).toHaveBeenCalledWith(SESSION_FLAG_KEY, "true");
  });
});

// ---------------------------------------------------------------------------
// Crash detected — previous session did not clean up
// ---------------------------------------------------------------------------

describe("useCrashRecovery — crash detected (flag was 'true')", () => {
  beforeEach(() => {
    clearStorage();
    _store[SESSION_FLAG_KEY] = "true"; // previous session left flag set
    _isConnected = false;
    _positions = [];
  });

  it("didCrash is true when flag was 'true' on mount", () => {
    // Arrange — flag set from previous session

    // Act
    const { result } = renderHook(() => useCrashRecovery());

    // Assert
    expect(result.current.didCrash).toBe(true);
  });

  it("positionCount is null when broker is not connected", () => {
    // Arrange
    _isConnected = false;

    // Act
    const { result } = renderHook(() => useCrashRecovery());

    // Assert
    expect(result.current.positionCount).toBeNull();
  });

  it("positionCount reflects open (non-zero quantity) positions when connected", () => {
    // Arrange — 3 positions, 2 open, 1 closed
    _isConnected = true;
    _positions = [{ quantity: 75 }, { quantity: -30 }, { quantity: 0 }];

    // Act
    const { result } = renderHook(() => useCrashRecovery());

    // Assert — only non-zero quantity positions are open
    expect(result.current.positionCount).toBe(2);
  });

  it("positionCount is 0 when all positions are flat", () => {
    // Arrange
    _isConnected = true;
    _positions = [{ quantity: 0 }, { quantity: 0 }];

    // Act
    const { result } = renderHook(() => useCrashRecovery());

    // Assert
    expect(result.current.positionCount).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Clean unmount — flag is set to 'false'
// ---------------------------------------------------------------------------

describe("useCrashRecovery — clean unmount", () => {
  beforeEach(() => {
    clearStorage();
    _isConnected = false;
    _positions = [];
  });

  it("sets flag to 'false' on unmount", () => {
    // Arrange — start a clean session
    const { unmount } = renderHook(() => useCrashRecovery());

    // Act
    unmount();

    // Assert
    expect(localStorageMock.setItem).toHaveBeenCalledWith(SESSION_FLAG_KEY, "false");
  });
});

// ---------------------------------------------------------------------------
// dismiss() function
// ---------------------------------------------------------------------------

describe("useCrashRecovery — dismiss()", () => {
  beforeEach(() => {
    clearStorage();
    _store[SESSION_FLAG_KEY] = "true";
    _isConnected = false;
    _positions = [];
  });

  it("didCrash becomes false after dismiss()", () => {
    // Arrange — crash was detected
    const { result } = renderHook(() => useCrashRecovery());
    expect(result.current.didCrash).toBe(true);

    // Act
    act(() => {
      result.current.dismiss();
    });

    // Assert
    expect(result.current.didCrash).toBe(false);
  });

  it("calling dismiss() multiple times does not throw", () => {
    const { result } = renderHook(() => useCrashRecovery());

    // Act + Assert — must not throw
    expect(() => {
      act(() => {
        result.current.dismiss();
        result.current.dismiss();
      });
    }).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// localStorage unavailable (private browsing / quota exceeded)
// ---------------------------------------------------------------------------

describe("useCrashRecovery — localStorage unavailable", () => {
  beforeEach(() => {
    _isConnected = false;
    _positions = [];
  });

  it("does not throw when localStorage.getItem throws", () => {
    // Arrange — simulate storage error
    localStorageMock.getItem.mockImplementationOnce(() => {
      throw new Error("SecurityError: storage not available");
    });
    localStorageMock.setItem.mockImplementationOnce(() => {
      throw new Error("SecurityError: storage not available");
    });

    // Act + Assert — must not propagate the error
    expect(() => renderHook(() => useCrashRecovery())).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// CrashRecoveryState shape
// ---------------------------------------------------------------------------

describe("useCrashRecovery — return shape", () => {
  beforeEach(() => {
    clearStorage();
    _isConnected = false;
    _positions = [];
  });

  it("returns the expected keys", () => {
    const { result } = renderHook(() => useCrashRecovery());
    expect(result.current).toHaveProperty("didCrash");
    expect(result.current).toHaveProperty("positionCount");
    expect(result.current).toHaveProperty("dismiss");
    expect(typeof result.current.dismiss).toBe("function");
  });

  it("positionCount is null when no crash (query not triggered)", () => {
    // Arrange — clean session, no crash
    const { result } = renderHook(() => useCrashRecovery());

    // Assert — query is disabled so positionCount is null
    expect(result.current.positionCount).toBeNull();
  });
});
