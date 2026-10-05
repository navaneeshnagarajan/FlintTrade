import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { version as reactVersion } from "react";
import { useAuthStore } from "@/stores/authStore";
import { VersionInventory } from "../VersionInventory";

const mocks = vi.hoisted(() => ({ backend: vi.fn(), ollama: vi.fn() }));

beforeEach(() => {
  useAuthStore.setState({ token: "test-session" });
  // Exercise the real metadata clients; substitute only the external HTTP seam.
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const value: unknown = url.endsWith("/versions/ollama")
      ? await mocks.ollama() : url.endsWith("/versions") ? await mocks.backend() : undefined;
    if (value === undefined) throw new Error("Unexpected synthetic HTTP request");
    return new Response(JSON.stringify(value));
  }));
  mocks.backend.mockResolvedValue({
    app_version: "v0.0.1", runtimes: [{ name: "Python", version: "3.12.9" }],
    packages: [{ name: "flask", installed: "3.1.2", configured: "3.1.1" }],
    brokers: [{ name: "kotakneoapi", installed: "3.0.7", configured: "3.0.7", source_commit: "a".repeat(40), installed_commit: "b".repeat(40) }],
  });
  mocks.ollama.mockResolvedValue({ configured: "0.35.0", reported: "0.32.0", status: "reported" });
});
afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); delete window.flintDesktop; });

describe("About version inventory", () => {
  it("separates running, installed, configured and declared versions", async () => {
    render(<VersionInventory />);
    expect(within(screen.getByRole("row", { name: /^React / })).getByText(reactVersion)).toBeInTheDocument();
    expect(await screen.findByText("3.12.9")).toBeInTheDocument();
    expect(screen.getByText("3.1.2")).toBeInTheDocument();
    expect(screen.getByText("3.1.1")).toBeInTheDocument();
    expect(screen.getByText("0.32.0")).toBeInTheDocument();
    expect(screen.getByText("0.35.0")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(40))).toBeInTheDocument();
    expect(screen.getByText("b".repeat(40))).toBeInTheDocument();
    expect(screen.getByText(/does not establish broker or model qualification/)).toBeInTheDocument();
    expect(screen.getByText(/Not running in a desktop shell/)).toBeInTheDocument();
  });

  it("keeps the release compatibility baseline separate from the runtime pin", async () => {
    mocks.backend.mockResolvedValue({ app_version: "0.0.1", runtimes: [], packages: [], brokers: [
      { name: "kotakneoapi", installed: "3.0.8", configured: "3.0.8", release_version: "3.0.7", source_commit: null, installed_commit: null },
    ] });
    render(<VersionInventory />);
    expect(await screen.findByText(/kotakneoapi release compatibility baseline/)).toHaveTextContent("3.0.7");
    expect(within(screen.getByRole("table", { name: "Broker SDKs" })).getAllByText("3.0.8")).toHaveLength(2);
  });

  it("makes demo metadata unavailable without contacting the backend or Ollama", () => {
    useAuthStore.setState({ token: "demo-user" });
    render(<VersionInventory />);
    expect(screen.getByText(/Backend and Ollama versions are unavailable in Demo/)).toBeInTheDocument();
    expect(mocks.backend).not.toHaveBeenCalled();
    expect(mocks.ollama).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not turn an offline backend into an installed version", async () => {
    mocks.backend.mockRejectedValue(new Error("secret-host.example"));
    mocks.ollama.mockRejectedValue(new Error("private path"));
    render(<VersionInventory />);
    expect(await screen.findByText(/Backend version information is unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Ollama version information is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/secret-host|private path/)).not.toBeInTheDocument();
  });

  it("discards responses from a previous session and shows a non-responding Ollama endpoint honestly", async () => {
    let resolve: (value: unknown) => void = () => {};
    mocks.backend.mockReturnValue(new Promise((done) => { resolve = done; }));
    mocks.ollama.mockResolvedValue({ configured: "0.35.0", reported: null, status: "not_responding" });
    render(<VersionInventory />);
    expect(await screen.findByText("Not responding")).toBeInTheDocument();
    act(() => useAuthStore.setState({ token: "demo-user" }));
    await act(async () => resolve({ app_version: "old", runtimes: [], packages: [], brokers: [] }));
    expect(screen.queryByText("old")).not.toBeInTheDocument();
    expect(screen.getByText(/Backend and Ollama versions are unavailable in Demo/)).toBeInTheDocument();
  });
});
