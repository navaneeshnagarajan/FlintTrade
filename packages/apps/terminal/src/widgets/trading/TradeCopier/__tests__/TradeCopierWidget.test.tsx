import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import TradeCopierWidget from "../TradeCopierWidget";
afterEach(() => vi.unstubAllGlobals());
describe("TradeCopierWidget retirement", () => {
  it("discloses unavailable native mirroring without arming controls or polling", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<TradeCopierWidget />);
    expect(screen.getByTestId("runtime-status")).toHaveTextContent("Unavailable");
    expect(screen.getByRole("status")).toHaveTextContent(/native account mirroring design/i);
    expect(screen.queryByRole("button", { name: /start|enable|mirror/i })).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("keeps the account overview reachable", () => {
    render(<TradeCopierWidget />);
    expect(screen.getByRole("link", { name: /account overview/i })).toHaveAttribute("href", "/ditto");
  });
});
