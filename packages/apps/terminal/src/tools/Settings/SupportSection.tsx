import { useEffect, useMemo, useState } from "react";
import {
  Bug,
  Check,
  Copy,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { openExternalUrl } from "@/lib/desktopShell";
import { getSupportDiagnostics, type SupportDiagnostics } from "@/services/ftApi.support";
import { useModeStore } from "@/stores/modeStore";
import { FieldLabel, SectionTitle, TextInput, Toggle } from "./shared";
import type { SectionId } from "./settingsConfig";

export const GITHUB_NEW_ISSUE_URL = "https://github.com/navaneeshnagarajan/FlintTrade/issues/new";
export const SECURITY_ADVISORY_URL = "https://github.com/navaneeshnagarajan/FlintTrade/security/advisories/new";
export const ISSUE_URL_BUDGET = 7_000;

const SAFE_UI_ROUTES = new Set([
  "admin", "ai", "automate", "ditto", "explore", "home", "invest", "lab", "learn",
  "settings", "setup", "setup-account", "terminal", "trade", "welcome",
]);
const SAFE_SETTINGS_SECTIONS: ReadonlySet<SectionId> = new Set([
  "profile", "general", "appearance", "ticker", "api", "brokers", "trading", "risk",
  "leverage", "practice", "keyboard", "llm", "telegram", "whatsapp", "dataPaths",
  "security", "monitoring", "skill", "presets", "updates", "support", "about",
]);

export function safeClientRoute(pathname: string, hash: string): string {
  const segments = pathname.split("/").filter(Boolean);
  let route = "/";
  if (segments[0] === "admin" && segments[1] === "observability") {
    route = "/admin/observability";
  } else if (segments[0] && SAFE_UI_ROUTES.has(segments[0])) {
    route = `/${segments[0]}`;
  } else if (segments.length > 0) {
    route = "/unknown";
  }

  const settingsSection = hash.startsWith("#") ? hash.slice(1) : "";
  if (route === "/settings" && SAFE_SETTINGS_SECTIONS.has(settingsSection as SectionId)) {
    return `${route}#${settingsSection}`;
  }
  return route;
}

interface IssueBodyInput {
  affectedArea: string;
  description: string;
  steps: string;
  expected: string;
  includeDiagnostics: boolean;
  diagnostics: SupportDiagnostics | null;
  mode: string;
  userAgent: string;
  viewport: string;
}

function contentOrPlaceholder(value: string, maxLength: number): string {
  return value.trim().slice(0, maxLength) || "Not provided.";
}

function safeSingleLine(value: string, maxLength: number): string {
  return value.replace(/[\r\n\t]+/g, " ").trim().slice(0, maxLength) || "Unavailable";
}

function errorSummary(diagnostics: SupportDiagnostics | null): string {
  if (!diagnostics?.errors.available) return "Error log unavailable.";
  if (diagnostics.errors.groups.length === 0) return "No recent error groups.";
  return diagnostics.errors.groups.slice(0, 10).map((group) => {
    const status = group.status_code === null ? "unknown status" : String(group.status_code);
    return `- ${group.error_class} on ${group.method} ${group.route} (${status}) x${group.occurrences}`;
  }).join("\n");
}

export function buildIssueBody(input: IssueBodyInput): string {
  const runtime = input.diagnostics?.runtime;
  const version = input.diagnostics?.app.version ?? "Unavailable";
  const body = [
    "## Affected area",
    "",
    contentOrPlaceholder(input.affectedArea, 120),
    "",
    "## Describe the bug",
    "",
    contentOrPlaceholder(input.description, 2_000),
    "",
    "## To reproduce",
    "",
    contentOrPlaceholder(input.steps, 1_500),
    "",
    "## Expected behaviour",
    "",
    contentOrPlaceholder(input.expected, 1_000),
    "",
  ];
  if (input.includeDiagnostics) {
    body.push(
      "## Environment",
      "",
      `- FlintTrade: ${safeSingleLine(version, 80)}`,
      `- OS: ${runtime ? `${safeSingleLine(runtime.os, 40)} ${safeSingleLine(runtime.os_release, 80)} (${safeSingleLine(runtime.architecture, 40)})` : "Unavailable"}`,
      `- Python: ${safeSingleLine(runtime?.python ?? "", 40)}`,
      `- Browser/WebView: ${safeSingleLine(input.userAgent, 300)}`,
      `- Viewport: ${safeSingleLine(input.viewport, 40)}`,
      `- Mode: ${safeSingleLine(input.mode, 40)}`,
      "",
      "## Recent error groups",
      "",
      errorSummary(input.diagnostics),
      "",
    );
  } else {
    body.push("## Diagnostics", "", "Not included in this GitHub draft.", "");
  }
  body.push(
    "## Additional context",
    "",
    "A locally generated diagnostics file can be attached separately after review.",
  );
  return body.join("\n");
}

function issueUrl(summary: string, body: string): string {
  const params = new URLSearchParams({
    template: "bug_report.md",
    title: `[BUG] ${summary.trim().slice(0, 160)}`,
    body,
  });
  return `${GITHUB_NEW_ISSUE_URL}?${params.toString()}`;
}

export function buildIssueLaunch(summary: string, body: string): { copyBody: boolean; url: string } {
  const fullUrl = issueUrl(summary, body);
  if (fullUrl.length <= ISSUE_URL_BUDGET) return { copyBody: false, url: fullUrl };
  const params = new URLSearchParams({
    template: "bug_report.md",
    title: `[BUG] ${summary.trim().slice(0, 160)}`,
  });
  return { copyBody: true, url: `${GITHUB_NEW_ISSUE_URL}?${params.toString()}` };
}

function diagnosticsStatus(diagnostics: SupportDiagnostics | null): string {
  if (!diagnostics) return "Diagnostics unavailable";
  if (!diagnostics.errors.available) return "Runtime details ready; error log unavailable";
  const count = diagnostics.errors.total;
  return `${count} recorded error${count === 1 ? "" : "s"}; ${diagnostics.errors.groups.length} grouped`;
}

export function SupportSection() {
  const mode = useModeStore((state) => state.mode);
  const [summary, setSummary] = useState("");
  const [affectedArea, setAffectedArea] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState("");
  const [expected, setExpected] = useState("");
  const [includeDiagnostics, setIncludeDiagnostics] = useState(false);
  const [diagnostics, setDiagnostics] = useState<SupportDiagnostics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function loadDiagnostics() {
    setLoading(true);
    setError(null);
    try {
      setDiagnostics(await getSupportDiagnostics());
    } catch (caught) {
      setDiagnostics(null);
      setError(caught instanceof Error ? caught.message : "Diagnostics unavailable");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDiagnostics();
  }, []);

  const clientRoute = safeClientRoute(window.location.pathname, window.location.hash);
  const viewport = `${window.innerWidth}x${window.innerHeight}`;

  const reportBody = useMemo(() => buildIssueBody({
    affectedArea,
    description,
    steps,
    expected,
    includeDiagnostics,
    diagnostics,
    mode,
    userAgent: window.navigator.userAgent,
    viewport,
  }), [affectedArea, description, diagnostics, expected, includeDiagnostics, mode, steps, viewport]);
  const issueLaunch = useMemo(
    () => summary.trim() ? buildIssueLaunch(summary, reportBody) : null,
    [reportBody, summary],
  );

  function downloadDiagnostics() {
    if (!diagnostics) return;
    const bundle = {
      ...diagnostics,
      client: {
        route: clientRoute,
        mode,
        user_agent: window.navigator.userAgent,
        viewport,
      },
    };
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `flinttrade-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function copyReport() {
    try {
      await window.navigator.clipboard.writeText(reportBody);
      setError(null);
      setNotice("Report draft copied locally");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2_000);
    } catch {
      setError("Clipboard access was refused");
    }
  }

  async function openIssue() {
    if (!summary.trim()) return;
    setError(null);
    try {
      const launch = issueLaunch ?? buildIssueLaunch(summary, reportBody);
      if (launch.copyBody) {
        await window.navigator.clipboard.writeText(reportBody);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2_000);
        setNotice("The draft exceeded the safe URL limit, so it was copied for pasting into GitHub");
      } else {
        setNotice("Opening GitHub sends the displayed draft in the URL");
      }
      await openExternalUrl(launch.url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not open GitHub");
    }
  }

  async function openSecurityAdvisory() {
    setError(null);
    try {
      await openExternalUrl(SECURITY_ADVISORY_URL);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not open GitHub Security Advisories");
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle>Report Bug</SectionTitle>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="space-y-4 min-w-0">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <FieldLabel>Bug summary</FieldLabel>
              <TextInput
                value={summary}
                onChange={(value) => setSummary(value.slice(0, 160))}
                placeholder="Short, specific title"
                aria-label="Bug summary"
              />
            </div>
            <div>
              <FieldLabel>Affected area</FieldLabel>
              <TextInput
                value={affectedArea}
                onChange={(value) => setAffectedArea(value.slice(0, 120))}
                placeholder="Chart, order pad, setup..."
                aria-label="Affected area"
              />
            </div>
          </div>

          <div>
            <FieldLabel>What happened</FieldLabel>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              aria-label="What happened"
              maxLength={2_000}
              rows={5}
              className="w-full resize-y rounded border border-border-default bg-surface-base px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:border-accent/60 focus:outline-none focus:ring-1 focus:ring-accent/20"
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <FieldLabel>Steps to reproduce</FieldLabel>
              <textarea
                value={steps}
                onChange={(event) => setSteps(event.target.value)}
                aria-label="Steps to reproduce"
                maxLength={1_500}
                rows={4}
                className="w-full resize-y rounded border border-border-default bg-surface-base px-3 py-2 text-xs text-text-primary focus:border-accent/60 focus:outline-none focus:ring-1 focus:ring-accent/20"
              />
            </div>
            <div>
              <FieldLabel>Expected behaviour</FieldLabel>
              <textarea
                value={expected}
                onChange={(event) => setExpected(event.target.value)}
                aria-label="Expected behaviour"
                maxLength={1_000}
                rows={4}
                className="w-full resize-y rounded border border-border-default bg-surface-base px-3 py-2 text-xs text-text-primary focus:border-accent/60 focus:outline-none focus:ring-1 focus:ring-accent/20"
              />
            </div>
          </div>
        </div>

        <aside className="space-y-3 border-l-0 border-border-default lg:border-l lg:pl-4" aria-label="Diagnostics">
          <div className="flex items-center gap-2">
            <ShieldCheck size={15} className="text-profit" />
            <h3 className="text-xs font-semibold text-text-primary">Diagnostics</h3>
          </div>

          <div className="space-y-1 text-xs text-text-secondary">
            <div className="font-mono text-text-primary">
              {diagnostics?.app.version ?? (loading ? "Loading..." : "Unavailable")}
            </div>
            <div>{loading ? "Reading local error summary..." : diagnosticsStatus(diagnostics)}</div>
            {diagnostics && (
              <div>{diagnostics.runtime.os} {diagnostics.runtime.os_release} · {diagnostics.runtime.architecture}</div>
            )}
          </div>

          <p className="text-xs leading-relaxed text-text-muted">
            Export excludes request bodies, messages, tracebacks, user and account identifiers, entry ids, and URL queries.
          </p>

          <Toggle
            checked={includeDiagnostics}
            onChange={setIncludeDiagnostics}
            label="Include diagnostic summary in GitHub draft"
          />
          <pre
            aria-label="GitHub draft preview"
            className="max-h-40 overflow-auto whitespace-pre-wrap break-words border-l-2 border-border-default pl-2 font-mono text-xs leading-relaxed text-text-muted"
          >
            {reportBody}
          </pre>

          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={() => void loadDiagnostics()}
              disabled={loading}
              className="flex h-8 items-center justify-center gap-2 rounded border border-border-default bg-surface-base px-3 text-xs text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:opacity-50"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Refresh diagnostics
            </button>
            <button
              type="button"
              onClick={downloadDiagnostics}
              disabled={!diagnostics}
              className="flex h-8 items-center justify-center gap-2 rounded border border-border-default bg-surface-base px-3 text-xs text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:opacity-50"
            >
              <Download size={13} />
              Download diagnostics
            </button>
            <button
              type="button"
              onClick={() => void copyReport()}
              className="flex h-8 items-center justify-center gap-2 rounded border border-border-default bg-surface-base px-3 text-xs text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            >
              {copied ? <Check size={13} className="text-profit" /> : <Copy size={13} />}
              {copied ? "Copied" : "Copy report"}
            </button>
          </div>
        </aside>
      </div>

      <div className="space-y-3 border-t border-border-default pt-4">
        <p className="flex items-start gap-1.5 text-xs leading-relaxed text-text-muted">
          <Bug size={12} className="mt-0.5 shrink-0" />
          {issueLaunch?.copyBody
            ? "This draft is too large for a URL. It will be copied locally; GitHub receives only the bug title."
            : "Opening GitHub sends the bug title and exact draft shown above in the URL. Downloaded diagnostics remain local until you attach them."}
        </p>
        {(notice || error) && (
          <div
            role={error ? "alert" : "status"}
            className={error ? "text-xs text-loss" : "text-xs text-text-secondary"}
          >
            {error ?? notice}
          </div>
        )}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => void openSecurityAdvisory()}
            className="mr-auto flex h-8 items-center gap-2 rounded border border-border-default bg-surface-base px-3 text-xs text-text-secondary hover:bg-surface-hover hover:text-text-primary"
          >
            <ShieldAlert size={13} />
            Report security issue privately
          </button>
          <button
            type="button"
            onClick={() => void openIssue()}
            disabled={!summary.trim()}
            className="flex h-8 items-center gap-2 rounded bg-accent px-3 text-xs font-medium text-black hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ExternalLink size={13} />
            Open GitHub issue
          </button>
        </div>
      </div>
    </div>
  );
}
