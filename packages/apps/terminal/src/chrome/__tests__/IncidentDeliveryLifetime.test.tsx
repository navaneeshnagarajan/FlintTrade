// Test source: GNU AGPL v3, as licensed in the repository LICENSE.
import { Activity, StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { SystemDiagnostics } from '@/chrome/SystemDiagnostics';
import { useAuthStore } from '@/stores/authStore';
import { useModeStore } from '@/stores/modeStore';
import { useBrokerStore } from '@/stores/brokerStore';
import { useConnectionStore } from '@/stores/connectionStore';

const id = '44444444-4444-4444-8444-444444444444';
const claim = '55555555-5555-4555-8555-555555555555';
const instant = '2026-10-12T00:00:00Z';
const delivery = { id, channel: 'desktop', state: 'browser_pending', attempts: 0, updated_at: instant };
function snapshot() {
  return { schema_version: 1, observed_at: instant, scope: 'core_process', resources: {}, acquisition: {}, models: {}, jobs: {}, network_diagnosis: {}, recovery: {}, operational_events: {
    status: 'available', durable: true, retention: 'until_manual_deletion', has_more: false, next_cursor: null,
    incidents: [{ id: '66666666-6666-4666-8666-666666666666', correlation_id: 'inert-correlation', observed_at: instant, source: 'core_http', scope: 'core_process', severity: 'critical', code: 'http_failure', freshness: 'observed', measurement: {}, root_cause: { state: 'unknown', code: null }, deliveries: [delivery] }],
  } };
}
afterEach(() => { useAuthStore.getState().setLoggedOut(); cleanup(); onlineManager.setOnline(true); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('finishes the original claimed attempt across StrictMode replay without resending', async () => {
  useAuthStore.setState({ status: 'logged-in', token: 'inert-lifetime', username: 'synthetic' });
  useModeStore.setState({ mode: 'practice' });
  class Notification { static permission = 'denied'; }
  vi.stubGlobal('Notification', Notification);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['system', 'diagnostics'], snapshot());
  const calls: string[] = []; const unexpected: string[] = []; const failures: unknown[] = [];
  let release!: (response: Response) => void;
  const held = new Promise<Response>(resolve => { release = resolve; });
  let signal: AbortSignal | null | undefined;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    const key = `${init.method} ${url}`; calls.push(key);
    try {
      if (key === `POST /ft-api/api/v1/system/incidents/deliveries/${id}/claim`) { signal = init.signal; return await held; }
      if (key === `POST /ft-api/api/v1/system/incidents/deliveries/${id}/receipt`) {
        expect(init.body).toBe(JSON.stringify({ claim, state: 'failed' }));
        return new Response(JSON.stringify({ ...delivery, state: 'failed', attempts: 1 }));
      }
      if (key === 'GET /ft-api/api/v1/system/diagnostics') {
        const value = snapshot(); value.operational_events.incidents[0]!.deliveries = [{ ...delivery, state: 'failed', attempts: 1 }];
        return new Response(JSON.stringify({ status: 'success', data: value }));
      }
      unexpected.push(key); throw new Error(key);
    } catch (error) { failures.push(error); throw error; }
  }));
  try {
    render(<StrictMode><QueryClientProvider client={client}><SystemDiagnostics /></QueryClientProvider></StrictMode>);
    expect(calls.filter(key => key.endsWith('/claim'))).toHaveLength(1);
    expect(signal?.aborted).toBe(false);
    await act(async () => { release(new Response(JSON.stringify({ id, claim, state: 'sending' }))); });
    await waitFor(() => expect(calls.filter(key => key.endsWith('/receipt'))).toHaveLength(1));
    expect(await screen.findByText('Failed — explicit retry required')).toBeVisible();
    expect(calls.filter(key => key.endsWith('/claim'))).toHaveLength(1);
    expect(unexpected).toEqual([]); expect(failures).toEqual([]);
  } finally {
    release(new Response(JSON.stringify({ id, claim, state: 'sending' })));
    cleanup(); client.clear();
  }
});

function heldPanel(two = false) {
  useAuthStore.setState({ status: 'logged-in', token: 'inert-lifetime-held', username: 'synthetic' });
  useModeStore.setState({ mode: 'practice' });
  const second = '88888888-8888-4888-8888-888888888888';
  let data = snapshot();
  if (two) data.operational_events.incidents[0]!.deliveries.push({ ...delivery, id: second });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['system', 'diagnostics'], data);
  class Notification { static permission = 'denied'; }
  vi.stubGlobal('Notification', Notification);
  const calls: string[] = []; const failures: unknown[] = [];
  let release!: (response: Response) => void;
  const held = new Promise<Response>(resolve => { release = resolve; });
  let claimSignal: AbortSignal | null | undefined;
  const added = vi.spyOn(window, 'addEventListener'); const removed = vi.spyOn(window, 'removeEventListener');
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    const key = `${init.method} ${url}`; calls.push(key);
    try {
      if (key === `POST /ft-api/api/v1/system/incidents/deliveries/${id}/claim`) { claimSignal = init.signal; return await held; }
      if (key === `POST /ft-api/api/v1/system/incidents/deliveries/${second}/claim`) return new Response(JSON.stringify({ id: second, claim, state: 'sending' }));
      if ([id, second].some(value => key === `POST /ft-api/api/v1/system/incidents/deliveries/${value}/receipt`)) {
        expect(init.body).toBe(JSON.stringify({ claim, state: 'failed' }));
        const actual = url.includes(second) ? second : id;
        return new Response(JSON.stringify({ ...delivery, id: actual, state: 'failed', attempts: 1 }));
      }
      if (key === 'GET /ft-api/api/v1/system/diagnostics') return new Response(JSON.stringify({ status: 'success', data }));
      throw new Error(`Unexpected request: ${key}`);
    } catch (error) { failures.push(error); throw error; }
  }));
  const tree = (mode: 'visible' | 'hidden') => <QueryClientProvider client={client}><Activity mode={mode}><SystemDiagnostics /></Activity></QueryClientProvider>;
  const mounted = render(tree('visible'));
  return {
    client, calls, failures, second,
    signal: () => claimSignal,
    hide: () => mounted.rerender(tree('hidden')),
    show: () => mounted.rerender(tree('visible')),
    replace: (value: ReturnType<typeof snapshot>) => { data = value; },
    finish: async () => { await act(async () => { release(new Response(JSON.stringify({ id, claim, state: 'sending' }))); }); },
    close: async () => {
      useAuthStore.getState().setLoggedOut();
      await act(async () => { release(new Response(JSON.stringify({ id, claim, state: 'sending' }))); });
      cleanup(); client.clear();
      expect(failures).toEqual([]);
      expect(added.mock.calls.filter(([name]) => name === 'pagehide').map(([, listener]) => listener))
        .toEqual(removed.mock.calls.filter(([name]) => name === 'pagehide').map(([, listener]) => listener));
    },
  };
}

it('keeps a held claim across equivalent and fresh real diagnostics responses', async () => {
  const h = heldPanel();
  try {
    expect(h.signal()?.aborted).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh diagnostics' }));
    await waitFor(() => expect(h.client.getQueryState(['system', 'diagnostics'])?.fetchStatus).toBe('idle'));
    expect(h.signal()?.aborted).toBe(false);
    const fresh = snapshot(); fresh.observed_at = '2026-10-12T00:00:01Z';
    h.replace(fresh);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh diagnostics' }));
    await screen.findByText('2026-10-12T00:00:01Z');
    expect(h.signal()?.aborted).toBe(false);
    await h.finish();
    await waitFor(() => expect(h.calls.filter(key => key.endsWith('/receipt'))).toHaveLength(1));
    expect(h.calls.filter(key => key.endsWith('/claim'))).toHaveLength(1);
  } finally { await h.close(); }
});

it('drains only the admitted finite queue while Activity is hidden without reads or discovery', async () => {
  const h = heldPanel(true);
  try {
    h.hide();
    const added = snapshot(); added.operational_events.incidents[0]!.deliveries = [{ ...delivery, id: '99999999-9999-4999-8999-999999999999' }];
    await act(async () => { h.client.setQueryData(['system', 'diagnostics'], added); });
    expect(h.signal()?.aborted).toBe(false);
    await h.finish();
    expect(h.calls.filter(key => key.endsWith('/claim'))).toEqual([
      `POST /ft-api/api/v1/system/incidents/deliveries/${id}/claim`,
      `POST /ft-api/api/v1/system/incidents/deliveries/${h.second}/claim`,
    ]);
    expect(h.calls.filter(key => key.endsWith('/receipt'))).toHaveLength(2);
    expect(h.calls.filter(key => key.startsWith('GET'))).toEqual([]);
    await act(async () => { h.client.setQueryData(['system', 'diagnostics'], snapshot()); });
    h.show();
    await waitFor(() => expect(h.calls.filter(key => key.startsWith('GET'))).toHaveLength(1));
    expect(h.calls.filter(key => key.endsWith('/claim'))).toHaveLength(2);
  } finally { await h.close(); }
});

const retirements = [
  { name: 'Lock', retire: (_client: QueryClient) => useAuthStore.getState().setPinRequired() },
  { name: 'account A-B-A', retire: (_client: QueryClient) => { const id = useBrokerStore.getState().activeAccountId; useBrokerStore.setState({ activeAccountId: 'inert-other' }); useBrokerStore.setState({ activeAccountId: id }); } },
  { name: 'mode A-B-A', retire: (_client: QueryClient) => { useModeStore.setState({ mode: 'explore' }); useModeStore.setState({ mode: 'practice' }); } },
  { name: 'connection authority', retire: (_client: QueryClient) => useConnectionStore.setState({ apiKey: 'inert-replacement' }) },
  { name: 'invalidated freshness', retire: (client: QueryClient) => { void client.invalidateQueries({ queryKey: ['system', 'diagnostics'], refetchType: 'none' }); } },
  { name: 'offline', retire: (_client: QueryClient) => onlineManager.setOnline(false) },
  { name: 'query owner disposal', retire: (client: QueryClient) => client.clear() },
  { name: 'application pagehide', retire: (_client: QueryClient) => window.dispatchEvent(new Event('pagehide')) },
];
it.each(retirements)('synchronously retires hidden work on $name without late receipts or queue revival', async ({ retire }) => {
  const h = heldPanel(true);
  try {
    h.hide();
    expect(h.signal()?.aborted).toBe(false);
    act(() => { retire(h.client); expect(h.signal()?.aborted).toBe(true); });
    await h.finish();
    expect(h.calls).toEqual([`POST /ft-api/api/v1/system/incidents/deliveries/${id}/claim`]);
    h.show();
    expect(h.calls.filter(key => key.startsWith('POST'))).toHaveLength(1);
  } finally { await h.close(); }
});

it('keeps the original ten-second claim deadline across fresh renders and hide', async () => {
  vi.useFakeTimers();
  const deadlines: number[] = [];
  vi.spyOn(AbortSignal, 'timeout').mockImplementation(ms => {
    deadlines.push(ms);
    const controller = new AbortController();
    setTimeout(() => controller.abort(new DOMException('Timed out', 'TimeoutError')), ms);
    return controller.signal;
  });
  const h = heldPanel();
  try {
    await act(async () => { await vi.advanceTimersByTimeAsync(9_999); });
    expect(h.signal()?.aborted).toBe(false);
    const fresh = snapshot(); fresh.observed_at = '2026-10-12T00:00:02Z';
    await act(async () => { h.client.setQueryData(['system', 'diagnostics'], fresh); });
    h.hide();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(deadlines).toEqual([10_000]);
    expect(h.signal()?.aborted).toBe(true);
    expect(h.signal()?.reason.name).toBe('TimeoutError');
    await h.finish();
    expect(h.calls).toEqual([`POST /ft-api/api/v1/system/incidents/deliveries/${id}/claim`]);
  } finally { await h.close(); }
});

it('retires an aged hidden census at its original freshness deadline', async () => {
  // Native AbortSignal.timeout remains real; only the query/batch clock moves.
  vi.useFakeTimers();
  const h = heldPanel();
  try {
    h.hide();
    await act(async () => { await vi.advanceTimersByTimeAsync(24_999); });
    expect(h.signal()?.aborted).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(h.signal()?.aborted).toBe(true);
    await h.finish();
    expect(h.calls).toEqual([`POST /ft-api/api/v1/system/incidents/deliveries/${id}/claim`]);
  } finally { await h.close(); }
});

it('retires in-flight delivery when a fresh hidden diagnostics response is malformed', async () => {
  const h = heldPanel();
  try {
    h.hide();
    await act(async () => { h.client.setQueryData(['system', 'diagnostics'], { ...snapshot(), operational_events: { status: 'unavailable' } }); });
    expect(h.signal()?.aborted).toBe(true);
    await h.finish();
    expect(h.calls).toEqual([`POST /ft-api/api/v1/system/incidents/deliveries/${id}/claim`]);
  } finally { await h.close(); }
});
