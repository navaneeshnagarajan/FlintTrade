import * as Sentry from "@sentry/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { initialiseGlitchtip } from "../glitchtip";

type TransportFactory = NonNullable<Parameters<typeof Sentry.init>[0]["transport"]>;
type Envelope = Parameters<ReturnType<TransportFactory>["send"]>[0];

vi.mock(import("@sentry/react"), async (importOriginal) => {
  const sdk = await importOriginal();
  return { ...sdk, init: vi.fn(sdk.init) };
});

afterEach(async () => {
  await Sentry.close();
  Sentry.getCurrentScope().setClient(undefined);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("GlitchTip SDK compatibility", () => {
  it("preserves restricted collection and sends errors plus static transactions", async () => {
    const envelopes: Envelope[] = [];
    const { init: initSdk } = await vi.importActual<typeof Sentry>("@sentry/react");
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network forbidden"));
    vi.mocked(Sentry.init).mockImplementation((options) => initSdk({
      ...options,
      // Run the real SDK, replacing only its transport. No synthetic event
      // can leave this test, even if SDK fetch instrumentation changes.
      transport: () => ({
        send: async (envelope) => {
          envelopes.push(envelope);
          return { statusCode: 200 };
        },
        flush: async () => true,
      }),
    }));

    await initialiseGlitchtip("https://synthetic@example.invalid/1", "production");
    const client = Sentry.getClient();
    expect(client).toBeDefined();
    const options = client!.getOptions();
    expect(options.tracesSampleRate).toBe(0.1);
    expect(options.traceLifecycle).toBe("static");
    expect(client!.getDataCollectionOptions()).toMatchObject({
      userInfo: false,
      cookies: false,
      httpBodies: [],
      databaseQueryData: false,
      queues: false,
      genAI: { inputs: false, outputs: false },
      graphQL: { document: false, variables: false },
      httpHeaders: {
        request: { deny: ["forwarded", "-ip", "remote-", "via", "-user"] },
        response: { deny: ["forwarded", "-ip", "remote-", "via", "-user"] },
      },
      urlQueryParams: { deny: ["forwarded", "-ip", "remote-", "via", "-user"] },
    });

    // Deterministically sample this synthetic transaction without changing
    // the application's production sample rate.
    options.tracesSampleRate = 1;
    Sentry.captureException(new Error("synthetic telemetry error"));
    Sentry.withActiveSpan(null, () => {
      Sentry.startSpan({ name: "synthetic transaction", op: "test", forceTransaction: true }, () => undefined);
    });
    expect(await Sentry.flush(2_000)).toBe(true);

    const items: Envelope[1][number][] = [];
    for (const [, envelopeItems] of envelopes) items.push(...envelopeItems);
    const error = items.find(([header]) => header.type === "event");
    const transaction = items.find(([header]) => header.type === "transaction");
    const errorEvent = error?.[1] as Sentry.Event | undefined;
    const transactionEvent = transaction?.[1] as Sentry.Event | undefined;
    expect(errorEvent?.exception).toBeDefined();
    expect(transactionEvent?.transaction).toBe("synthetic transaction");
    expect(items.some(([header]) => header.type === "span")).toBe(false);
    expect(envelopes.length).toBeGreaterThan(0);
    expect(errorEvent?.sdk?.settings?.infer_ip).toBe("never");
    expect(transactionEvent?.sdk?.settings?.infer_ip).toBe("never");
    expect(JSON.stringify(envelopes)).not.toContain("{{auto}}");
    expect(fetch).not.toHaveBeenCalled();
  });
});
