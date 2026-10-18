import { Activity } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { IncidentTimelinePanel } from '../IncidentTimelinePanel';
import { IncidentChannelSettings } from '../IncidentChannelSettings';
import { useAuthStore } from '@/stores/authStore';
import { useModeStore } from '@/stores/modeStore';

const id = '66666666-6666-4666-8666-666666666666';
const receipt = { id: '44444444-4444-4444-8444-444444444444', channel: 'telegram', state: 'failed', attempts: 1, updated_at: '2026-10-12T00:00:00Z' };
const row = { id, correlation_id: id, observed_at: receipt.updated_at, source: 'core_http', scope: 'core_process', severity: 'critical', code: 'http_failure', freshness: 'observed', measurement: { state: 'measured', duration_ms: 12, status_code: 503 }, root_cause: { state: 'unknown', code: null }, deliveries: [receipt] };
const envelope = (incidents: object[]) => ({ status: 'available', durable: true, retention: 'until_manual_deletion', incidents, has_more: false, next_cursor: null });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function login() {
  useAuthStore.setState({ status: 'logged-in', token: 'synthetic-incident-controls' });
  useModeStore.setState({ mode: 'live' });
}

it('uses the shared primitives for all seven incident input and button controls', () => {
  login();
  const { container } = render(<IncidentTimelinePanel value={envelope([row])} current refresh={() => undefined} />);
  const controls = [...container.querySelectorAll('input,button')];
  expect(controls).toHaveLength(7);
  expect(controls.map(control => control.getAttribute('data-slot'))).toEqual(['button', 'input', 'input', 'button', 'button', 'button', 'button']);
});

it.each(['history_job', 'model_task'])('renders retained %s failure provenance without manufacturing critical delivery', source => {
  login();
  const kind = source === 'history_job' ? 'historify_job_manager' : 'service_usage_ledger';
  render(<IncidentTimelinePanel value={envelope([{ ...row, source, severity: 'warning', code: `${source}_failure`, producer: { kind, reference: id }, measurement: { state: 'unmeasured', duration_ms: null, status_code: null }, deliveries: [] }])} current refresh={() => undefined} />);
  expect(screen.getByRole('article', { name: 'warning incident' })).toHaveTextContent(`Source: ${source}`);
  expect(screen.getByText(`Producer: ${kind}`)).toBeVisible();
  expect(screen.getByText('Root cause: unknown')).toBeVisible();
  expect(screen.queryByRole('button', { name: /Retry|Cancel/ })).not.toBeInTheDocument();
});

it('keeps recipient and confirmation retirement across channel, auth and Activity changes', () => {
  login();
  const calls = vi.fn(); vi.stubGlobal('fetch', calls);
  const view = render(<Activity mode="visible"><IncidentChannelSettings /></Activity>);
  const recipient = screen.getByLabelText<HTMLInputElement>('Configured alert recipient');
  const confirmation = screen.getByLabelText<HTMLInputElement>('Allow this channel to receive critical incident notices');
  fireEvent.change(recipient, { target: { value: 'synthetic-recipient' } }); fireEvent.click(confirmation);
  fireEvent.change(screen.getByLabelText('Alert channel'), { target: { value: 'email' } });
  expect(recipient.value).toBe(''); expect(confirmation.checked).toBe(false);
  fireEvent.change(recipient, { target: { value: 'synthetic-recipient' } }); fireEvent.click(confirmation);
  act(() => useAuthStore.setState({ token: 'synthetic-replacement' }));
  expect(recipient.value).toBe(''); expect(confirmation.checked).toBe(false);
  fireEvent.change(recipient, { target: { value: 'synthetic-recipient' } });
  view.rerender(<Activity mode="hidden"><IncidentChannelSettings /></Activity>);
  expect(recipient.value).toBe('');
  expect(calls).not.toHaveBeenCalled();
});
