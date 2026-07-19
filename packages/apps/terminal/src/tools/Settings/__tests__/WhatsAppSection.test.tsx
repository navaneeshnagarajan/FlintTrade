/**
 * WhatsAppSection.test.tsx — persist/hydrate behaviour for the WhatsApp
 * settings form (real TanStack Query; services mocked).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import "@testing-library/jest-dom";

const mockRead = vi.fn();
const mockPersist = vi.fn();
vi.mock("@/services/ftApi.whatsapp", () => ({
  readWhatsAppConfig: () => mockRead() as Promise<unknown>,
  persistWhatsAppConfig: (patch: unknown) => mockPersist(patch) as Promise<unknown>,
}));
vi.mock("@/services/ftApi.automation", () => ({
  testWhatsAppAlert: vi.fn(),
}));

import { WhatsAppSection } from "../WhatsAppSection";

interface WhatsAppSettings {
  enabled: boolean;
  phoneE164: string;
  adminUrl: string;
}

function Harness({ initial }: { initial: WhatsAppSettings }) {
  const [settings, setSettings] = useState<WhatsAppSettings>(initial);
  return (
    <WhatsAppSection
      settings={settings}
      onChangeField={(field, value) =>
        setSettings((prev) => ({ ...prev, [field]: value }))
      }
    />
  );
}

function renderSection(initial?: Partial<WhatsAppSettings>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness initial={{ enabled: false, phoneE164: "", adminUrl: "", ...initial }} />
    </QueryClientProvider>,
  );
}

describe("WhatsAppSection", () => {
  beforeEach(() => {
    mockRead.mockReset();
    mockPersist.mockReset();
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: false, webhook_url_set: false },
    });
  });

  it("hydrates the enabled flag and discloses a stored URL without revealing it", async () => {
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: true, webhook_url_set: true },
    });
    renderSection();
    await waitFor(() =>
      expect(screen.getByLabelText("WhatsApp webhook URL")).toHaveAttribute(
        "placeholder",
        expect.stringContaining("saved"),
      ),
    );
    expect(screen.getByText("Enabled")).toBeInTheDocument();
  });

  it("saves through the config endpoint and clears the draft URL", async () => {
    mockPersist.mockResolvedValue({
      status: "ok",
      data: { enabled: true, webhook_url_set: true },
    });
    renderSection({ enabled: true });

    fireEvent.change(screen.getByLabelText("WhatsApp webhook URL"), {
      target: { value: "https://bridge.example/send" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save/i }));

    await waitFor(() => expect(mockPersist).toHaveBeenCalledOnce());
    expect(mockPersist).toHaveBeenCalledWith({
      enabled: true,
      webhookUrl: "https://bridge.example/send",
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.getByLabelText("WhatsApp webhook URL")).toHaveValue("");
  });

  it("blocks saving an enabled config with no URL anywhere", async () => {
    renderSection({ enabled: true });
    await waitFor(() => expect(mockRead).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /^save/i })).toBeDisabled();
  });

  it("reports a rejected save honestly", async () => {
    mockPersist.mockRejectedValue(new Error("Enabling WhatsApp alerts requires a webhook URL"));
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: false, webhook_url_set: true },
    });
    renderSection({ enabled: true });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^save/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^save/i }));
    expect(
      await screen.findByText(/requires a webhook URL/i),
    ).toBeInTheDocument();
  });

  it("forgets the stored URL and disables alerts", async () => {
    mockRead.mockResolvedValue({
      status: "success",
      data: { enabled: true, webhook_url_set: true },
    });
    mockPersist.mockResolvedValue({
      status: "ok",
      data: { enabled: false, webhook_url_set: false },
    });
    renderSection({ enabled: true });

    const forget = await screen.findByRole("button", { name: /forget stored url/i });
    fireEvent.click(forget);

    await waitFor(() => expect(mockPersist).toHaveBeenCalledOnce());
    expect(mockPersist).toHaveBeenCalledWith({ enabled: false, clearWebhookUrl: true });
    await waitFor(() => expect(screen.getByText("Disabled")).toBeInTheDocument());
  });
});
