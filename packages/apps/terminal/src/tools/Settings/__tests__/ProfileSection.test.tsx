/**
 * ProfileSection.test — the Profile Manager surface inside unified Settings.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ProfileSection } from "../ProfileSection";
import { useSettingsStore } from "@/stores/settingsStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useAuthStore } from "@/stores/authStore";

describe("ProfileSection", () => {
  beforeEach(() => {
    act(() => {
      useSettingsStore.setState({ name: "Navaneesh", experience: "pro" });
      useModeStore.setState({ mode: "explore" });
      useConnectionStore.setState({ status: "disconnected" });
      useAuthStore.setState({ status: "unknown", username: null });
    });
    window.location.hash = "";
  });

  afterEach(() => cleanup());

  it("renders the operator display name", () => {
    render(<ProfileSection />);
    expect(screen.getByText("Navaneesh")).toBeInTheDocument();
    expect(screen.getByLabelText("Operator display name")).toHaveValue("Navaneesh");
  });

  it("persists an edited display name to the settings store", () => {
    render(<ProfileSection />);
    fireEvent.change(screen.getByLabelText("Operator display name"), {
      target: { value: "Flint" },
    });
    expect(useSettingsStore.getState().name).toBe("Flint");
  });

  it("shows the live mode and connection context", () => {
    render(<ProfileSection />);
    expect(screen.getByText(/explore mode/i)).toBeInTheDocument();
    expect(screen.getByText(/gateway disconnected/i)).toBeInTheDocument();
  });

  it("reflects a connected gateway", () => {
    act(() => useConnectionStore.setState({ status: "connected" }));
    render(<ProfileSection />);
    expect(screen.getByText(/gateway connected/i)).toBeInTheDocument();
  });

  it("deep-links to a settings section via the hash", () => {
    render(<ProfileSection />);
    fireEvent.click(screen.getByRole("button", { name: /open broker gateway settings/i }));
    expect(window.location.hash).toBe("#api");
  });

  // The most security-relevant Profile Manager actions — only shown when the
  // operator is logged in, which the other tests never set, so they were
  // entirely unrendered/untested.
  it("renders Lock and Sign out actions when logged in", () => {
    act(() => useAuthStore.setState({ status: "logged-in", username: "navaneesh" }));
    render(<ProfileSection />);
    expect(screen.getByText(/signed in as navaneesh/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /lock now/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });

  it("locks the session from the Profile Manager", () => {
    act(() => useAuthStore.setState({ status: "logged-in", username: "navaneesh" }));
    render(<ProfileSection />);
    fireEvent.click(screen.getByRole("button", { name: /lock now/i }));
    expect(useAuthStore.getState().status).toBe("pin-required");
  });

  it("signs out from the Profile Manager", () => {
    act(() => useAuthStore.setState({ status: "logged-in", username: "navaneesh" }));
    render(<ProfileSection />);
    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));
    expect(useAuthStore.getState().status).toBe("logged-out");
  });
});
