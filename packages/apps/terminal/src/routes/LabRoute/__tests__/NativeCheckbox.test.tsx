/** Mounted checkbox contract: native interaction never issues entry permission. */
import { createRef } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { executionSessionSchema } from "@/services/executionSessions";
import captured from "@/services/__tests__/fixtures/native-v2-read-plan-captured-v2.json";
import { NativeV2Studio } from "../NativeExecutionInspection";

const census = () => (JSON.parse(captured.initial_census.body).data as unknown[]).map(row => executionSessionSchema.parse(row));

const exact = "/api/v1/execution-sessions/mounted-native";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("retains native IDs, form names, refs and unchecked defaults in the project primitive", async () => {
  const ref = createRef<HTMLInputElement>();
  const user = userEvent.setup();
  const { rerender } = render(<>
    <Label htmlFor="checkbox-contract">Explicit checkbox choice</Label>
    <Checkbox id="checkbox-contract" name="explicit-choice" value="selected" ref={ref} />
  </>);
  const checkbox = screen.getByRole("checkbox", { name: "Explicit checkbox choice" });
  expect(ref.current).toBe(checkbox);
  expect(checkbox).toHaveAttribute("id", "checkbox-contract");
  expect(checkbox).toHaveAttribute("name", "explicit-choice");
  expect(checkbox).toHaveAttribute("value", "selected");
  expect(checkbox).not.toBeChecked();
  await user.click(screen.getByText("Explicit checkbox choice"));
  expect(checkbox).toBeChecked();
  await user.keyboard(" ");
  expect(checkbox).not.toBeChecked();
  rerender(<>
    <Label htmlFor="checkbox-contract">Explicit checkbox choice</Label>
    <Checkbox id="checkbox-contract" name="explicit-choice" value="selected" ref={ref} disabled />
  </>);
  await user.click(screen.getByText("Explicit checkbox choice"));
  expect(checkbox).toBeDisabled();
  expect(checkbox).not.toBeChecked();
});

it("uses project checkboxes with native label, keyboard and disabled behaviour without permission defaults", async () => {
  const first = captured.samples.find(row => row.path === exact && row.method === "GET")!;
  const session = executionSessionSchema.parse(JSON.parse(first.body).data);
  expect(census()).toContainEqual(session);
  const user = userEvent.setup();
  useAuthStore.setState({ status: "logged-in", token: "synthetic-checkbox-client", username: "mounted-operator",
    sessionGeneration: useAuthStore.getState().sessionGeneration + 1 });
  const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
    label: "Inert checkbox account", status: "connected" as const, is_primary: true,
    connected_at: null, error_message: null };
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
  let release: (() => void) | undefined;
  const held = new Promise<void>(resolve => { release = resolve; });
  const queue = captured.samples.slice(1, 3);
  const calls: string[] = [];
  const failures: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    try {
      calls.push(`${init?.method} ${url}`);
      const expected = queue.shift();
      expect(expected).toBeDefined();
      expect(url).toBe(`/ft-api${expected!.path}`);
      expect(init?.method).toBe(expected!.method);
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual({ authorization: "Bearer synthetic-checkbox-client" });
      expect(init?.body).toBeUndefined();
      await held;
      return new Response(expected!.body, { status: expected!.status });
    } catch (error) { failures.push(error); throw error; }
  }));
  render(<NativeV2Studio sessions={census()} census="available" />);
  await user.click(screen.getByRole("button", { name: "Inspect mounted-native" }));
  const studio = within(screen.getByRole("region", { name: "Native Studio" }));
  const names = ["Allow placement requests", "Allow cancellation of unfilled orders",
    "Inspect orders", "Inspect positions", "Inspect holdings", "Inspect trades", "Inspect fees",
    "Inspect broker_protection", "Inspect quotes"];
  try {
    expect(failures).toEqual([]);
    expect(calls).toEqual([`GET /ft-api${exact}/autonomy-v2`]);
    for (const name of names) {
      const checkbox = studio.getByRole("checkbox", { name });
      expect(checkbox).toBeDisabled();
      expect(checkbox).not.toBeChecked();
      await user.click(checkbox);
      expect(checkbox).not.toBeChecked();
    }
  } finally {
    release?.();
  }
  await waitFor(() => expect(studio.queryByRole("status")).not.toBeInTheDocument());
  for (const name of names) {
    const checkbox = studio.getByRole("checkbox", { name });
    expect(checkbox).toBeEnabled();
    expect(checkbox).not.toBeChecked();
    await user.click(studio.getByLabelText(name));
    expect(checkbox).toBeChecked();
    expect(checkbox).toHaveFocus();
    await user.keyboard(" ");
    expect(checkbox).not.toBeChecked();
  }
  await user.click(studio.getByText("Allow placement requests"));
  expect(studio.getByRole("checkbox", { name: "Allow placement requests" })).toBeChecked();
  await user.keyboard(" ");
  expect(studio.getByRole("checkbox", { name: "Allow placement requests" })).not.toBeChecked();
  for (const label of ["Maximum order quantity", "Maximum total quantity", "Maximum entry commands",
    "Maximum entry reads", "Grant duration (ms)", "Grant expiry (epoch ms)"]) {
    expect(studio.getByLabelText(label)).toHaveValue("");
  }
  for (const name of ["Preview finite custody", "Accept finite custody", "Grant finite entry permission", "Start native producer"]) {
    expect(studio.getByRole("button", { name })).toBeDisabled();
  }
  expect(calls).toEqual([`GET /ft-api${exact}/autonomy-v2`, `GET /ft-api${exact}`]);
  expect(queue).toEqual([]);
  expect(failures).toEqual([]);
  // This explicit project-primitive contract is independent of the behaviour
  // controls above; the original raw inputs must fail this Standards oracle.
  for (const name of names) expect(studio.getByRole("checkbox", { name })).toHaveAttribute("data-slot", "checkbox");
});
