import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useAuthStore } from "@/stores/authStore";
import { createNativeV2Client, readExecutionSession } from "../executionSessions";
import captured from "./fixtures/native-v2-readonly-recovered.json";

const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
  label: "Synthetic account", status: "connected" as const, is_primary: true, connected_at: null, error_message: null };
const failures: unknown[] = [];
let clients: ReturnType<typeof createNativeV2Client>[] = [];
beforeEach(() => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-correspondence-client", username: "mounted-operator",
    sessionGeneration: useAuthStore.getState().sessionGeneration + 1 });
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
});
afterEach(() => {
  clients.forEach(client => client.dispose()); clients = [];
  vi.unstubAllGlobals();
  expect(failures.splice(0)).toEqual([]);
});
function client() { const value = createNativeV2Client(); clients.push(value); return value; }

it.each(["cash", "options", "cash-conflict"] as const)(
  "reads the fresh literal normal-factory %s configured-only pair without granting authority", async profile => {
    const queue = [...captured.profiles[profile]];
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      try {
        const row = queue.shift(); expect(row).toBeDefined();
        expect(url.replace(/^\/ft-api/, "")).toBe(row!.path);
        expect(init?.method).toBe("GET"); expect(init?.body).toBeUndefined();
        expect(Object.fromEntries(new Headers(init?.headers))).toEqual({ authorization: "Bearer synthetic-correspondence-client" });
        calls.push(url);
        return new Response(row!.body, { status: row!.status });
      } catch (error) { failures.push(error); throw error; }
    }));
    const result = await client().read("mounted-native");
    expect(result.session.run_id).toBe(result.view.scope.run_id);
    expect(result.view.transfer_receipts).toEqual([]);
    expect(result.view.duty).toBeNull();
    expect(result.session.entries_armed).toBe(false);
    expect(result.view.effective_authority).toBe("none");
    expect(calls).toHaveLength(2); expect(queue).toEqual([]);
  },
);

it.each(["native:run", "native.run", "native/run", "native\n", " native", "native ", "", "a".repeat(129)])(
  "refuses the literal unsupported run identity %j before either public read transport", async id => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await expect(client().read(id)).rejects.toBeDefined();
    await expect(readExecutionSession(id)).rejects.toBeDefined();
    expect(fetch).not.toHaveBeenCalled();
  },
);
