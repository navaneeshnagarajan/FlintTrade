import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { GrantRequestV2Schema } from "@/generated/nativeAutonomyV2";
import { executionSessionSchema } from "@/services/executionSessions";
import captured from "@/services/__tests__/fixtures/native-v2-lifecycle-captured-v6.json";
import { NativeV2Studio } from "../NativeExecutionInspection";

const census = () => (JSON.parse(captured.initial_census.body).data as unknown[]).map(row => executionSessionSchema.parse(row));

const exact = "/api/v1/execution-sessions/mounted-native";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("requires explicit finite custody, grant and separate Start through the real exported client", async () => {
  const first = captured.samples.find(row => row.path === exact && row.method === "GET")!;
  const session = executionSessionSchema.parse(JSON.parse(first.body).data);
  const preview = captured.samples.find(row => row.path.endsWith("/transfer-preview"))!;
  const selection = GrantRequestV2Schema.parse(preview.request_json);
  vi.setSystemTime(new Date(session.autonomy_v2!.report!.generated_at_ms));
  useAuthStore.setState({ status: "logged-in", token: "synthetic-studio-ui", username: "mounted-operator",
    sessionGeneration: useAuthStore.getState().sessionGeneration + 1 });
  const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
    label: "Inert normal-factory account", status: "connected" as const, is_primary: true,
    connected_at: null, error_message: null };
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
  // Literal producer exchanges after configuration/qualification. No response
  // is reconstructed, normalised or relabelled to make the journey succeed.
  const queue = captured.samples.slice(2);
  const failures: unknown[] = [];
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    try {
      const expected = queue.shift();
      expect(expected).toBeDefined();
      const path = url.replace(/^\/ft-api/, "");
      calls.push(`${init?.method} ${path}`);
      expect(path).toBe(expected!.path);
      expect(init?.method).toBe(expected!.method);
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual(init?.method === "POST"
        ? { authorization: "Bearer synthetic-studio-ui", "content-type": "application/json" }
        : { authorization: "Bearer synthetic-studio-ui" });
      if (init?.body) expect(JSON.parse(String(init.body))).toEqual(expected!.request_json);
      return new Response(expected!.body, { status: expected!.status });
    } catch (error) { failures.push(error); throw error; }
  }));
  render(<NativeV2Studio sessions={census()} census="available" />);
  fireEvent.click(screen.getByRole("button", { name: "Inspect mounted-native" }));
  const studio = within(screen.getByRole("region", { name: "Native Studio" }));
  await waitFor(() => expect(studio.queryByRole("status")).not.toBeInTheDocument());
  for (const label of ["Maximum order quantity", "Maximum total quantity", "Maximum entry commands",
    "Maximum entry reads", "Grant duration (ms)", "Grant expiry (epoch ms)"]) {
    expect(studio.getByLabelText(label)).toHaveValue("");
  }
  expect(studio.getByRole("button", { name: "Preview finite custody" })).toBeDisabled();
  const values: Record<string, string> = {
    "Entry instrument ID": selection.limits.instruments[0]!.instrument_id,
    "Entry exchange": selection.limits.instruments[0]!.exchange,
    "Entry product": selection.limits.instruments[0]!.product,
    "Maximum order quantity": String(selection.limits.max_order_quantity),
    "Maximum total quantity": String(selection.limits.max_total_quantity),
    "Maximum entry commands": String(selection.limits.max_commands),
    "Maximum entry reads": String(selection.limits.max_reads),
    "Grant duration (ms)": String(selection.limits.max_duration_ms),
    "Grant expiry (epoch ms)": String(selection.expires_at_ms),
  };
  for (const [label, value] of Object.entries(values)) fireEvent.change(studio.getByLabelText(label), { target: { value } });
  fireEvent.click(studio.getByRole("checkbox", { name: "Allow placement requests" }));
  fireEvent.click(studio.getByRole("button", { name: "Preview finite custody" }));
  await waitFor(() => expect(studio.getByRole("button", { name: "Accept finite custody" })).toBeEnabled());
  expect(calls.filter(call => call.endsWith("/grant") || call.endsWith("/start"))).toEqual([]);
  fireEvent.click(studio.getByRole("button", { name: "Accept finite custody" }));
  await waitFor(() => expect(studio.getByRole("button", { name: "Grant finite entry permission" })).toBeEnabled());
  fireEvent.click(studio.getByRole("button", { name: "Grant finite entry permission" }));
  await waitFor(() => expect(studio.getByRole("button", { name: "Start native producer" })).toBeEnabled());
  expect(studio.getByText("granted / not_started")).toBeVisible();
  expect(calls.filter(call => call.endsWith("/start"))).toEqual([]);
  fireEvent.click(studio.getByRole("button", { name: "Start native producer" }));
  await studio.findByText("started / running");
  fireEvent.click(studio.getByRole("button", { name: "Stop native entries" }));
  await studio.findByText("retired / stopped");
  expect(studio.getByText(/does not cancel exchange orders/)).toBeVisible();
  expect(queue).toEqual([]);
  expect(failures).toEqual([]);
});
