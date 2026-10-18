import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { exportKnowledgeVersion, knowledgeSkillSchema, listKnowledgeSkills, readKnowledgeSkill } from "../knowledgeApi";
import { BODY, SCOPE, NAME, knowledgeTransport, procedure, response, row, seedKnowledgeSession } from "./knowledgeTestUtils";

beforeEach(seedKnowledgeSession);
afterEach(() => vi.unstubAllGlobals());

it("honours the stock release-label export contract while binding name, origin and package hash", async () => {
  const io = knowledgeTransport();
  const stock = knowledgeSkillSchema.parse(row({ origin: "stock", version_id: "stock:" + "c".repeat(64) }));
  const value = { kind: "skill-version", context_scope: null, version_id: stock.version_id, version: "bundled-release", name: stock.name, origin: "stock", package_hash: stock.package_hash, files: { "SKILL.md": BODY }, rights: {} };
  const path = `GET /ft-api/v1/knowledge/versions/${encodeURIComponent(stock.version_id)}`;
  io.routes.set(path, () => response(value));
  expect(await exportKnowledgeVersion(stock, { scope: null })).toEqual(value);
  io.routes.set(path, () => response({ ...value, version_id: "foreign-stock" }));
  await expect(exportKnowledgeVersion(stock, { scope: null })).rejects.toThrow(/identity mismatch/);
  io.assertClean();
});

it("distinguishes an empty authoritative catalogue from a denied read", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [] }));
  expect(await listKnowledgeSkills()).toEqual({ scope: SCOPE, skills: [] });
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ error: "context_scope_required" }, 403));
  await expect(listKnowledgeSkills()).rejects.toThrow("context_scope_required");
  io.assertClean();
});


it.each([undefined, null, "true", 1, {}])("rejects a malformed enabled flag %j without coercion", async enabled => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row({ enabled })] }));
  await expect(listKnowledgeSkills()).rejects.toThrow();
  io.assertClean();
});
it.each([
  { state: "unknown" }, { origin: "unknown" }, { enabled: true, validated: false },
  { enabled: true, default: false, run_pinned: false }, { enabled: true, unavailable_reason: "retired" },
  { enabled: true, state: "candidate" }, { name: "../risk" },
])("refuses inconsistent catalogue authority %j", async overrides => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row(overrides)] }));
  await expect(listKnowledgeSkills()).rejects.toThrow();
  io.assertClean();
});
it("refuses two enabled same-name identities instead of choosing one", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row(), row({ version_id: "other" })] }));
  await expect(listKnowledgeSkills()).rejects.toThrow();
  io.assertClean();
});
it("rejects a full body for a different same-name version", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure({ version: "replacement" })));
  await expect(readKnowledgeSkill(NAME, row(), { scope: SCOPE })).rejects.toThrow(/version|identity/i);
  io.assertClean();
});
it.each([undefined, null, { ...SCOPE, run_id: "server-run-b" }])("refuses a full body with missing or changed scope %j", async scope => {
  const io = knowledgeTransport();
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure({ scope })));
  await expect(readKnowledgeSkill(NAME, row(), { scope: SCOPE })).rejects.toThrow();
  expect(io.requests).toHaveLength(1);
  io.assertClean();
});

it("rechecks catalogue eligibility after a body read without trimming its bytes", async () => {
  const io = knowledgeTransport();
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row()] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure()));
  expect((await readKnowledgeSkill(NAME, row(), { scope: SCOPE })).body).toBe(BODY);
  expect(io.requests.map(r => r.path)).toContain("/ft-api/v1/knowledge/skills");
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => {
    io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: SCOPE, skills: [row({ enabled: false, state: "retired" })] }));
    return response(procedure());
  });
  await expect(readKnowledgeSkill(NAME, row(), { scope: SCOPE })).rejects.toThrow(/enabled|changed|unavailable/i);
  io.assertClean();
});
