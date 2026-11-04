import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { InspectRequestV2Schema } from "@/generated/nativeAutonomyV2";
import { executionSessionSchema } from "@/services/executionSessions";
import captured from "@/services/__tests__/fixtures/native-v2-read-plan-captured-v2.json";
import { NativeV2Studio } from "../NativeExecutionInspection";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("submits all explicitly selected surfaces through the exported client and keeps incomplete evidence blocked", async () => {
  const census = () => (JSON.parse(captured.initial_census.body).data as unknown[]).map(row => executionSessionSchema.parse(row));

const exact = "/api/v1/execution-sessions/mounted-native";
  const samples = captured.samples.filter(row => row.path.startsWith("/api/v1/execution-sessions"));
  const first = samples.find(row => row.method === "GET" && row.path === exact)!;
  const session = executionSessionSchema.parse(JSON.parse(first.body).data);
  expect(census()).toContainEqual(session);
  const selected = InspectRequestV2Schema.parse(samples.find(row => row.path.endsWith("/inspect"))!.request_json);
  vi.setSystemTime(new Date(selected.read_plan.deadline_ms - 9000));
  useAuthStore.setState({ status: "logged-in", token: "synthetic-read-plan-client", username: "mounted-operator",
    sessionGeneration: useAuthStore.getState().sessionGeneration + 1 });
  const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
    label: "Captured read account", status: "connected" as const, is_primary: true, connected_at: null, error_message: null };
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
  const queue = samples.slice(1); const calls: string[] = []; const failures: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    try {
      const row = queue.shift(); expect(row).toBeDefined();
      expect(url.replace(/^\/ft-api/, "")).toBe(row!.path); expect(init?.method).toBe(row!.method);
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual(row!.method === "POST"
        ? { authorization: "Bearer synthetic-read-plan-client", "content-type": "application/json" }
        : { authorization: "Bearer synthetic-read-plan-client" });
      expect(init?.body === undefined ? null : JSON.parse(String(init.body))).toEqual(row!.request_json);
      calls.push(`${row!.method} ${row!.path}`);
      return new Response(row!.body, { status: row!.status });
    } catch (error) { failures.push(error); throw error; }
  }));
  render(<NativeV2Studio sessions={census()} census="available" />);
  fireEvent.click(screen.getByRole("button", { name: "Inspect mounted-native" }));
  const studio = within(screen.getByRole("region", { name: "Native Studio" }));
  await waitFor(() => expect(studio.queryByRole("status")).not.toBeInTheDocument());
  expect(studio.getByRole("button", { name: "Inspect selected surfaces" })).toBeDisabled();
  expect(studio.getByLabelText("Maximum inspection reads")).toHaveValue("");
  for (const surface of selected.read_plan.surfaces) fireEvent.click(studio.getByRole("checkbox", { name: `Inspect ${surface}` }));
  fireEvent.change(studio.getByLabelText("Maximum inspection reads"), { target: { value: String(selected.read_plan.max_reads) } });
  fireEvent.change(studio.getByLabelText("Maximum inspection pages"), { target: { value: String(selected.read_plan.max_pages) } });
  fireEvent.change(studio.getByLabelText("Inspection deadline (local time)"), {
    target: { value: new Date(selected.read_plan.deadline_ms).toISOString().slice(0, -1) },
  });
  fireEvent.click(studio.getByRole("button", { name: "Inspect selected surfaces" }));
  await studio.findByText("Qualification: blocked. A report never grants entry authority.");
  expect(studio.getByRole("button", { name: "Start native producer" })).toBeDisabled();
  expect(studio.getByText(/Missing fee windows or quote instruments remain unavailable/)).toBeVisible();
  expect(calls.filter(call => call.startsWith("POST"))).toEqual([`POST ${exact}/autonomy-v2/inspect`]);
  expect(queue).toEqual([]); expect(failures).toEqual([]);
});
