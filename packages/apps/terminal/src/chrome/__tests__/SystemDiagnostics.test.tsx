import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { SystemDiagnostics } from "../SystemDiagnostics";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
it("renders the mounted core diagnostics without converting unmeasured capacity or network cause into success", async () => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-diagnostics" }); useModeStore.setState({ mode: "live" });
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ status: "success", data: { schema_version: 1, observed_at: "2026-10-07T00:00:00Z", scope: "core_process", resources: { status: "degraded", gpu: { status: "unavailable", scope: "unavailable" } }, acquisition: { status: "unavailable" }, models: { status: "unmeasured", capacity: null }, jobs: { status: "unmeasured", active: null }, network_diagnosis: { status: "unmeasured", cause: null }, operational_events: { durable: false, retained: 0 }, recovery: { restart_performed: false } } }), { status: 200 }))));
  render(<QueryClientProvider client={new QueryClient()}><SystemDiagnostics /></QueryClientProvider>);
  expect(await screen.findByText('Core diagnostics')).toBeVisible();
  expect(await screen.findByText('2026-10-07T00:00:00Z')).toBeVisible();
  expect(screen.getByRole('region', { name: 'Models' })).toHaveTextContent('unmeasured');
  expect(screen.getByRole('region', { name: 'Network diagnosis' })).toHaveTextContent('Not measured / unavailable');
  expect(fetch).toHaveBeenCalledWith('/ft-api/api/v1/system/diagnostics', expect.objectContaining({ method: 'GET' }));
  vi.unstubAllGlobals();
});
