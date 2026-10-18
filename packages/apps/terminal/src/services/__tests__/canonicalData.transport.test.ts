import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CanonicalDataClient } from "../canonicalData";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

// Produced by the real PortfolioEvidence owner on synthetic in-memory SQLite.
// Pins Python decimal/UTF-8/offset/microsecond canonicalisation independently of JS.
const scope = { principal_id: "synthetic-operator", environment: "manual_ledger", account_id: "manual:synthetic-operator", run_id: null, generation: 4 };
const record = { record_id: "synthetic-精密", kind: "transaction" as const, instrument_id: "asset-β", venue: "declared-register", currency: "USD", quantity_unit: "units", quantity: "-0.00000010", observed_at: "2026-01-02T15:30:00.123456+05:30", cash_amount: "001.2300" };
const body = { origin: "manual" as const, source_id: "synthetic-source", records: [record] };
const receipt = { batch_id: "38a7d021fc4f679f87c6e3cb1f7e29d7c9cae0d21bb1ce26ab876f8f8b5c7d24", input_sha256: "2e10b9b116bb4c5da28fc7486121bc7b35db44dfc714392d383cc4e9a154de81", count: 1, verification: "user_declared", complete: false, execution_authority: false };
const evidence = { scope, records: [{ ...record, quantity: "-1.0E-7", observed_at: "2026-01-02T10:00:00.123456+00:00", cash_amount: "1.2300", input_sha256: receipt.input_sha256, origin: "manual", source_id: body.source_id, published_at: null, retrieved_at: "2026-10-10T14:58:04.849788+00:00" }], status: "partial", complete: false, execution_authority: false, holdings_inferred_from_transactions: false };
let failures: unknown[];
let calls: string[];
beforeEach(() => {
  failures = []; calls = [];
  vi.stubGlobal("crypto", webcrypto);
  useAuthStore.setState({ status: "logged-in", token: "synthetic-session", username: "synthetic", sessionGeneration: 4 });
  useBrokerStore.setState({ activeAccountId: "native:synthetic:A" });
  useConnectionStore.setState({ apiKey: "" });
  useModeStore.setState({ mode: "live" });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    try {
      expect(url).toBe("/ft-api/api/v1/data/portfolio/evidence");
      expect(init.credentials).toBe("omit"); expect(init.cache).toBe("no-store");
      expect(new Headers(init.headers).get("Authorization")).toBe("Bearer synthetic-session");
      const method = init.method ?? "GET"; calls.push(method);
      expect(["GET", "POST"]).toContain(method);
      return new Response(JSON.stringify({ status: "success", data: method === "POST" ? receipt : evidence }), { status: method === "POST" ? 201 : 200 });
    } catch (error) { failures.push(error); throw error; }
  }));
});
afterEach(() => { vi.unstubAllGlobals(); expect(failures).toEqual([]); });
it("matches a real Python receipt without rounding decimals, Unicode identity or microsecond timestamps", async () => {
  const client = new CanonicalDataClient(); const onReceipt = vi.fn();
  const result = await client.appendPortfolio(body, scope, onReceipt);
  expect(result).toEqual({ receipt, evidence });
  expect(onReceipt).toHaveBeenCalledWith(receipt);
  expect(calls).toEqual(["POST", "GET"]);
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual(body);
});
it("rejects caller-supplied authority fields before sending a portfolio mutation", async () => {
  const input = { ...body, scope };
  await expect(new CanonicalDataClient().appendPortfolio(input, scope, vi.fn())).rejects.toThrow();
  expect(calls).toEqual([]);
});
it("permanently closes a disposed client before any replacement view can use it", async () => {
  const retired = new CanonicalDataClient();
  await retired.dispose();
  expect(retired.current()).toBe(false);
  await expect(retired.readPortfolio()).rejects.toThrow(/retired/);
  expect(calls).toEqual([]);
  expect(await new CanonicalDataClient().readPortfolio()).toEqual(evidence);
});
it("refuses preview evidence reads without touching HTTP", async () => {
  useAuthStore.setState({ token: "demo-user" });
  await expect(new CanonicalDataClient().readPortfolio()).rejects.toThrow(/unavailable session/);
  expect(calls).toEqual([]);
});
