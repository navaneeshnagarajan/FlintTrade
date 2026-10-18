import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RunPolicyPanel } from "../RunPolicyPanel";
import { policyWorkflows } from "../RunPolicyFields";
import { useAuthStore } from "@/stores/authStore";
import type { RunScope } from "@/services/runPolicyTransport";
import type { ExactControlSelector } from "@/services/runPolicy";
import fixtures from "@/services/__tests__/runPolicy.exact-fixture.json";

const response = (data: unknown) => new Response(JSON.stringify(data));
beforeEach(() => useAuthStore.setState(state => ({ status: "logged-in", token: "synthetic-r41", username: "operator", sessionGeneration: state.sessionGeneration + 1 })));
afterEach(() => vi.unstubAllGlobals());

async function fillForm(fixture: typeof fixtures[number]) {
  await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: fixture.category } });
  const workflow = policyWorkflows.find(item => item.id === fixture.category)!;
  for (const field of workflow.fields) {
    const value = field.name.split(".").reduce<unknown>((entry, key) => (entry as Record<string, unknown>)[key], fixture.proposal.value);
    fireEvent.change(screen.getByLabelText(field.label), { target: { value: field.kind === "json" ? JSON.stringify(value) : String(value) } });
  }
}

it.each(fixtures.flatMap(fixture => ["read-missing", "read-foreign", "read-corrupt", "late-change", "unknown-ack", "retired-get", "changed-selector"].map(fault => ({ fixture, fault, category: fixture.category }))))("mounted $category refuses $fault without replay or stale success", async ({ fixture, fault }) => {
  const scope = fixture.base.scope as RunScope;
  const base = `/v1/model-runs/${scope.run_id}/configuration`;
  const replacement = { ...scope, run_id: "replacement-run-r41" };
  const exact = `${base}/control?${new URLSearchParams(fixture.selector as ExactControlSelector)}`;
  let reads = 0; let posts = 0; let release: ((value: Response) => void) | undefined;
  const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = url.replace(/^\/ft-api/, "");
    if (path === base && init.method === "GET") return response(fixture.base);
    if (path === `/v1/model-runs/${replacement.run_id}/configuration` && init.method === "GET") return response({ ...fixture.base, scope: replacement });
    if (path === exact && init.method === "GET") {
      reads++;
      if (reads === 1) {
        if (fault === "read-missing") return response({});
        if (fault === "read-foreign") return response({ ...fixture.before, scope: replacement });
        if (fault === "read-corrupt") return response({ ...fixture.before, exact_control: { ...fixture.before.exact_control, revision: true } });
        return response(fixture.before);
      }
      if (fault === "retired-get") return new Promise<Response>(resolve => { release = resolve; });
      return response(fault === "late-change" ? { ...fixture.after, exact_control: { ...fixture.after.exact_control, revision: 2 } } : fixture.after);
    }
    if (path === `${base}/preview` && init.method === "POST") { posts++; return response(fixture.preview); }
    if (path === `${base}/confirm` && init.method === "POST") { posts++; return response(fault === "unknown-ack" ? {} : fixture.confirmed); }
    failures.push(`${init.method} ${path}`); throw new Error("unregistered request");
  }));
  const view = render(<RunPolicyPanel scope={scope} />);
  await fillForm(fixture);
  fireEvent.click(screen.getByRole("button", { name: "Read selected control" }));
  if (fault.startsWith("read-")) {
    await screen.findByRole("alert");
    expect(screen.queryByText(/Current control revision: 0/)).not.toBeInTheDocument();
    expect(posts).toBe(0); expect(reads).toBe(1);
  } else {
    await screen.findByText(/Current control revision: 0/);
    if (fault === "changed-selector") {
      if (fixture.category.startsWith("rights-")) fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: fixture.category === "rights-source" ? "rights-output" : "rights-source" } });
      else fireEvent.change(screen.getByLabelText(policyWorkflows.find(item => item.id === fixture.category)!.fields[0].label), { target: { value: "different-selector" } });
      expect(screen.getByRole("button", { name: "Preview policy" })).toBeDisabled();
      expect(posts).toBe(0); expect(reads).toBe(1);
    } else {
      fireEvent.click(screen.getByRole("button", { name: "Preview policy" }));
      fireEvent.click(await screen.findByRole("button", { name: "Confirm exact policy" }));
      if (fault === "retired-get") {
        await waitFor(() => expect(release).toBeTypeOf("function"));
        view.rerender(<RunPolicyPanel scope={replacement} />);
        await act(async () => release!(response(fixture.after)));
        await screen.findByText(/replacement-run-r41/);
        expect(screen.queryByText(/Policy request pending/)).not.toBeInTheDocument();
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      } else await screen.findByRole("alert");
      expect(posts).toBe(2); expect(reads).toBe(2);
    }
  }
  expect(screen.queryByText(/Policy verified by exact readback/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirm exact policy" })).not.toBeInTheDocument();
  expect(failures).toEqual([]);
});

it.each(fixtures)("mounted $category form reads exact authority before preview and verifies only separate durable evidence", async fixture => {
  const scope = fixture.base.scope as RunScope;
  const selector = fixture.selector as ExactControlSelector;
  const base = `/v1/model-runs/${scope.run_id}/configuration`;
  const exact = `${base}/control?${new URLSearchParams(selector)}`;
  const calls: string[] = []; const failures: string[] = [];
  let configured = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init.method} ${path}`);
    try {
      if (path === base && init.method === "GET") return response(fixture.base);
      if (path === exact && init.method === "GET") return response(configured ? fixture.after : fixture.before);
      if (path === `${base}/preview` && init.method === "POST") { expect(JSON.parse(String(init.body))).toEqual(fixture.proposal); return response(fixture.preview); }
      if (path === `${base}/confirm` && init.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({ ...fixture.proposal, confirmation: fixture.preview.confirmation });
        configured = true; return response(fixture.confirmed);
      }
      throw new Error("unregistered request");
    } catch (reason) { failures.push(String(reason)); throw reason; }
  }));
  render(<RunPolicyPanel scope={scope} />);
  await screen.findByText(/Authoritative scope/);
  fireEvent.change(screen.getByLabelText("Policy workflow"), { target: { value: fixture.category } });
  const workflow = policyWorkflows.find(item => item.id === fixture.category)!;
  for (const field of workflow.fields) {
    const value = field.name.split(".").reduce<unknown>((entry, key) => (entry as Record<string, unknown>)[key], fixture.proposal.value);
    fireEvent.change(screen.getByLabelText(field.label), { target: { value: field.kind === "json" ? JSON.stringify(value) : String(value) } });
  }
  expect(screen.getByRole("button", { name: "Preview policy" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Read selected control" }));
  await screen.findByText(/Current control revision: 0/);
  fireEvent.click(screen.getByRole("button", { name: "Preview policy" }));
  const confirm = await screen.findByRole("button", { name: "Confirm exact policy" });
  await act(async () => fireEvent.click(confirm));
  expect(await screen.findByText(/Policy verified by exact readback/)).toBeVisible();
  expect(screen.getByText(/Current control revision: 1/)).toBeVisible();
  expect(screen.queryByText(/Acknowledged only/)).not.toBeInTheDocument();
  expect(calls).toEqual([`GET ${base}`, `GET ${exact}`, `POST ${base}/preview`, `POST ${base}/confirm`, `GET ${exact}`]);
  if (fixture.category.startsWith("rights-")) await waitFor(() => expect(screen.getByLabelText("Reviewed documents (fact ID to UTF-8 text JSON)")).toHaveValue(""));
  expect(failures).toEqual([]);
});
