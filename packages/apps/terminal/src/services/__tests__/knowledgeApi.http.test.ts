import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { exportKnowledgeVersion, intakeKnowledgeDraft, knowledgeSkillSchema, listKnowledgeSkills, readKnowledgeSkill, retireKnowledgeVersion } from "../knowledgeApi";
import { useBrokerStore } from "@/stores/brokerStore";
import { BODY, SCOPE, NAME, VERSION, deferred, row, seedKnowledgeSession } from "./knowledgeTestUtils";

beforeEach(seedKnowledgeSession);
afterEach(() => vi.unstubAllGlobals());

it("exercises the production client over private-loopback HTTP with exact routes, bytes and retirement readback", async () => {
  const received: { method: string; path: string; body: string }[] = [];
  const failures: unknown[] = [];
  let retired = false;
  const skill = knowledgeSkillSchema.parse(row());
  const candidate = row({ state: "candidate", default: false, validated: false, enabled: false });
  const path = `/v1/knowledge/versions/${encodeURIComponent(VERSION)}`;
  const server = createServer(async (request: IncomingMessage, response: ServerResponse) => {
    try {
      const buffers: Buffer[] = [];
      for await (const chunk of request) buffers.push(Buffer.from(chunk));
      const body = Buffer.concat(buffers).toString();
      received.push({ method: request.method!, path: request.url!, body });
      expect(request.headers.authorization).toBe("Bearer synthetic-knowledge");
      response.setHeader("Content-Type", "application/json");
      response.setHeader("Cache-Control", "no-store");
      let payload: unknown;
      switch (`${request.method} ${request.url}`) {
        case "GET /v1/knowledge/skills": payload = { scope: SCOPE, skills: [row(retired ? { state: "retired", enabled: false } : {})] }; break;
        case `GET /v1/knowledge/skills/${NAME}`: payload = { scope: SCOPE, reference: `skill:${NAME}`, version: VERSION, body: BODY, classification: "private", receipt: "http-context" }; break;
        case `GET ${path}`: payload = { version_id: VERSION, context_scope: SCOPE, version: VERSION, kind: "skill-version", name: NAME, package_hash: skill.package_hash, origin: "learned", files: { "SKILL.md": BODY }, rights: {} }; break;
        case `POST ${path}/retire`:
          expect(JSON.parse(body)).toEqual({ reason: "HTTP review" });
          retired = true; payload = { version: VERSION, state: "retired", receipt: "http-retirement" }; break;
        case `POST /api/v1/ai/skill-drafts/${NAME}/candidate`:
          expect(body).toBe("{}"); response.statusCode = 202; payload = { status: "accepted", data: candidate }; break;
        case "GET /api/v1/ai/skill-drafts": payload = { status: "success", data: [candidate] }; break;
        default: throw new Error(`Unregistered route: ${request.method} ${request.url}`);
      }
      response.end(JSON.stringify(payload));
    } catch (error) { failures.push(error); response.statusCode = 500; response.end(JSON.stringify({ error: "inert_http_fixture_failure" })); }
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Owned HTTP port unavailable");
  const realFetch = globalThis.fetch;
  vi.stubGlobal("fetch", (url: string, init: RequestInit) => realFetch(`http://127.0.0.1:${address.port}${url.replace(/^\/ft-api/, "")}`, init));
  try {
    expect(await listKnowledgeSkills()).toEqual({ scope: SCOPE, skills: [skill] });
    expect((await readKnowledgeSkill(NAME, skill, { scope: SCOPE })).body).toBe(BODY);
    expect((await exportKnowledgeVersion(skill, { scope: SCOPE })).files["SKILL.md"]).toBe(BODY);
    expect((await intakeKnowledgeDraft(skill)).version_id).toBe(VERSION);
    expect((await retireKnowledgeVersion(skill, "HTTP review", { scope: SCOPE })).catalogue.skills[0].state).toBe("retired");
    expect(received.map(item => `${item.method} ${item.path}`)).toEqual([
      "GET /v1/knowledge/skills", `GET /v1/knowledge/skills/${NAME}`, "GET /v1/knowledge/skills",
      `GET ${path}`, `POST /api/v1/ai/skill-drafts/${NAME}/candidate`, "GET /api/v1/ai/skill-drafts",
      `POST ${path}/retire`, "GET /v1/knowledge/skills",
    ]);
    expect(failures).toEqual([]);
  } finally { server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); }
});

it("refuses a real held HTTP body after an account changes away and back", async () => {
  const entered = deferred<void>();
  const release = deferred<void>();
  let reads = 0;
  const server = createServer(async (_request, response) => {
    reads++; entered.resolve(); await release.promise;
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ scope: SCOPE, reference: `skill:${NAME}`, version: VERSION, body: BODY, classification: "private", receipt: "held-http" }));
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Owned HTTP port unavailable");
  const realFetch = globalThis.fetch;
  vi.stubGlobal("fetch", (url: string, init: RequestInit) => realFetch(`http://127.0.0.1:${address.port}${url.replace(/^\/ft-api/, "")}`, init));
  try {
    const result = readKnowledgeSkill(NAME, row(), { scope: SCOPE });
    const refused = expect(result).rejects.toThrow(/retired scope/);
    await entered.promise;
    useBrokerStore.getState().setActiveAccount("native:dhan:account-b");
    useBrokerStore.getState().setActiveAccount("native:dhan:account-a");
    release.resolve(); await refused;
    expect(reads).toBe(1);
  } finally { release.resolve(); server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); }
});
