import { useAuthStore } from "@/stores/authStore";
import { ExecutionSessionsPanel } from "./ExecutionSessionsPanel";

/** Existing Testing mount, now using immutable backend run IDs. */
export function ForwardTestSection() {
  const presentationOwner = useAuthStore(state => JSON.stringify([state.status, state.username, state.sessionGeneration]));
  // Retire drafts, pending labels and confirmations on operator replacement,
  // not on Terminal account/mode changes. Backend runs are never stopped here.
  return <ExecutionSessionsPanel key={presentationOwner} />;
}
