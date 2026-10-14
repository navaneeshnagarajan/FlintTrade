import { get } from "./ftApi.helpers";
import { MarketDataAuthorityChangedError } from "@/hooks/useDataScope";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";
import type { NativeAccount } from "./ftApi.native";
import { z } from "zod";

const identity = z.string().regex(/\S/);
const discoverySchema = z.looseObject({
  accounts: z.array(z.looseObject({
    adapter_id: identity,
    account_id: identity,
    label: z.string().nullable().optional(),
    is_primary: z.boolean().optional(),
    has_session: z.boolean().optional(),
    expires_at: z.number().finite().nullable().optional(),
    read_only: z.boolean().optional(),
    read_smoke_ok: z.boolean().optional(),
    needs_relogin: z.boolean().optional(),
    login_retryable: z.boolean().optional(),
    login_error: z.string().nullable().optional(),
  })),
});

type Outcome = { accounts: NativeAccount[] } | { error: unknown };
interface Discovery {
  controller: AbortController;
  borrowers: Set<(outcome: Outcome) => void>;
  stopped: boolean;
  unsubscribe: Array<() => void>;
}
let pending: Discovery | undefined;

function retire(discovery: Discovery): void {
  discovery.stopped = true;
  if (pending === discovery) pending = undefined;
  discovery.unsubscribe.forEach((unsubscribe) => unsubscribe());
  discovery.unsubscribe = [];
}

function finish(discovery: Discovery, outcome: Outcome): void {
  if (discovery.stopped) return;
  // Remove the slot before delivery; a subsequent call must acquire afresh.
  retire(discovery);
  for (const deliver of discovery.borrowers) deliver(outcome);
  discovery.borrowers.clear();
}

function accountAuthority(accounts: BrokerAccount[]): string {
  // Display labels are not authority. No credentials enter a cache key.
  return JSON.stringify(accounts.map((account) => [
    account.source, account.broker, account.account_id, account.is_primary,
    account.status, account.connected_at, account.expires_at, account.read_only,
    account.read_smoke_ok, account.needs_relogin, account.login_retryable,
  ]));
}

function observeAuthority(discovery: Discovery): void {
  const changed = () => {
    finish(discovery, { error: new MarketDataAuthorityChangedError() });
    discovery.controller.abort();
  };
  // These subscriptions live only as long as this acquisition. Synchronous
  // retirement fences A->B->A too, even if an old body ignores cancellation.
  discovery.unsubscribe = [
    useAuthStore.subscribe((next, previous) => {
      if (next.sessionGeneration !== previous.sessionGeneration || next.status !== previous.status
        || next.username !== previous.username || next.token !== previous.token) changed();
    }),
    useBrokerStore.subscribe((next, previous) => {
      if (next.activeAccountId !== previous.activeAccountId
        || accountAuthority(next.accounts) !== accountAuthority(previous.accounts)) changed();
    }),
    useConnectionStore.subscribe((next, previous) => {
      if (next.apiKey !== previous.apiKey || next.status !== previous.status
        || next.demo !== previous.demo) changed();
    }),
    useModeStore.subscribe((next, previous) => { if (next.mode !== previous.mode) changed(); }),
  ];
}

/** Share acquisition only; settled successes and failures are never cached. */
export async function discoverNativeAccounts(signal?: AbortSignal): Promise<NativeAccount[]> {
  signal?.throwIfAborted();
  const created = !pending;
  const discovery = pending ??= {
    controller: new AbortController(), borrowers: new Set(), stopped: false, unsubscribe: [],
  };
  const result = new Promise<NativeAccount[]>((resolve, reject) => {
    const deliver = (outcome: Outcome) => {
      signal?.removeEventListener("abort", cancel);
      discovery.borrowers.delete(deliver);
      if ("error" in outcome) reject(outcome.error);
      else resolve(outcome.accounts);
    };
    const cancel = () => {
      deliver({ error: signal?.reason });
      if (!discovery.stopped && discovery.borrowers.size === 0) {
        retire(discovery);
        discovery.controller.abort();
      }
    };
    discovery.borrowers.add(deliver);
    signal?.addEventListener("abort", cancel, { once: true });
  });
  if (created) {
    observeAuthority(discovery);
    void get<unknown>("native/accounts", discovery.controller.signal).then(
      (value) => {
        if (discovery.stopped) return;
        const parsed = discoverySchema.safeParse(value);
        finish(discovery, parsed.success
          ? { accounts: parsed.data.accounts }
          : { error: new Error("Native account discovery is unavailable or malformed.") });
      },
      (error: unknown) => finish(discovery, { error }),
    );
  }
  return result;
}
