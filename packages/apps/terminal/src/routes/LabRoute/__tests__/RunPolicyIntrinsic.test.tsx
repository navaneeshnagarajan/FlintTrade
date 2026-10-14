import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import type { RunScope } from "@/services/runPolicyTransport";
import { contradict, contradictions, fixtures, registerPolicy, transportFailures, type PolicyFixture } from "@/services/__tests__/runPolicy.intrinsicTestUtils";
import { RunPolicyPanel } from "../RunPolicyPanel";
import { policyWorkflows } from "../RunPolicyFields";

beforeEach(() => {
  transportFailures.length = 0;
  useAuthStore.setState(state => ({ status: "logged-in", token: "synthetic-intrinsic", username: "operator", sessionGeneration: state.sessionGeneration + 1 }));
});
afterEach(() => { vi.unstubAllGlobals(); expect(transportFailures).toEqual([]); });

async function fillForm(fixture: PolicyFixture) {
  await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: fixture.category } });
  for (const field of policyWorkflows.find(item => item.id === fixture.category)!.fields) {
    const value = field.name.split(".").reduce<unknown>((entry, key) => (entry as Record<string, unknown>)[key], fixture.proposal.value);
    fireEvent.change(screen.getByLabelText(field.label), { target: { value: field.kind === "json" ? JSON.stringify(value) : String(value) } });
  }
}

it.each(contradictions.flatMap(fault => ["selected", "ACK", "GET", "both"].map(seam => ({ ...fault, seam }))))("mounted $category $field contradictory $seam never becomes selected or verified evidence", async ({ seam, ...fault }) => {
  const { fixture } = fault;
  const paths = registerPolicy(fixture, {
    selected: seam === "selected" ? contradict(fixture.after, fault) : fixture.before,
    ack: seam === "ACK" || seam === "both" ? contradict(fixture.confirmed, fault) : fixture.confirmed,
    after: seam === "GET" || seam === "both" ? contradict(fixture.after, fault) : fixture.after,
  });
  render(<RunPolicyPanel scope={fixture.base.scope as RunScope} />);
  await fillForm(fixture);
  fireEvent.click(screen.getByRole("button", { name: "Read selected control" }));
  if (seam !== "selected") {
    await screen.findByText(/Current control revision: 0/);
    fireEvent.click(screen.getByRole("button", { name: "Preview policy" }));
    const confirm = await screen.findByRole("button", { name: "Confirm exact policy" });
    await act(async () => fireEvent.click(confirm));
  }
  await waitFor(() => expect(screen.queryByText(/Policy request pending/)).not.toBeInTheDocument());
  expect(screen.queryByText(/Policy verified by exact readback/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Selected control revision/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Preview policy" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirm exact policy" })).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toBeVisible();
  expect(paths.calls).toEqual([`GET ${paths.base}`, `GET ${paths.exact}`, ...(seam === "selected" ? [] : [`POST ${paths.base}/preview`, `POST ${paths.base}/confirm`, `GET ${paths.exact}`])]);
});

it.each(fixtures)("mounted untouched real-owner $category remains verifiable", async fixture => {
  const paths = registerPolicy(fixture);
  render(<RunPolicyPanel scope={fixture.base.scope as RunScope} />);
  await fillForm(fixture);
  expect(screen.getByRole("button", { name: "Preview policy" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Read selected control" }));
  await screen.findByText(/Current control revision: 0/);
  fireEvent.click(screen.getByRole("button", { name: "Preview policy" }));
  const confirm = await screen.findByRole("button", { name: "Confirm exact policy" });
  await act(async () => fireEvent.click(confirm));
  expect(await screen.findByText(/Policy verified by exact readback/)).toBeVisible();
  expect(screen.getByText(/Current control revision: 1/)).toBeVisible();
  expect(paths.calls).toEqual([`GET ${paths.base}`, `GET ${paths.exact}`, `POST ${paths.base}/preview`, `POST ${paths.base}/confirm`, `GET ${paths.exact}`]);
});
