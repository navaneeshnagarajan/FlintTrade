import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.ai", () => ({
  getObsidianStatus: vi.fn(),
  listObsidianNotes: vi.fn(),
  readObsidianNote: vi.fn(),
  searchObsidianNotes: vi.fn(),
}));
import {
  getObsidianStatus,
  listObsidianNotes,
  readObsidianNote,
  searchObsidianNotes,
} from "@/services/ftApi.ai";
import ObsidianWidget from "./ObsidianWidget";

const mockStatus = getObsidianStatus as unknown as ReturnType<typeof vi.fn>;
const mockNotes = listObsidianNotes as unknown as ReturnType<typeof vi.fn>;
const mockRead = readObsidianNote as unknown as ReturnType<typeof vi.fn>;
const mockSearch = searchObsidianNotes as unknown as ReturnType<typeof vi.fn>;

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ObsidianWidget />
    </QueryClientProvider>,
  );
}

describe("ObsidianWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStatus.mockResolvedValue({ configured: true, available: true, vault_path: "/vault" });
    mockNotes.mockResolvedValue(["FlintTrade/Journal/2026-06-06.md", "Ideas/nifty.md"]);
    mockRead.mockResolvedValue({ path: "Ideas/nifty.md", content: "# Nifty\nBuy the dip." });
    mockSearch.mockResolvedValue([{ path: "Ideas/nifty.md", snippet: "Buy the dip." }]);
  });

  it("lists vault notes when available", async () => {
    renderWidget();
    expect(await screen.findByText("Ideas/nifty.md")).toBeInTheDocument();
    expect(screen.getByText("FlintTrade/Journal/2026-06-06.md")).toBeInTheDocument();
  });

  it("shows a connecting state while the vault status is loading (no empty flash)", () => {
    mockStatus.mockReturnValue(new Promise(() => {})); // never resolves
    renderWidget();
    expect(screen.getByText(/Connecting to vault/i)).toBeInTheDocument();
    expect(screen.queryByText(/Vault is empty/i)).not.toBeInTheDocument();
  });

  it("shows a setup hint and no notes when the vault is not configured", async () => {
    mockStatus.mockResolvedValue({ configured: false, available: false, vault_path: null });
    renderWidget();
    expect(await screen.findByText(/Obsidian vault not configured/i)).toBeInTheDocument();
    expect(mockNotes).not.toHaveBeenCalled();
  });

  it("opens a note's content on click", async () => {
    renderWidget();
    fireEvent.click(await screen.findByText("Ideas/nifty.md"));
    expect(await screen.findByText(/Buy the dip/i)).toBeInTheDocument();
    expect(mockRead).toHaveBeenCalledWith("Ideas/nifty.md");
  });

  it("searches the vault on submit", async () => {
    renderWidget();
    await screen.findByText("Ideas/nifty.md");
    fireEvent.change(screen.getByLabelText("Search notes"), { target: { value: "dip" } });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));
    expect(await screen.findByText(/Buy the dip/i)).toBeInTheDocument();
    expect(mockSearch).toHaveBeenCalledWith("dip");
  });
});
