import type { UserEvent } from "@testing-library/user-event";

/** Press Tab until the target has focus, so a test proves keyboard reach. */
export async function tabTo(user: UserEvent, target: HTMLElement, maxStops = 150): Promise<void> {
  for (let stop = 0; stop < maxStops; stop += 1) {
    await user.tab();
    if (document.activeElement === target) return;
  }
  throw new Error(`Tab did not reach the element within ${maxStops} stops`);
}
