/**
 * Tests for useBrokerConnected
 *
 * Strategy:
 *   - useBrokerConnected combines two independent connection paths:
 *       1. Direct broker mode: any unified BrokerAccount in brokerStore with status "connected"
 *       2. Legacy mode: OpenAlgo connection in connectionStore with status "connected"
 *   - Both stores are mocked at the module level so we control the state returned
 *     by each selector call without spinning up Zustand's persist/devtools layers.
 *   - useBrokerAccounts is mocked separately; AppLayout owns its single gated
 *     gateway/native poll, so this read-only hook must not mount another observer.
 *   - renderHook renders the hook in a minimal React environment.
 *   - rerender() is used to verify reactive updates when store state changes.
 *
 * Arrange-Act-Assert pattern is applied to every test.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Store mocks — defined BEFORE importing the hook so vi.mock hoisting works.
// ---------------------------------------------------------------------------

const mocks = vi.hoisted(() => ({
  useBrokerAccounts: vi.fn(() => ({ isLoading: false, error: null, refetch: vi.fn() })),
}));

// Module-level variables that drive both mock selectors.
let _brokerAccounts: Array<{ status: string; source?: "gateway" | "native" }> = [];
let _legacyStatus = "disconnected";
let _mode = "live";

vi.mock("@/stores/brokerStore", () => ({
  useBrokerStore: (
    selector: (s: { accounts: Array<{ status: string; source?: "gateway" | "native" }> }) => unknown,
  ) => selector({ accounts: _brokerAccounts }),
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: { status: string }) => unknown) =>
    selector({ status: _legacyStatus }),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => selector({ mode: _mode }),
}));

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: mocks.useBrokerAccounts,
}));

// useShallow is a pass-through in tests — the mock already handles the selector.
vi.mock("zustand/react/shallow", () => ({
  useShallow: (selector: unknown) => selector,
}));

// ---------------------------------------------------------------------------
// Hook import — after mocks so module resolution uses the mocked modules.
// ---------------------------------------------------------------------------

import { useBrokerConnected, useDirectBrokerConnected } from "../useBrokerConnected";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function connectedAccount(source: "gateway" | "native" = "gateway") {
  return { status: "connected", source } as const;
}

function disconnectedAccount(source: "gateway" | "native" = "gateway") {
  return { status: "disconnected", source } as const;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useBrokerConnected — initial / disconnected state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _brokerAccounts = [];
    _legacyStatus = "disconnected";
    _mode = "live";
  });

  it("returns false on initial state (no accounts, legacy disconnected)", () => {
    // Arrange — both stores in default empty/disconnected state (set in beforeEach)

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(false);
  });

  it("returns false when brokerStore has no accounts and legacy is disconnected", () => {
    // Arrange
    _brokerAccounts = [];
    _legacyStatus = "disconnected";

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(false);
  });

  it("returns false when brokerStore accounts all have non-connected status", () => {
    // Arrange
    _brokerAccounts = [disconnectedAccount(), { status: "error" }, { status: "authenticating" }];
    _legacyStatus = "disconnected";

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(false);
  });
});

describe("useBrokerConnected — legacy (OpenAlgo) connection path", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _brokerAccounts = [];
    _legacyStatus = "disconnected";
    _mode = "live";
  });

  it("returns true when connectionStore status is 'connected'", () => {
    // Arrange
    _legacyStatus = "connected";

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(true);
  });

  it("returns false when connectionStore status is 'connecting'", () => {
    // Arrange — in-progress connection is not yet connected
    _legacyStatus = "connecting";

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(false);
  });

  it("returns false when connectionStore status is 'error'", () => {
    // Arrange
    _legacyStatus = "error";

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(false);
  });
});

describe("useBrokerConnected — gateway (broker account) connection path", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _brokerAccounts = [];
    _legacyStatus = "disconnected";
    _mode = "live";
  });

  it("returns true when at least one BrokerAccount has status 'connected'", () => {
    // Arrange
    _brokerAccounts = [connectedAccount()];

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(true);
  });

  it("returns true when one of multiple accounts is connected", () => {
    // Arrange — mixed statuses; one connected account is sufficient
    _brokerAccounts = [disconnectedAccount(), connectedAccount(), { status: "error" }];

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(true);
  });

  it("returns false when accounts list is present but none are connected", () => {
    // Arrange
    _brokerAccounts = [disconnectedAccount(), { status: "token_expired" }];

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(false);
  });
});

describe("useBrokerConnected — OR logic between both paths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _brokerAccounts = [];
    _legacyStatus = "disconnected";
    _mode = "live";
  });

  it("returns true when both paths are connected simultaneously", () => {
    // Arrange — gateway account connected AND legacy connected
    _brokerAccounts = [connectedAccount()];
    _legacyStatus = "connected";

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert — OR: either path is sufficient
    expect(result.current).toBe(true);
  });

  it("returns true when only legacy path is connected (no gateway accounts)", () => {
    // Arrange
    _brokerAccounts = [];
    _legacyStatus = "connected";

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(true);
  });

  it("returns true when only gateway path is connected (legacy disconnected)", () => {
    // Arrange
    _brokerAccounts = [connectedAccount()];
    _legacyStatus = "disconnected";

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(true);
  });

  it("returns true when only a native unified-account row is connected", () => {
    // Arrange
    _brokerAccounts = [connectedAccount("native")];

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(true);
  });

  it("returns false when native unified-account rows exist but none are connected", () => {
    // Arrange
    _brokerAccounts = [disconnectedAccount("native"), { status: "token_expired", source: "native" }];

    // Act
    const { result } = renderHook(() => useBrokerConnected());

    // Assert
    expect(result.current).toBe(false);
  });

  it("returns false in Explore while legacy Live connection state is still hydrated", () => {
    _mode = "explore";
    _legacyStatus = "connected";

    const { result } = renderHook(() => useBrokerConnected());

    expect(result.current).toBe(false);
  });

  it("returns false in Explore while native Live connection state is still hydrated", () => {
    _mode = "explore";
    _brokerAccounts = [connectedAccount("native")];

    const { result } = renderHook(() => useBrokerConnected());

    expect(result.current).toBe(false);
  });
});

describe("useDirectBrokerConnected — excludes legacy OpenAlgo store status", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _brokerAccounts = [];
    _legacyStatus = "disconnected";
    _mode = "live";
  });

  it("returns false when only the legacy OpenAlgo status is connected", () => {
    _legacyStatus = "connected";

    const { result } = renderHook(() => useDirectBrokerConnected());

    expect(result.current).toBe(false);
  });

  it("returns true for a connected gateway account", () => {
    _brokerAccounts = [connectedAccount()];

    const { result } = renderHook(() => useDirectBrokerConnected());

    expect(result.current).toBe(true);
  });

  it("returns true for a live native session", () => {
    _brokerAccounts = [connectedAccount("native")];

    const { result } = renderHook(() => useDirectBrokerConnected());

    expect(result.current).toBe(true);
  });

  it("reads the unified store without mounting a second broker-account poll", () => {
    renderHook(() => useDirectBrokerConnected());

    expect(mocks.useBrokerAccounts).not.toHaveBeenCalled();
  });
});

describe("useBrokerConnected — reactivity on state change", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _brokerAccounts = [];
    _legacyStatus = "disconnected";
    _mode = "live";
  });

  it("updates from false to true when legacy status changes to connected", () => {
    // Arrange — start disconnected
    _legacyStatus = "disconnected";
    const { result, rerender } = renderHook(() => useBrokerConnected());
    expect(result.current).toBe(false);

    // Act — simulate connection
    _legacyStatus = "connected";
    rerender();

    // Assert — hook reflects updated state
    expect(result.current).toBe(true);
  });

  it("updates from true to false when legacy status changes to disconnected", () => {
    // Arrange — start connected
    _legacyStatus = "connected";
    const { result, rerender } = renderHook(() => useBrokerConnected());
    expect(result.current).toBe(true);

    // Act — simulate disconnection
    _legacyStatus = "disconnected";
    rerender();

    // Assert
    expect(result.current).toBe(false);
  });

  it("updates from false to true when a gateway account is added as connected", () => {
    // Arrange — start with no accounts
    _brokerAccounts = [];
    const { result, rerender } = renderHook(() => useBrokerConnected());
    expect(result.current).toBe(false);

    // Act — gateway account added with connected status
    _brokerAccounts = [connectedAccount()];
    rerender();

    // Assert
    expect(result.current).toBe(true);
  });

  it("stays true when legacy disconnects but gateway account remains connected", () => {
    // Arrange — both paths connected
    _brokerAccounts = [connectedAccount()];
    _legacyStatus = "connected";
    const { result, rerender } = renderHook(() => useBrokerConnected());
    expect(result.current).toBe(true);

    // Act — legacy disconnects, gateway still connected
    _legacyStatus = "disconnected";
    rerender();

    // Assert — OR logic: still true
    expect(result.current).toBe(true);
  });

  it("updates from false to true when a native account establishes a session", () => {
    // Arrange — start with no native session
    _brokerAccounts = [];
    const { result, rerender } = renderHook(() => useBrokerConnected());
    expect(result.current).toBe(false);

    // Act — native account now has a live broker session
    _brokerAccounts = [connectedAccount("native")];
    rerender();

    // Assert
    expect(result.current).toBe(true);
  });
});
