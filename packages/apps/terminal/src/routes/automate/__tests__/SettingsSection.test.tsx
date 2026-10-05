import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom";
vi.mock("@/services/ftApi", () => ({
  getSafetyConfig: vi.fn().mockResolvedValue({ kill_switch_active: false }),
  updateSafetyConfig: vi.fn(),
  activateKillSwitch: vi.fn(),
  resetKillSwitch: vi.fn(),
}));
vi.mock("@/services/ftApi.telegram", () => ({
  readTelegramConfig: vi.fn().mockResolvedValue({ data: { enabled: false } }),
}));
vi.mock("@/services/api", () => ({ sendTelegram: vi.fn() }));
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({ emitNotification: vi.fn() }));
import SettingsSection from "../SettingsSection";

describe("Automate settings links", () => {
  it("links to the canonical settings without duplicating operational controls", () => {
    render(<MemoryRouter><QueryClientProvider client={new QueryClient()}><SettingsSection /></QueryClientProvider></MemoryRouter>);
    expect(screen.getByRole("link", { name: /risk.*safety/i })).toHaveAttribute("href", "/settings#risk");
    expect(screen.getByRole("link", { name: /telegram/i })).toHaveAttribute("href", "/settings#telegram");
    expect(screen.queryByRole("button", { name: /activate kill switch|save config|send test/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});
