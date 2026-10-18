import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SkillDraftReviewSection } from "../SkillSection";
import { useBrokerStore } from "@/stores/brokerStore";
import { BODY, NAME, VERSION, deferred, knowledgeTransport, response, row, seedKnowledgeSession } from "@/services/__tests__/knowledgeTestUtils";

const draftPath = "/ft-api/api/v1/ai/skill-drafts";
const candidate = () => row({ state: "candidate", default: false, validated: false, enabled: false, unavailable_reason: "skill rights unresolved" });
beforeEach(seedKnowledgeSession);
afterEach(() => vi.unstubAllGlobals());
function mount() {
  render(<QueryClientProvider client={new QueryClient()}><SkillDraftReviewSection /></QueryClientProvider>);
}

it("retains full source text and verifies 202 intake without claiming activation", async () => {
  const io = knowledgeTransport();
  io.routes.set(`GET ${draftPath}`, () => response({ status: "success", data: [candidate()] }));
  io.routes.set(`GET ${draftPath}/${NAME}`, () => response({ status: "success", data: { name: NAME, content: BODY } }));
  io.routes.set(`POST ${draftPath}/${NAME}/candidate`, init => {
    expect(JSON.parse(String(init.body))).toEqual({});
    return response({ status: "accepted", data: candidate() }, 202);
  });
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "View source" }));
  expect((await screen.findByLabelText("Retained draft source")).textContent).toBe(BODY);
  expect(screen.queryByRole("button", { name: /^Approve$/i })).not.toBeInTheDocument();
  expect(screen.getByText(/not activation/i)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Retain candidate" }));
  expect(await screen.findByRole("status")).toHaveTextContent(`Candidate intake verified: ${VERSION}`);
  expect(screen.getByRole("status")).toHaveTextContent(/source preserved/i);
  expect(io.requests.map(r => `${r.init.method} ${r.path}`)).toEqual([
    `GET ${draftPath}`, `GET ${draftPath}/${NAME}`, `POST ${draftPath}/${NAME}/candidate`, `GET ${draftPath}`,
  ]);
  io.assertClean();
});

it.each(["wrong-name", "wrong-version", "enabled", "wrong-status", "bad-readback", "denied"])("does not claim candidate intake on %s", async fault => {
  const io = knowledgeTransport();
  let wrote = false;
  io.routes.set(`GET ${draftPath}`, () => response({ status: "success", data: [candidate(), ...(wrote && fault === "bad-readback" ? [candidate()] : [])] }));
  io.routes.set(`POST ${draftPath}/${NAME}/candidate`, () => {
    wrote = true;
    const data = { ...candidate(), ...(fault === "wrong-name" ? { name: "different" } : {}),
      ...(fault === "wrong-version" ? { version_id: "different" } : {}), ...(fault === "enabled" ? { enabled: true } : {}) };
    if (fault === "denied") return response({ message: "operator session required" }, 403);
    return response({ status: "accepted", data }, fault === "wrong-status" ? 200 : 202);
  });
  mount();
  await userEvent.setup().click(await screen.findByRole("button", { name: "Retain candidate" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText(/Candidate intake verified:/)).not.toBeInTheDocument();
  io.assertClean();
});

it("does not report a held A intake in B or read B as A's confirmation", async () => {
  const io = knowledgeTransport();
  const held = deferred<Response>();
  let entered = false;
  io.routes.set(`GET ${draftPath}`, () => response({ status: "success", data: [candidate()] }));
  io.routes.set(`POST ${draftPath}/${NAME}/candidate`, () => { entered = true; return held.promise; });
  mount();
  await userEvent.setup().click(await screen.findByRole("button", { name: "Retain candidate" }));
  expect(entered).toBe(true);
  act(() => useBrokerStore.getState().setActiveAccount("native:dhan:account-b"));
  await waitFor(() => expect(io.requests.filter(r => r.init.method === "GET")).toHaveLength(2));
  await act(async () => held.resolve(response({ status: "accepted", data: candidate() }, 202)));
  expect(screen.queryByText(/Candidate intake verified:/)).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(io.requests.filter(r => r.init.method === "GET")).toHaveLength(2);
  io.assertClean();
});
