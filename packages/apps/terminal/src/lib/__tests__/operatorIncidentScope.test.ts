import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { listForeverOrders } from '../brokerOrdersApi';
import { useAuthStore } from '@/stores/authStore';
import { useBrokerStore } from '@/stores/brokerStore';
import { resetOperatorSignals, useOperatorSignalStore } from '@/stores/operatorSignalStore';
beforeEach(() => { resetOperatorSignals(); useAuthStore.setState({ status: 'logged-in', token: 'synthetic-A', username: 'operator', sessionGeneration: 70 }); useBrokerStore.getState().setActiveAccount('native:dhan:A'); });
afterEach(() => vi.unstubAllGlobals());
it.each(['account', 'generation', 'account-roundtrip'] as const)('rejects retired %s incident completion at the real request seam', async change => {
  let finish!: (value: unknown) => void;
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({ ok: false, status: 429, json: () => new Promise(resolve => { finish = resolve; }) })));
  const result = listForeverOrders({ broker: 'dhan', account_id: 'A' }).catch(error => error);
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
  if (change === 'generation') useAuthStore.setState({ sessionGeneration: 71 });
  else { useBrokerStore.getState().setActiveAccount('native:dhan:B'); if (change === 'account-roundtrip') useBrokerStore.getState().setActiveAccount('native:dhan:A'); }
  finish({ status: 'error', message: 'Broker rate limit exceeded' });
  expect((await result).status).toBe(429);
  expect(useOperatorSignalStore.getState().brokerRateLimited).toBe(false);
  expect(useOperatorSignalStore.getState().brokerReject).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
});
it('still records a failure belonging to the current account/generation', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'error', message: 'Broker rate limit exceeded' }), { status: 429 })));
  await expect(listForeverOrders({ broker: 'dhan', account_id: 'A' })).rejects.toThrow('rate limit');
  expect(useOperatorSignalStore.getState().brokerRateLimited).toBe(true);
});
