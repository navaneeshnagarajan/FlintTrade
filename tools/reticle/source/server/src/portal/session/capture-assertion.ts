import { CaptureScopeSchema } from '@reticlehq/core';
import type { SessionManager } from './session-manager.js';

/** Resolve only the owned lifetime, never the ordinary successor convenience path. */
export function bindCaptureAssertion(sessions: SessionManager, sessionId: unknown, input: unknown) {
  const scope = CaptureScopeSchema.parse(input);
  if (sessionId !== scope.sessionId) throw new Error('capture scope session mismatch');
  const session = sessions.all().find(candidate => candidate.id === scope.sessionId);
  if (session === undefined) throw new Error('capture scope original session departed');
  // Legitimate idle revival on the SAME socket is not a replacement.
  session.markAgentActivity();
  const check = () => {
    if (!sessions.all().includes(session)) throw new Error('capture scope session replaced');
    session.assertCaptureScope(scope);
  };
  check();
  return { session, scope, check };
}
