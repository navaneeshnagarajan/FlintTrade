import { Activity } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { executionSessionSchema } from "@/services/executionSessions";
import { GrantRequestV2Schema } from "@/generated/nativeAutonomyV2";
import captured from "@/services/__tests__/fixtures/native-v2-lifecycle-captured-v6.json";
import { NativeV2Studio } from "../NativeExecutionInspection";

const census = () => (JSON.parse(captured.initial_census.body).data as unknown[]).map(row => executionSessionSchema.parse(row));

const session = () => executionSessionSchema.parse(JSON.parse(captured.samples[3]!.body).data);
const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
  label: "Synthetic mounted account", status: "connected" as const, is_primary: true, connected_at: null, error_message: null };
const failures: unknown[] = [];
beforeEach(() => {
  vi.setSystemTime(new Date(session().autonomy_v2!.report!.generated_at_ms));
  useAuthStore.setState({ status: "logged-in", token: "synthetic-mounted-fence", username: "mounted-operator",
    sessionGeneration: useAuthStore.getState().sessionGeneration + 1 });
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
});
afterEach(() => {
  cleanup(); vi.unstubAllGlobals(); vi.useRealTimers();
  expect(failures.splice(0)).toEqual([]);
});

function transport(indices: number[], held?: number, malformed?: number,
  edit?: (row: typeof captured.samples[number], index: number) => void) {
  const queue = [...indices]; const calls: number[] = []; let resolve!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    try {
      const index = queue.shift(); expect(index).toBeDefined();
      const row = structuredClone(captured.samples[index!]!); edit?.(row, index!);
      expect(url.replace(/^\/ft-api/, "")).toBe(row.path); expect(init?.method).toBe(row.method);
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual(row.method === "POST"
        ? { authorization: "Bearer synthetic-mounted-fence", "content-type": "application/json" }
        : { authorization: "Bearer synthetic-mounted-fence" });
      expect(init?.body === undefined ? null : JSON.parse(String(init.body))).toEqual(row.request_json);
      calls.push(index!);
      if (index === held) return await new Promise<Response>(done => { resolve = done; });
      return new Response(index === malformed ? '{"status":"success","data":null}' : row.body, { status: row.status });
    } catch (error) { failures.push(error); throw error; }
  }));
  return { calls, queue, release: () => resolve(new Response(captured.samples[held!]!.body, { status: 200 })) };
}
async function inspect() {
  fireEvent.click(screen.getByRole("button", { name: "Inspect mounted-native" }));
  const region = within(screen.getByRole("region", { name: "Native Studio" }));
  await waitFor(() => expect(region.queryByRole("status")).not.toBeInTheDocument());
  return region;
}
function enterFiniteIntent(region: ReturnType<typeof within>) {
  const s = GrantRequestV2Schema.parse(captured.samples[4]!.request_json);
  const values = {
    "Entry instrument ID": s.limits.instruments[0]!.instrument_id,
    "Entry exchange": s.limits.instruments[0]!.exchange, "Entry product": s.limits.instruments[0]!.product,
    "Maximum order quantity": s.limits.max_order_quantity, "Maximum total quantity": s.limits.max_total_quantity,
    "Maximum entry commands": s.limits.max_commands, "Maximum entry reads": s.limits.max_reads,
    "Grant duration (ms)": s.limits.max_duration_ms, "Grant expiry (epoch ms)": s.expires_at_ms,
  };
  for (const [label, value] of Object.entries(values)) fireEvent.change(region.getByLabelText(label), { target: { value: String(value) } });
  fireEvent.click(region.getByRole("checkbox", { name: "Allow placement requests" }));
}

it("retires held finite controls on Activity hide and A-B-A without replay or resurrected drafts", async () => {
  const trace = transport([2,3,4,2,3], 4);
  const tree = (mode: "visible" | "hidden") => <Activity mode={mode}><NativeV2Studio sessions={census()} census="available" /></Activity>;
  const mounted = render(tree("visible"));
  let region = await inspect(); enterFiniteIntent(region);
  const oldControls = region.getByRole("region", { name: "Finite native permission" });
  fireEvent.click(region.getByRole("button", { name: "Preview finite custody" }));
  expect(trace.calls).toEqual([2,3,4]);
  fireEvent.click(region.getByRole("button", { name: "Preview finite custody" }));
  expect(trace.calls).toEqual([2,3,4]);
  mounted.rerender(tree("hidden"));
  const other = { ...account, account_id: "Other" };
  await act(async () => {
    useBrokerStore.setState({ accounts: [account, other], activeAccountId: brokerAccountKey(other) });
    useBrokerStore.setState({ activeAccountId: brokerAccountKey(account) });
    trace.release();
  });
  expect(oldControls).not.toBeInTheDocument();
  mounted.rerender(tree("visible"));
  expect(oldControls).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Native run evidence" })).not.toBeInTheDocument();
  expect(trace.calls).toEqual([2,3,4]);
  region = await inspect();
  expect(region.getByLabelText("Maximum order quantity")).toHaveValue("");
  expect(region.getByRole("button", { name: "Accept finite custody" })).toBeDisabled();
  expect(region.getByRole("button", { name: "Start native producer" })).toBeDisabled();
  expect(trace.calls).toEqual([2,3,4,2,3]); expect(trace.queue).toEqual([]);
});

it("renders uncertain acceptance without enabling grant or resending", async () => {
  const trace = transport([2,3,4,5,6,7,8,9], undefined, 7);
  render(<NativeV2Studio sessions={census()} census="available" />);
  const region = await inspect(); enterFiniteIntent(region);
  fireEvent.click(region.getByRole("button", { name: "Preview finite custody" }));
  await waitFor(() => expect(region.getByRole("button", { name: "Accept finite custody" })).toBeEnabled());
  fireEvent.click(region.getByRole("button", { name: "Accept finite custody" }));
  expect(await region.findByRole("alert")).toHaveTextContent("unknown");
  expect(region.getByRole("button", { name: "Grant finite entry permission" })).toBeDisabled();
  expect(region.getByRole("button", { name: "Start native producer" })).toBeDisabled();
  expect(region.getByRole("button", { name: "Read exact native status" })).toBeEnabled();
  expect(region.getByRole("button", { name: "Stop native entries" })).toBeEnabled();
  expect(trace.calls).toEqual([2,3,4,5,6,7,8,9]); expect(trace.queue).toEqual([]);
});

it.each(["model census", "account provenance", "accepted digest", "receiving operator", "receipt reference"])(
  "keeps mounted grant disabled after contradictory %s acceptance", async fault => {
    const trace = transport([2,3,4,5,6,7,8,9], undefined, undefined, (row, index) => {
      if (index !== 7) return;
      const raw = JSON.parse(row.body);
      if (fault === "model census") delete raw.data.model_obligations;
      if (fault === "account provenance") raw.data.account_provenance.credential_generation++;
      if (fault === "accepted digest") raw.data.accepted_payload_digest = "b".repeat(64);
      if (fault === "receiving operator") raw.data.receiving_operator = `operator:${"b".repeat(64)}`;
      if (fault === "receipt reference") raw.data.transfer_ref.revision = "b".repeat(64);
      row.body = JSON.stringify(raw);
    });
    render(<NativeV2Studio sessions={census()} census="available" />);
    const region = await inspect(); enterFiniteIntent(region);
    fireEvent.click(region.getByRole("button", { name: "Preview finite custody" }));
    await waitFor(() => expect(region.getByRole("button", { name: "Accept finite custody" })).toBeEnabled());
    fireEvent.click(region.getByRole("button", { name: "Accept finite custody" }));
    expect(await region.findByRole("alert")).toHaveTextContent("unknown");
    expect(region.getByRole("button", { name: "Grant finite entry permission" })).toBeDisabled();
    expect(region.getByRole("button", { name: "Start native producer" })).toBeDisabled();
    expect(trace.calls).toEqual([2,3,4,5,6,7,8,9]); expect(trace.queue).toEqual([]);
  },
);

it("retires a late acceptance across connected A-B-A without a readback or grant", async () => {
  const trace = transport([2,3,4,5,6,7,8,9], 7);
  render(<NativeV2Studio sessions={census()} census="available" />);
  const region = await inspect(); enterFiniteIntent(region);
  fireEvent.click(region.getByRole("button", { name: "Preview finite custody" }));
  await waitFor(() => expect(region.getByRole("button", { name: "Accept finite custody" })).toBeEnabled());
  fireEvent.click(region.getByRole("button", { name: "Accept finite custody" }));
  expect(trace.calls).toEqual([2,3,4,5,6,7]);
  const oldControls = region.getByRole("region", { name: "Finite native permission" });
  const other = { ...account, account_id: "Other" };
  await act(async () => {
    useBrokerStore.setState({ accounts: [account, other], activeAccountId: brokerAccountKey(other) });
    useBrokerStore.setState({ activeAccountId: brokerAccountKey(account) });
    trace.release();
  });
  expect(oldControls).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Native run evidence" })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(trace.calls).toEqual([2,3,4,5,6,7]); expect(trace.queue).toEqual([8,9]);
});

