import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { listKnowledgeSkills } from "../knowledgeApi";
import { SCOPE, knowledgeTransport, response, seedKnowledgeSession } from "./knowledgeTestUtils";

beforeEach(seedKnowledgeSession);
afterEach(() => vi.unstubAllGlobals());

it.each([undefined, {}, { ...SCOPE, run_id: "" }, { ...SCOPE, environment: "practice" }, { ...SCOPE, account_id: 7 }, { ...SCOPE, extra: true }])("refuses missing or malformed authoritative scope %j", async scope => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ skills: [], scope }));
  await expect(listKnowledgeSkills()).rejects.toThrow();
  io.assertClean();
});
it("preserves explicit server null rather than interpreting it as unavailable", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ skills: [], scope: null }));
  expect(await listKnowledgeSkills()).toEqual({ skills: [], scope: null });
  io.assertClean();
});
