/**
 * LockScreen.test.tsx — Renders the lock screen UI with PIN input.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (s: {
    username: string;
    setLoggedOut: () => void;
    setLoggedIn: () => void;
  }) => unknown) =>
    selector({
      username: "testuser",
      setLoggedOut: vi.fn(),
      setLoggedIn: vi.fn(),
    }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { LockScreen } from "../LockScreen";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LockScreen", () => {
  it("renders the lock screen dialog with user name", () => {
    render(<LockScreen />);
    expect(screen.getByRole("dialog", { name: /screen locked/i })).toBeInTheDocument();
    expect(screen.getByText("testuser")).toBeInTheDocument();
  });

  it("has a hidden PIN input field", () => {
    render(<LockScreen />);
    expect(screen.getByLabelText(/enter your 6-digit pin/i)).toBeInTheDocument();
  });
});
