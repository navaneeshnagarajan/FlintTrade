// Minimal structured server-side logger for the site app.
//
// Emits a single-line JSON record so violations land in the operator's log sink
// (stdout → GlitchTip/Vercel logs, per X9) rather than as free-form console text. Used by
// the hardened /api/csp-report endpoint (§9.4.4) which must NOT use bare console.warn.

type Fields = Record<string, unknown>;

function emit(level: "info" | "warn" | "error", event: string, fields?: Fields): void {
  const record = { level, event, ...(fields ?? {}) };
  // eslint-disable-next-line no-console -- structured single-line JSON to the server log sink
  console[level === "error" ? "error" : level === "warn" ? "warn" : "log"](
    JSON.stringify(record),
  );
}

export const logger = {
  info: (event: string, fields?: Fields) => emit("info", event, fields),
  warn: (event: string, fields?: Fields) => emit("warn", event, fields),
  error: (event: string, fields?: Fields) => emit("error", event, fields),
};
