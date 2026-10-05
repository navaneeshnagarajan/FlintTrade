/** Initialise optional error reporting without delaying application startup. */
export async function initialiseGlitchtip(
  dsn: string | undefined,
  environment: "development" | "production",
): Promise<void> {
  if (!dsn) return;
  try {
    const Sentry = await import("@sentry/react");
    const deniedFields = ["forwarded", "-ip", "remote-", "via", "-user"];
    Sentry.init({
      dsn,
      integrations: [Sentry.browserTracingIntegration()],
      tracesSampleRate: 0.1,
      environment,
      // Sentry 11 broadens collection and streams spans by default. Keep the
      // v10 privacy baseline and transaction envelopes used with GlitchTip.
      // https://github.com/getsentry/sentry-javascript/blob/11.0.0/MIGRATION.md
      traceLifecycle: "static",
      dataCollection: {
        userInfo: false,
        cookies: false,
        httpHeaders: {
          request: { deny: deniedFields },
          response: { deny: deniedFields },
        },
        httpBodies: [],
        urlQueryParams: { deny: deniedFields },
        genAI: { inputs: false, outputs: false },
        databaseQueryData: false,
        queues: false,
        graphQL: { document: false, variables: false },
      },
    });
  } catch {
    // Error reporting must never interrupt the application.
  }
}
