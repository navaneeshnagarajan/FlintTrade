import { isPublicDemoBuild } from "./demoSession";
// Fallback pins this source snapshot's commit time, not the visitor's wall clock.
// The website build supplies its own commit timestamp through the build script.
export const PREVIEW_AS_OF = import.meta.env.VITE_PUBLIC_PREVIEW_AS_OF || "2026-10-07T13:46:34-07:00";
export function previewSnapshotTime(value: string): number {
  if (!/^\d{4}-\d{2}-\d{2}T/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error("Invalid preview snapshot timestamp");
  return Date.parse(value);
}
export function createPreviewFetch(transport: typeof fetch, origin: string): typeof fetch {
  return (input, init) => {
    const request = typeof input === "string" || input instanceof URL ? null : input;
    const url = new URL(request ? request.url : String(input), origin);
    const method = (init?.method ?? request?.method ?? "GET").toUpperCase();
    const asset = url.pathname.startsWith("/demo-app/assets/") || url.pathname.startsWith("/demo-app/docs/");
    if (url.origin !== origin || method !== "GET" || !asset) return Promise.reject(new Error("Public Sandbox is a build-frozen preview; backend and provider requests are unavailable."));
    return transport(input, init);
  };
}
/** Runs before other app modules, only in the separate public build. There is
 * no synthetic account or bearer token. Timers still use native performance
 * time; date-labelled simulated evidence uses this build's fixed wall clock. */
export function initialisePublicPreview(): void {
  if (!isPublicDemoBuild()) return;
  const epoch = previewSnapshotTime(PREVIEW_AS_OF);
  const NativeDate = globalThis.Date;
  globalThis.Date = new Proxy(NativeDate, {
    construct(target, args, newTarget) { return Reflect.construct(target, args.length ? args : [epoch], newTarget); },
    apply() { return new NativeDate(epoch).toString(); },
    get(target, key) { return key === "now" ? () => epoch : Reflect.get(target, key); },
  });
  globalThis.fetch = createPreviewFetch(globalThis.fetch.bind(globalThis), location.origin);
  // Fail before transport, including direct SDKs that do not use fetch.
  class DisabledTransport { constructor() { throw new Error("Network transport is unavailable in the frozen preview"); } }
  globalThis.WebSocket = DisabledTransport as unknown as typeof WebSocket;
  globalThis.EventSource = DisabledTransport as unknown as typeof EventSource;
  globalThis.XMLHttpRequest = DisabledTransport as unknown as typeof XMLHttpRequest;
  navigator.sendBeacon = () => false;
  localStorage.setItem("flinttrade:mode", JSON.stringify({ state: { mode: "explore" }, version: 2 }));
}
