import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import LearningPermissions from '../LearningPermissions';
import { useAuthStore } from '@/stores/authStore';
afterEach(() => vi.unstubAllGlobals());
it('does not mint a learning grant when trusted authority is unavailable', async () => {
  useAuthStore.setState({ status: 'logged-in', token: 'synthetic-permission' });
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ error: 'learning_authority_unavailable' }), { status: 503 }))); vi.stubGlobal('fetch', fetch);
  render(<LearningPermissions />); const user = userEvent.setup();
  expect(screen.getByLabelText('Complete learning proposal JSON')).toHaveValue('');
  await user.type(screen.getByLabelText('Complete learning proposal JSON'), '{{}');
  await user.click(screen.getByRole('button', { name: 'Preview exact permission' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('learning_authority_unavailable');
  expect(screen.getByRole('button', { name: 'Confirm this exact permission' })).toBeDisabled();
  expect(fetch).toHaveBeenCalledTimes(1); expect(fetch.mock.calls[0][0]).toBe('/ft-api/v1/learning/permissions/preview');
});
