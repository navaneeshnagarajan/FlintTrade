import { act, render, screen, waitFor, within } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { KnowledgeSelector, revalidateSelectedKnowledge, useSelectedKnowledge } from "../KnowledgeSelector";
import { observeKnowledgeScope } from "@/services/knowledgeScope";
import { BODY, SCOPE, NAME, VERSION, deferred, knowledgeTransport, procedure, response, row, seedKnowledgeSession } from "@/services/__tests__/knowledgeTestUtils";

beforeEach(seedKnowledgeSession);
afterEach(() => vi.unstubAllGlobals());

function SelectionConsumer({ onCommit = () => {} }: { onCommit?: (refs: string[]) => void }) {
  const [selected, setSelected] = useSelectedKnowledge();
  useLayoutEffect(() => { onCommit(selected); });
  return <><output aria-label="Task references">{selected.join(",")}</output><KnowledgeSelector selected={selected} onSelection={setSelected} /></>;
}

it.each(["account", "mode", "auth", "run"])("fences cached selection and procedure at the %s commit boundary", async change => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure()));
  const client = new QueryClient();
  client.setQueryData(["aiAgent", "practice", "status"], { mode: "practice", run_id: "run-a" });
  const commits: string[][] = [];
  render(<QueryClientProvider client={client}><SelectionConsumer onCommit={refs => commits.push(refs)} /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /Read procedure/ }));
  await user.click(await screen.findByRole("button", { name: "Select this procedure" }));
  await waitFor(() => expect(screen.getByLabelText("Task references")).toHaveTextContent(`skill:${NAME}`));
  const mark = commits.length;
  act(() => {
    if (change === "account") useBrokerStore.getState().setActiveAccount("native:dhan:account-b");
    if (change === "mode") useModeStore.setState({ mode: "live" });
    if (change === "auth") useAuthStore.setState({ sessionGeneration: 11, token: "synthetic-b" });
    if (change === "run") client.setQueryData(["aiAgent", "practice", "status"], { mode: "practice", run_id: "run-b" });
  });
  expect(screen.getByLabelText("Task references")).toBeEmptyDOMElement();
  expect(screen.queryByLabelText("Complete procedure body")).not.toBeInTheDocument();
  expect(commits.slice(mark).every(refs => refs.length === 0)).toBe(true);
  await waitFor(() => expect(io.requests.filter(r => r.path.endsWith("/skills")).length).toBeGreaterThan(2));
  io.assertClean();
});

it("discards a held A procedure after B is selected, including return to A", async () => {
  const io = knowledgeTransport();
  const held = deferred<Response>();
  let entered = false;
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => { entered = true; return held.promise; });
  render(<QueryClientProvider client={new QueryClient()}><SelectionConsumer /></QueryClientProvider>);
  await userEvent.setup().click(await screen.findByRole("button", { name: /Read procedure/ }));
  expect(entered).toBe(true);
  act(() => useBrokerStore.getState().setActiveAccount("native:dhan:account-b"));
  await screen.findByRole("button", { name: /Read procedure/ });
  act(() => useBrokerStore.getState().setActiveAccount("native:dhan:account-a"));
  await act(async () => held.resolve(response(procedure())));
  expect(screen.queryByLabelText("Complete procedure body")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Task references")).toBeEmptyDOMElement();
  io.assertClean();
});

it("does not silently replace selected identity on same-name promotion or stale catalogue", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure()));
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><SelectionConsumer /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /Read procedure/ }));
  await user.click(await screen.findByRole("button", { name: "Select this procedure" }));
  await waitFor(() => expect(screen.getByLabelText("Task references")).toHaveTextContent(`skill:${NAME}`));
  const held = deferred<Response>();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => held.promise);
  await act(async () => { void client.invalidateQueries({ queryKey: ["knowledge", "skills"] }); });
  await waitFor(() => expect(screen.getByLabelText("Task references")).toBeEmptyDOMElement());
  await act(async () => held.resolve(response({ scope: SCOPE, skills: [row({ version_id: "replacement" })] })));
  expect(screen.getByLabelText("Task references")).toBeEmptyDOMElement();
  expect(screen.queryByRole("button", { name: "Unselect this procedure" })).not.toBeInTheDocument();
  io.assertClean();
});

it("preflights intended identities for R15 without inventing a version-pinned task contract", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure()));
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><SelectionConsumer /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /Read procedure/ }));
  await user.click(await screen.findByRole("button", { name: "Select this procedure" }));
  await waitFor(() => expect(screen.getByLabelText("Task references")).toHaveTextContent(`skill:${NAME}`));
  expect(await revalidateSelectedKnowledge(client)).toEqual([`skill:${NAME}`]);
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure({ version: "replacement" })));
  await expect(revalidateSelectedKnowledge(client)).rejects.toThrow(/identity|version/);
  io.assertClean();
});

it.each(["export", "retire"])("discards a deferred %s from A without contaminating B", async operation => {
  const io = knowledgeTransport();
  const held = deferred<Response>();
  let entered = false;
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  const path = `/ft-api/v1/knowledge/versions/${encodeURIComponent(VERSION)}`;
  io.routes.set(`${operation === "export" ? "GET" : "POST"} ${path}${operation === "retire" ? "/retire" : ""}`, () => { entered = true; return held.promise; });
  render(<QueryClientProvider client={new QueryClient()}><SelectionConsumer /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: operation === "export" ? "Export canonical version" : "Retire version" }));
  if (operation === "retire") {
    await user.type(screen.getByLabelText("Retirement reason"), "Review");
    await user.click(screen.getByRole("button", { name: "Confirm retirement" }));
  }
  expect(entered).toBe(true);
  act(() => useBrokerStore.getState().setActiveAccount("native:dhan:account-b"));
  await waitFor(() => expect(io.requests.filter(r => r.path.endsWith("/skills"))).toHaveLength(2));
  await user.click(await screen.findByRole("button", { name: "Retire version" }));
  await user.type(screen.getByLabelText("Retirement reason"), "B reason");
  await act(async () => held.resolve(operation === "retire"
    ? response({ version: VERSION, state: "retired", receipt: "receipt-a" })
    : response({ version_id: VERSION, context_scope: SCOPE, version: VERSION, name: NAME, origin: "learned", kind: "skill-version", package_hash: "b".repeat(64), files: { "SKILL.md": BODY }, rights: {} })));
  expect(screen.getByLabelText("Retirement reason")).toHaveValue("B reason");
  expect(screen.queryByLabelText("Canonical version export")).not.toBeInTheDocument();
  expect(screen.queryByText(/Retirement verified:/)).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(io.requests.filter(r => r.path.endsWith("/skills"))).toHaveLength(2);
  io.assertClean();
});

it("exports an authorised exact canonical package and retires only after explicit confirmation and readback", async () => {
  const io = knowledgeTransport();
  let retired = false;
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row(retired ? { state: "retired", enabled: false } : {})] }));
  const versionPath = `/ft-api/v1/knowledge/versions/${encodeURIComponent(VERSION)}`;
  const portable = { version_id: VERSION, context_scope: SCOPE, version: VERSION, name: NAME, origin: "learned", package_hash: "b".repeat(64), kind: "skill-version", files: { "SKILL.md": BODY }, rights: { fixture: "unknown" }, scope: { account_id: "account-a", environment: "paper", run_id: "run-a" } };
  io.routes.set(`GET ${versionPath}`, () => response(portable));
  io.routes.set(`POST ${versionPath}/retire`, init => {
    expect(JSON.parse(String(init.body))).toEqual({ reason: "Superseded after independent review" });
    retired = true;
    return response({ version: VERSION, state: "retired", receipt: "retirement-receipt" });
  });
  render(<QueryClientProvider client={new QueryClient()}><SelectionConsumer /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Export canonical version" }));
  expect(JSON.parse((await screen.findByLabelText("Canonical version export")).textContent!)).toEqual(portable);
  expect(screen.getByRole("link", { name: "Download canonical JSON" })).toHaveAttribute("download");
  await user.click(screen.getByRole("button", { name: "Retire version" }));
  expect(io.requests.filter(r => r.init.method === "POST")).toHaveLength(0);
  expect(screen.getByLabelText("Confirm retirement")).toHaveTextContent(VERSION);
  expect(screen.getByRole("button", { name: "Confirm retirement" })).toBeDisabled();
  await user.type(screen.getByLabelText("Retirement reason"), "Superseded after independent review");
  await user.click(screen.getByRole("button", { name: "Confirm retirement" }));
  expect(await screen.findByText(/Retirement verified:/)).toHaveTextContent(VERSION);
  expect(screen.queryByRole("button", { name: /Read procedure/ })).not.toBeInTheDocument();
  expect(io.requests.map(r => `${r.init.method} ${r.path}`)).toEqual([
    "GET /ft-api/v1/knowledge/skills", `GET ${versionPath}`, `POST ${versionPath}/retire`, "GET /ft-api/v1/knowledge/skills",
  ]);
  io.assertClean();
});

it.each(["export-identity", "retire-identity", "retire-readback"])("refuses a mismatched %s", async fault => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  const versionPath = `/ft-api/v1/knowledge/versions/${encodeURIComponent(VERSION)}`;
  io.routes.set(`GET ${versionPath}`, () => response({ version_id: "other", context_scope: SCOPE, version: "other", name: NAME, origin: "learned", package_hash: "b".repeat(64), kind: "skill-version", files: { "SKILL.md": BODY }, rights: {} }));
  io.routes.set(`POST ${versionPath}/retire`, () => response({ version: fault === "retire-identity" ? "other" : VERSION, state: "retired", receipt: "receipt" }));
  render(<QueryClientProvider client={new QueryClient()}><SelectionConsumer /></QueryClientProvider>);
  const user = userEvent.setup();
  if (fault === "export-identity") await user.click(await screen.findByRole("button", { name: "Export canonical version" }));
  else {
    await user.click(await screen.findByRole("button", { name: "Retire version" }));
    await user.type(screen.getByLabelText("Retirement reason"), "Review");
    await user.click(screen.getByRole("button", { name: "Confirm retirement" }));
  }
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText(/Retirement verified:/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Download canonical JSON" })).not.toBeInTheDocument();
  io.assertClean();
});

it("discards a held stock body across server-only A to B to A observations", async () => {
  const io = knowledgeTransport();
  const held = deferred<Response>(); let entered = false;
  let scope = SCOPE;
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope, skills: [row({ origin: "stock" })] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => { entered = true; return held.promise; });
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><SelectionConsumer /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /Read procedure/ }));
  expect(entered).toBe(true);
  scope = { ...SCOPE, run_id: "server-run-b" };
  await user.click(screen.getByRole("button", { name: "Refresh catalogue" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /Read procedure/ })).toBeEnabled());
  scope = SCOPE;
  await user.click(screen.getByRole("button", { name: "Refresh catalogue" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /Read procedure/ })).toBeEnabled());
  await act(async () => held.resolve(response(procedure({ classification: "public" }))));
  expect(screen.queryByLabelText("Complete procedure body")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Task references")).toBeEmptyDOMElement();
  expect(io.requests.filter(r => r.path.endsWith("/skills"))).toHaveLength(3);
  io.assertClean();
});

it("refuses a prior rendered read handler at the authoritative-scope commit boundary", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure({ scope: { ...SCOPE, run_id: "server-run-b" } })));
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><SelectionConsumer /></QueryClientProvider>);
  const button = await screen.findByRole("button", { name: /Read procedure/ });
  const mark = io.requests.length;
  act(() => {
    observeKnowledgeScope(client, { ...SCOPE, run_id: "server-run-b" });
    button.click();
  });
  await act(async () => { await Promise.resolve(); });
  expect(io.requests.slice(mark)).toEqual([]);
  expect(screen.queryByLabelText("Complete procedure body")).not.toBeInTheDocument();
  io.assertClean();
});

it("retires same-stock selection on observed server-only run refresh including A to B to A", async () => {
  const io = knowledgeTransport();
  let scope = SCOPE;
  const stock = row({ origin: "stock" });
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope, skills: [stock] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure({ scope, classification: "public" })));
  const client = new QueryClient();
  const commits: string[][] = [];
  render(<QueryClientProvider client={client}><SelectionConsumer onCommit={refs => commits.push(refs)} /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /Read procedure/ }));
  await user.click(await screen.findByRole("button", { name: "Select this procedure" }));
  await waitFor(() => expect(screen.getByLabelText("Task references")).toHaveTextContent(`skill:${NAME}`));
  // No broker/auth/mode/agent-status event: only the authoritative HTTP response changes.
  scope = { ...SCOPE, run_id: "server-run-b" };
  await user.click(screen.getByRole("button", { name: "Refresh catalogue" }));
  await waitFor(() => expect(screen.getByLabelText("Task references")).toBeEmptyDOMElement());
  expect(screen.queryByLabelText("Complete procedure body")).not.toBeInTheDocument();
  const mark = commits.length;
  scope = SCOPE;
  await user.click(screen.getByRole("button", { name: "Refresh catalogue" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /Read procedure/ })).toBeEnabled());
  expect(commits.slice(mark).every(refs => refs.length === 0)).toBe(true);
  expect(client.getQueryCache().findAll({ queryKey: ["aiAgent"] })).toHaveLength(0);
  io.assertClean();
});

it("identifies history by version and offers only the enabled run-pinned procedure", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [
    row({ version_id: "candidate-history", state: "candidate", enabled: false, default: false, validated: false, unavailable_reason: "skill rights unresolved" }),
    row({ version_id: "new-default", enabled: false }),
    row({ state: "validated", default: false, run_pinned: true }),
  ] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure()));
  const selected = vi.fn();
  render(<QueryClientProvider client={new QueryClient()}><KnowledgeSelector selected={[]} onSelection={selected} /></QueryClientProvider>);
  const user = userEvent.setup();
  const rows = await screen.findAllByRole("listitem");
  expect(rows).toHaveLength(3);
  expect(within(rows[0]).getByText(/candidate-history/)).toBeInTheDocument();
  expect(within(rows[0]).queryByRole("button", { name: /Read procedure/i })).not.toBeInTheDocument();
  expect(within(rows[1]).queryByRole("button", { name: /Read procedure/i })).not.toBeInTheDocument();
  expect(within(rows[2]).getByText(/Run-pinned/)).toBeInTheDocument();
  await user.click(within(rows[2]).getByRole("button", { name: /Read procedure/i }));
  expect((await screen.findByLabelText("Complete procedure body")).textContent).toBe(BODY);
  expect(screen.getByLabelText("Procedure identity")).toHaveTextContent(VERSION);
  expect(selected).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Select this procedure" }));
  expect(selected).toHaveBeenCalledWith([`skill:${NAME}`]);
  io.assertClean();
});
