/**
 * ProfileSection.test — the Profile Manager surface inside unified Settings.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, renderHook, screen, fireEvent, cleanup, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ProfileSection } from "../ProfileSection";
import { useSettingsStore } from "@/stores/settingsStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useAuthStore } from "@/stores/authStore";
import { useFeatureGate } from "@/hooks/useFeatureGate";
import { useSkillContent } from "@/hooks/useSkillContent";
import { widgetCatalog } from "@/layout/widgetFactory";

describe("ProfileSection", () => {
  beforeEach(() => {
    act(() => {
      useSettingsStore.setState({ name: "Example Operator", experience: "pro" });
      useModeStore.setState({ mode: "explore" });
      useConnectionStore.setState({ status: "disconnected" });
      useAuthStore.setState({ status: "unknown", username: null });
    });
    window.location.hash = "";
  });

  afterEach(() => cleanup());

  it.each([["beginner", "Getting Started"], ["intermediate", "Confident"], ["pro", "Expert"], ["custom", "Custom"]] as const)(
    "keeps discovery unrestricted and omits the retired %s experience label", (experience, label) => {
      act(() => useSettingsStore.setState({ experience }));
      render(<ProfileSection />);
      expect(screen.queryByText(label)).not.toBeInTheDocument();
      expect(screen.queryByText(/skill & experience/i)).not.toBeInTheDocument();
      expect(screen.getByLabelText("Operator display name")).toHaveValue("Example Operator");
      const { result } = renderHook(() => ({
        automation: useFeatureGate("route:automate"),
        content: useSkillContent(),
      }));
      expect(result.current.automation).toBe("visible");
      expect(new Set(result.current.content.availableWidgets)).toEqual(new Set(widgetCatalog.map(widget => widget.id)));
      expect(result.current.content.availableTools).toContain("trade-journal");
      expect(result.current.content.showAdvanced).toBe(true);
      // Visibility is not trading authority or a login; existing gates stay.
      expect(useModeStore.getState().mode).toBe("explore");
      expect(useAuthStore.getState().status).toBe("unknown");
    },
  );

  it("renders the operator display name", () => {
    render(<ProfileSection />);
    expect(screen.getByText("Example Operator")).toBeInTheDocument();
    expect(screen.getByLabelText("Operator display name")).toHaveValue("Example Operator");
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
    expect(screen.getByText("Example mode")).toBeInTheDocument();
    expect(screen.getByText(/gateway disconnected/i)).toBeInTheDocument();
  });

  it("reflects a connected gateway", () => {
    act(() => useConnectionStore.setState({ status: "connected" }));
    render(<ProfileSection />);
    expect(screen.getByText(/gateway connected/i)).toBeInTheDocument();
  });

  it("does not repeat the Settings navigation grid", () => {
    render(<ProfileSection />);
    expect(screen.queryByText(/Preferences & optimisation/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open brokers settings/i })).not.toBeInTheDocument();
  });

  // The most security-relevant Profile Manager actions — only shown when the
  // operator is logged in, which the other tests never set, so they were
  // entirely unrendered/untested.
  it("renders Lock and Sign out actions when logged in", () => {
    act(() => useAuthStore.setState({ status: "logged-in", username: "Example Operator" }));
    render(<ProfileSection />);
    expect(screen.getByText(/signed in as Example Operator/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /lock now/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });

  it("locks the session from the Profile Manager", () => {
    act(() => useAuthStore.setState({ status: "logged-in", username: "Example Operator" }));
    render(<ProfileSection />);
    fireEvent.click(screen.getByRole("button", { name: /lock now/i }));
    expect(useAuthStore.getState().status).toBe("pin-required");
  });

  it("signs out from the Profile Manager", () => {
    act(() => useAuthStore.setState({ status: "logged-in", username: "Example Operator" }));
    render(<ProfileSection />);
    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));
    expect(useAuthStore.getState().status).toBe("logged-out");
  });
});
