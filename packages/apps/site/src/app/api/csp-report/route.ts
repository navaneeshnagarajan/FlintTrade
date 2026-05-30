import { NextResponse } from "next/server";

import { logger } from "@/lib/logger";

const MAX_REPORT_BYTES = 4 * 1024; // 4 KB upper bound

interface CspReport {
  "csp-report"?: {
    "blocked-uri"?: string;
    "violated-directive"?: string;
    "document-uri"?: string;
    "script-sample"?: string; // attacker-controlled — never log
    "source-file"?: string;
    "line-number"?: number;
    "column-number"?: number;
  };
}

/** Reduce a URI to {scheme}://{host} only — strip path, query, fragment. */
function originOnly(uri: string | undefined): string {
  if (!uri) return "";
  try {
    const u = new URL(uri);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "(invalid)";
  }
}

/** Reduce a URI to its path component only, dropping query + fragment. */
function pathOnly(uri: string | undefined): string {
  if (!uri) return "";
  try {
    const u = new URL(uri);
    return u.pathname;
  } catch {
    return "(invalid)";
  }
}

export async function POST(req: Request) {
  // 1) Authenticate via Origin — CSP reports come from the same-origin browser. Reject
  //    cross-origin posts to prevent external pollution of the violation log (H9).
  const origin = req.headers.get("origin");
  const siteOrigin = process.env.FLINTTRADE_SITE_ORIGIN ?? "http://127.0.0.1:3000";
  if (origin && origin !== siteOrigin) {
    return NextResponse.json({ ok: false, reason: "origin-mismatch" }, { status: 403 });
  }

  // 2) Reject oversized payloads BEFORE parse to bound memory + log spam.
  const contentLength = Number(req.headers.get("content-length") ?? "0");
  if (contentLength > MAX_REPORT_BYTES) {
    return NextResponse.json({ ok: false, reason: "too-large" }, { status: 413 });
  }

  // 3) Parse + validate shape. Reject silently on failure.
  let body: CspReport | null = null;
  try {
    const text = await req.text();
    if (text.length > MAX_REPORT_BYTES) {
      return NextResponse.json({ ok: false, reason: "too-large" }, { status: 413 });
    }
    body = JSON.parse(text);
  } catch {
    return NextResponse.json({ ok: false, reason: "invalid-json" }, { status: 400 });
  }

  if (!body || typeof body !== "object" || !("csp-report" in body)) {
    return NextResponse.json({ ok: false, reason: "invalid-shape" }, { status: 400 });
  }

  const report = body["csp-report"] ?? {};

  // 4) Allowlist + sanitise. STRIP script-sample (attacker-controlled). Reduce URIs to
  //    origin/path only so query strings (potential PII / session tokens) don't leak.
  const safe = {
    blockedOrigin: originOnly(report["blocked-uri"]),
    violatedDirective: String(report["violated-directive"] ?? "").slice(0, 200),
    documentPath: pathOnly(report["document-uri"]),
    sourceFileOrigin: originOnly(report["source-file"]),
    lineNumber: typeof report["line-number"] === "number" ? report["line-number"] : null,
    columnNumber:
      typeof report["column-number"] === "number" ? report["column-number"] : null,
    // intentionally omitted: script-sample, full document-uri, full blocked-uri,
    // full source-file (all may contain sensitive paths or attacker payloads).
  };

  // 5) Structured logger (not console.warn) so violations reach the operator's sink.
  logger.warn("csp.violation", safe);

  return NextResponse.json({ ok: true });
}
