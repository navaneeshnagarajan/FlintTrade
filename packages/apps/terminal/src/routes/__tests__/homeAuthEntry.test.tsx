/**
 * homeAuthEntry.test.tsx — FT-HOME-003
 *
 * Direct `/home` while signed in must render Home, not the password
 * Welcome Back gate. Unauthenticated `/home` is the gate only.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { writePersistedAuthSession } from "@/lib/homeEntry";
import { useAuthStore } from "@/stores/authStore";
import ProtectedRoute from "../ProtectedRoute";

function HomeDashboard() {
  return <div data-testid="home-dashboard">Home dashboard</div>;
}

function WelcomeBackGate() {
  return <h1>Welcome Back</h1>;
}

function renderHomeEntry() {
  return render(
    <MemoryRouter initialEntries={["/home"]}>
      <Routes>
        <Route
          path="/home"
          element={(
            <ProtectedRoute>
              <HomeDashboard />
            </ProtectedRoute>
          )}
        />
        <Route path="/welcome" element={<WelcomeBackGate />} />
      </Routes>
    </MemoryRouter>,
  );
}

function resetAuth() {
  const timerId = useAuthStore.getState()._expiryTimerId;
  if (timerId !== null) clearTimeout(timerId);
  useAuthStore.setState({
    status: "unknown",
    token: null,
    reauthToken: null,
    username: null,
    expiresAt: null,
    lastActivity: Date.now(),
    sessionGeneration: 0,
    _expiryTimerId: null,
  });
}

describe("direct /home auth entry (FT-HOME-003)", () => {
  beforeEach(() => {
    resetAuth();
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders Home for a signed-in operator and never shows Welcome Back", async () => {
    useAuthStore.getState().setLoggedIn("jwt-alice", "alice", "2099-01-01T02:30:00Z");

    renderHomeEntry();

    expect(await screen.findByTestId("home-dashboard")).toBeInTheDocument();
    expect(screen.queryByText("Welcome Back")).not.toBeInTheDocument();
  });

  it("restores a tab-scoped session on address-bar /home and skips the gate", async () => {
    writePersistedAuthSession({
      token: "jwt-alice",
      username: "alice",
      expiresAt: "2099-01-01T02:30:00Z",
    });

    renderHomeEntry();

    expect(await screen.findByTestId("home-dashboard")).toBeInTheDocument();
    expect(screen.queryByText("Welcome Back")).not.toBeInTheDocument();
  });

  it("shows the Welcome Back gate when /home is opened without a session", async () => {
    useAuthStore.getState().setLoggedOut();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "success",
          data: { is_setup: true, is_locked: false },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderHomeEntry();

    await waitFor(() => {
      expect(screen.getByText("Welcome Back")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("home-dashboard")).not.toBeInTheDocument();
  });
});
