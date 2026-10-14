import type { Page, TestInfo } from "@playwright/test";
import type { SyntheticPhasedFixtureRegistry, SyntheticResponse } from "./fixture-registry";
import { assertRequest, captureEvidence, exitRow, registerRead } from "./order-flow-fixtures";
import {
  ACCOUNT_A, aggregateBooks, discovery, expect, fills, journal, mount, nativePath, ok,
  pump, queryObservations, session, sessionBooks, test,
} from "./foundation-truth-fixtures";

// S2: failed fetch and fulfilled raw-body decoding are distinct evidence classes.
// Real TradeJournalTool/Log/Session, production hooks/decoder/retry policy; no writes.
const MALFORMED_JSON = '{"status":"success","data":';
type Mode = "live" | "practice";
type Resource = "trades" | "orders";
type Failure = "transport" | "raw-body-decoding";
const pathFor = (mode: Mode, resource: string) => mode === "live" ? nativePath(resource) : `/ft-api/v1/sandbox/${resource}`;
const payloadFor = (mode: Mode, resource: Resource, rows: unknown[]) => ok(mode === "live" ? rows : { [resource]: rows });
const ordersSection = (page: Page) => session(page).locator("section[aria-labelledby=ss-orders]");

test.afterEach(async ({ presentationEvidence }) => { presentationEvidence.assertWrites([]); });

function declareFailure(api: SyntheticPhasedFixtureRegistry, mode: Mode, resource: Resource, failure: Failure, phase: string) {
  const path = pathFor(mode, resource);
  api.register({
    name: `${mode} ${phase} ${resource} ${failure}`, method: "GET", path,
    expectedCalls: resource === "trades" ? 3 : 1, readPhase: "startup",
    expectedFailure: failure === "transport" ? "connectionreset" : undefined,
    handler: (request): SyntheticResponse => {
      assertRequest(request, "GET", path);
      return failure === "transport" ? { failure: "connectionreset" }
        : { status: 200, contentType: "application/json", body: MALFORMED_JSON };
    },
  });
}

async function terminalFailure(page: Page, api: SyntheticPhasedFixtureRegistry, mode: Mode, path: string, resource: Resource, info: TestInfo, phase: string) {
  const key = resource === "trades" ? "tradebook" : "orders";
  const scope = mode === "practice" ? "practice:sandbox:default" : `live:native:dhan:${ACCOUNT_A}`;
  const currentQuery = async () => (await queryObservations(page)).find((query) => query.queryKey[0] === key && query.queryKey[2] === scope);
  const observations = [];
  // These are the existing QueryProvider delays, not a replacement retry owner.
  // Observe each actual failure before advancing its timer; stay below polls.
  for (const [failureCount, delay] of resource === "trades" ? [[1, 1000], [2, 2000]] : []) {
    await pump(page, async () => (await currentQuery())?.fetchFailureCount === failureCount);
    observations.push({ checkpoint: `before retry ${failureCount}`, delay, counts: api.readCounts(path), queries: await queryObservations(page) });
    await page.clock.runFor(delay);
  }
  await pump(page, async () => {
    const query = await currentQuery();
    return query?.status === "error" && query.fetchStatus === "idle";
  });
  const query = await currentQuery();
  expect(query).toMatchObject({ status: "error", fetchStatus: "idle", fetchFailureCount: resource === "trades" ? 3 : 1 });
  expect(query?.data).toBeUndefined();
  observations.push({ checkpoint: "terminal error, not loading/paused", delay: 0, counts: api.readCounts(path), queries: await queryObservations(page) });
  await info.attach(`${phase}-retry-ledger`, { body: JSON.stringify(observations, null, 2), contentType: "application/json" });
  return query;
}

for (const mode of ["live", "practice"] as const) {
  for (const resource of ["trades", "orders"] as const) {
    for (const failure of ["transport", "raw-body-decoding"] as const) {
      test(`S2 ${mode} initial ${resource} ${failure} reaches terminal refusal with independent valid data`, async ({ page, syntheticApi }, info) => {
        discovery(syntheticApi, 1); journal(syntheticApi, mode);
        if (mode === "live") aggregateBooks(syntheticApi);
        else {
          registerRead(syntheticApi, pathFor(mode, "funds"), ok({ funds: { available_balance: 0, used_margin: 0, current_balance: 0 } }), 1, "startup");
          registerRead(syntheticApi, pathFor(mode, "positions"), ok({ positions: [] }), 1, "startup");
        }
        const path = pathFor(mode, resource);
        const other = resource === "trades" ? "orders" : "trades";
        registerRead(syntheticApi, pathFor(mode, other), payloadFor(mode, other, other === "trades" ? fills("SYNTHETIC-INDEPENDENT") : []), 1, "startup");
        declareFailure(syntheticApi, mode, resource, failure, mode === "practice" && resource === "trades" ? "Log" : "Session");
        const failures: string[] = [];
        const bodies: Array<{ status: number; body: string }> = [];
        const bodyReads: Promise<void>[] = [];
        page.on("requestfailed", (request) => {
          if (request.url() === `http://localhost:5173${path}`) failures.push(request.failure()?.errorText ?? "missing failure");
        });
        page.on("response", (response) => {
          if (response.url() === `http://localhost:5173${path}`) bodyReads.push(response.text().then((body) => { bodies.push({ status: response.status(), body }); }));
        });
        const phases = [];
        await mount(page, "session", mode, async () => {
          // Practice Log genuinely owns the same tradebook before Session.
          // An error is retried on the next observer mount; fresh success is reused.
          if (mode === "practice" && resource === "trades") {
            await terminalFailure(page, syntheticApi, mode, path, resource, info, "Log");
            await pump(page, () => page.getByRole("tabpanel", { name: "Log", exact: true }).getByText(/Failed to load fills/).isVisible());
            await expect(page.getByRole("tabpanel", { name: "Log", exact: true })).toContainText("Failed to load fills");
            phases.push({ phase: "Log", counts: await syntheticApi.retireRead(path) });
            await captureEvidence(page, info, `${mode}-${failure}-log-terminal`);
            declareFailure(syntheticApi, mode, resource, failure, "Session");
          } else {
            await pump(page, async () => (await queryObservations(page)).some((query) => query.queryKey[0] === (mode === "practice" ? "tradebook" : "tradeJournal") && query.status === "success" && query.fetchStatus === "idle"));
          }
        });
        const finalQuery = await terminalFailure(page, syntheticApi, mode, path, resource, info, "Session");
        await pump(page, () => session(page).getByText(resource === "trades" ? "Trades unavailable." : "Orders unavailable.", { exact: true }).isVisible());
        expect(finalQuery?.error).toMatch(failure === "transport" ? /Failed to fetch/ : /JSON/);
        phases.push({ phase: "Session", counts: await syntheticApi.retireRead(path) });
        await Promise.all(bodyReads);
        const expectedOutcomes = resource === "orders" ? 1 : mode === "practice" ? 6 : 3;
        expect(failures.filter((error) => error !== "net::ERR_ABORTED")).toEqual(failure === "transport" ? Array<string>(expectedOutcomes).fill("net::ERR_CONNECTION_RESET") : []);
        expect(bodies).toEqual(failure === "transport" ? [] : Array.from({ length: expectedOutcomes }, () => ({ status: 200, body: MALFORMED_JSON })));
        expect(syntheticApi.readCounts(path)).toMatchObject({
          completed: failure === "transport" ? 0 : expectedOutcomes,
          failed: failure === "transport" ? expectedOutcomes : 0, pending: 0,
        });
        if (resource === "trades") {
          await expect(session(page).getByText("Trades unavailable.", { exact: true })).toBeVisible();
          await expect(session(page).getByRole("table")).toHaveCount(0);
          await expect(session(page).locator("section[aria-labelledby=ss-stats]")).toHaveCount(0);
          await expect(session(page)).not.toContainText(/\+₹0|No round trips closed yet today|Loading trades/);
          await expect(ordersSection(page)).toHaveText(/Orders\s*Placed\s*0\s*Filled\s*0\s*Rejected\s*0\s*Pending\s*0/);
        } else {
          await expect(ordersSection(page)).toHaveText(/Orders\s*Orders unavailable\./);
          await expect(ordersSection(page)).not.toContainText(/Placed|Filled|Rejected|Pending|Loading|0/);
          await expect(session(page).getByRole("table")).toContainText("SYNTHETIC-INDEPENDENT");
          await expect(session(page)).toContainText("+₹300");
          await expect(session(page).getByRole("status", { name: `${mode === "practice" ? "Practice" : "Live"} session statistics` })).toBeVisible();
        }
        await expect(session(page)).not.toContainText(/RELIANCE|BANKNIFTY|SAMPLE/);
        if (mode === "practice") await expect(session(page).getByText("Live", { exact: true })).toHaveCount(0);
        await syntheticApi.retireRead(pathFor(mode, other));
        await info.attach("transport-body-and-phase-ledger", { body: JSON.stringify({ mode, resource, failure, expectedOutcomes, phases, failures, bodies, finalQuery }, null, 2), contentType: "application/json" });
        await captureEvidence(page, info, `${mode}-${resource}-${failure}-terminal`);
      });
    }
  }

  for (const content of ["genuine-empty", "valid-data"] as const) {
    test(`S2 ${mode} independent ${content} control preserves exact completed reads`, async ({ page, syntheticApi }, info) => {
      discovery(syntheticApi, 1);
      const rows = content === "valid-data" ? fills("SYNTHETIC-VALID") : [];
      sessionBooks(syntheticApi, rows, content === "valid-data" ? [exitRow(undefined, "FILLED")] : [], mode);
      let logReads = 0;
      await mount(page, "session", mode, async () => {
        await pump(page, async () => (await queryObservations(page)).some((query) => query.queryKey[0] === (mode === "practice" ? "tradebook" : "tradeJournal") && query.status === "success" && query.fetchStatus === "idle"));
        logReads = syntheticApi.callCount("GET", pathFor(mode, "trades"));
      });
      await pump(page, () => session(page).getByRole("table").isVisible());
      await expect(session(page)).not.toContainText(/unavailable|Loading|RELIANCE|BANKNIFTY|SAMPLE/);
      if (content === "genuine-empty") {
        await expect(session(page)).toContainText("No round trips closed yet today.");
        await expect(session(page).getByRole("table").locator("tbody tr")).toHaveCount(0);
        await expect(session(page)).toContainText("+₹0");
        await expect(ordersSection(page)).toHaveText(/Orders\s*Placed\s*0\s*Filled\s*0\s*Rejected\s*0\s*Pending\s*0/);
      } else {
        await expect(session(page).getByRole("table").locator("tbody tr")).toHaveCount(1);
        await expect(session(page).getByRole("table")).toContainText("SYNTHETIC-VALID");
        await expect(session(page)).toContainText("+₹300");
        await expect(ordersSection(page)).toHaveText(/Orders\s*Placed\s*1\s*Filled\s*1\s*Rejected\s*0\s*Pending\s*0/);
      }
      if (mode === "practice") {
        expect(syntheticApi.callCount("GET", pathFor(mode, "trades"))).toBe(logReads);
        await expect(session(page).getByText("Live", { exact: true })).toHaveCount(0);
      } else expect(logReads).toBe(0);
      const counts = {};
      for (const resource of ["trades", "orders"] as const) {
        const read = await syntheticApi.retireRead(pathFor(mode, resource));
        expect(read).toMatchObject({ completed: 1, failed: 0, pending: 0 });
        Object.assign(counts, { [resource]: read });
      }
      await info.attach("valid-control-reads", { body: JSON.stringify({ mode, content, logReads, counts }, null, 2), contentType: "application/json" });
      await captureEvidence(page, info, `${mode}-${content}-control`);
    });
  }
}
