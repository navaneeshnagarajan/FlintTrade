import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ProfileSection } from '@/tools/Settings/ProfileSection';
import { logoutSession } from '../sessionLogout';
import { LogoutNotice } from '@/components/LogoutNotice';
import { useAuthStore } from '@/stores/authStore';
beforeEach(() => useAuthStore.setState({ status: 'logged-in', token: 'synthetic-original-session', reauthToken: null, username: 'A', sessionGeneration: 80 }));
afterEach(() => vi.unstubAllGlobals());
it('sends the original token before local retirement and shows server refusal separately', async () => {
  let finish!: (r: Response) => void;
  const fetch = vi.fn().mockImplementation(() => {
    expect(useAuthStore.getState().token).toBe('synthetic-original-session');
    return new Promise<Response>(resolve => { finish = resolve; });
  }); vi.stubGlobal('fetch', fetch); render(<><ProfileSection /><LogoutNotice /></>);
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  expect(useAuthStore.getState().status).toBe('logged-out');
  expect(screen.getByRole('status')).toHaveTextContent('pending');
  expect(fetch).toHaveBeenCalledWith('/ft-api/v1/auth/logout', expect.objectContaining({ method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer synthetic-original-session' } }));
  await act(async () => { finish(new Response(JSON.stringify({ status: 'error', code: 'logout_not_confirmed' }), { status: 503 })); await Promise.resolve(); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Server revocation is not confirmed');
  expect(screen.getByRole('alert')).toHaveTextContent('logout_not_confirmed');
  expect(fetch).toHaveBeenCalledTimes(1);
});
it('cannot retire or relabel a replacement session when the old logout finishes', async () => {
  let finish!: (r: Response) => void;
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>(resolve => { finish = resolve; })));
  const task = logoutSession();
  useAuthStore.setState({ status: 'logged-in', token: 'synthetic-B', username: 'B', sessionGeneration: 90 });
  finish(new Response(JSON.stringify({ status: 'success' })));
  await task;
  expect(useAuthStore.getState()).toMatchObject({ status: 'logged-in', token: 'synthetic-B', username: 'B', sessionGeneration: 90 });
});
it('does not treat invalid or expired 401 as positive revocation evidence', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'error', message: 'Session invalid or expired' }), { status: 401 })));
  const result = await logoutSession();
  expect(result).toEqual({ state: 'unconfirmed', code: 'HTTP 401' });
});
it('uses the original retained PIN reauthentication session when explicitly logged out', async () => {
  useAuthStore.getState().setPinRequired();
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'success' }))); vi.stubGlobal('fetch', fetch);
  await logoutSession();
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic-original-session');
  expect(fetch.mock.calls[0][1].credentials).toBe('omit');
});
it('confirms server retirement only after its successful exact-session response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'success' }))));
  render(<LogoutNotice />); await act(async () => { await logoutSession(); });
  expect(screen.getByRole('status')).toHaveTextContent('Server confirmed retirement');
});
