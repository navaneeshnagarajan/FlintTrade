import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes } from "react-router";
import { useAuthStore } from "@/stores/authStore";
import ModeHonestyBar from "../ModeHonestyBar";

describe("ModeHonestyBar", () => {
  it("renders the Explore line as one static Mode row", () => {
    render(<ModeHonestyBar mode="explore" />);
    const bar = screen.getByTestId("mode-honesty-bar");
    expect(bar).toHaveAttribute("data-mode", "explore");
    expect(bar).toHaveTextContent(
      "Example data. No broker is connected and no orders are sent.",
    );
    expect(bar.querySelector("p")).toHaveClass("whitespace-nowrap");
    expect(bar).not.toHaveAttribute("role", "alert");
  });

  it("renders the Practice line", () => {
    render(<ModeHonestyBar mode="practice" />);
    const bar = screen.getByTestId("mode-honesty-bar");
    expect(bar).toHaveTextContent(
      "Practice — simulated fills, no real money.",
    );
    expect(bar).not.toHaveTextContent(/SandboxEngine/i);
  });

  it("renders the Live line", () => {
    render(<ModeHonestyBar mode="live" />);
    expect(screen.getByTestId("mode-honesty-bar")).toHaveTextContent(
      "Live — real-money capable when a broker is Connected. Orders place only on a live session.",
    );
  });

  describe("example-data session", () => {
    afterEach(() => {
      useAuthStore.setState({ token: null });
    });

    it("offers Create your account, which opens Setup", () => {
      useAuthStore.setState({ token: "demo-user" });
      render(
        <MemoryRouter initialEntries={["/home"]}>
          <Routes>
            <Route path="/home" element={<ModeHonestyBar mode="explore" />} />
            <Route path="/setup" element={<p>Setup page</p>} />
          </Routes>
        </MemoryRouter>,
      );

      fireEvent.click(screen.getByRole("button", { name: "Create your account →" }));
      expect(screen.getByText("Setup page")).toBeInTheDocument();
    });

    it("does not offer it to a signed-in operator", () => {
      useAuthStore.setState({ token: "operator-session" });
      render(<ModeHonestyBar mode="explore" />);
      expect(screen.queryByTestId("mode-bar-setup")).not.toBeInTheDocument();
    });
  });

  it("does not paint API smoke on the Mode bar", () => {
    for (const mode of ["explore", "practice", "live"] as const) {
      const { unmount } = render(<ModeHonestyBar mode={mode} />);
      const bar = screen.getByTestId("mode-honesty-bar");
      expect(bar).not.toHaveTextContent(/API smoke/i);
      if (mode === "practice") expect(bar).toHaveTextContent(/^Practice/);
      if (mode === "live") expect(bar).toHaveTextContent(/^Live/);
      unmount();
    }
  });
});
