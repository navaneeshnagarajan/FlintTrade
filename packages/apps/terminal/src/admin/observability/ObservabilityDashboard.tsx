/**
 * ObservabilityDashboard — single aggregator screen for the /admin/observability route.
 *
 * This screen does NOT build new widgets. It COMPOSES the existing, self-contained
 * observability surfaces into one responsive grid so an operator can survey the
 * whole platform at a glance:
 *
 *   - System Metrics       → SystemMetricsPanel   (CPU / memory / disk / network / uptime)
 *   - Traffic & Latency    → MonitoringSection    (connection roll-up, requests/sec, error rate,
 *                                                   per-broker latency — the System Health widget
 *                                                   retired into this section, ruling D6)
 *   - Security & Rate Limit→ SecuritySection      (threat counters, banned-IP management)
 *   - Audit Trail          → AuditTrailWidget     (append-only activity log)
 *
 * Each child component sources its own data through @/services/ftApi (the same client
 * the widgets already expect), so this aggregator passes no data props — it only arranges.
 *
 * British English is used throughout visible copy ("Visualisation", "Behaviour",
 * "Authorisation", "Optimisation").
 *
 * NOTE on coverage: the original OBS-07 brief referenced twelve discrete observability
 * widgets (health, traffic, error, activity, latency, api-analyzer, system-metrics,
 * security-tracker, log-stream, rate-limiter, audit-log, mcp-audit). In this codebase
 * those domains are not twelve separate widget files — they are folded into the five
 * self-contained components above (plus the AdminRoute Logs panel for log-stream, and
 * the api-analyzer / mcp-audit domains have no standalone frontend component yet).
 * Composing the real, compilable components keeps this screen honest and buildable.
 */

import type { JSX } from "react";
import { Activity } from "lucide-react";

// Existing observability surfaces — imported directly from their real paths
// (no barrel imports, per the repo's bundle conventions).
import AuditTrailWidget from "@/widgets/utility/AuditTrail/AuditTrailWidget";
import { SystemMetricsPanel } from "@/routes/admin/SystemMetricsPanel";
import { MonitoringSection } from "@/tools/Settings/MonitoringSection";
import { SecuritySection } from "@/tools/Settings/SecuritySection";

// ---------------------------------------------------------------------------
// Section frame — gives each composed surface a consistent heading + card shell
// ---------------------------------------------------------------------------

interface SectionProps {
  /** Visible British-English heading for the section. */
  title: string;
  /** Short description of what the operator is looking at. */
  description: string;
  /** The composed observability surface. */
  children: React.ReactNode;
  /** When true, the section spans both columns on large viewports. */
  wide?: boolean;
}

function ObservabilitySection({ title, description, children, wide }: SectionProps): JSX.Element {
  return (
    <section
      aria-label={title}
      className={`rounded-glass-inner border border-glass-l2 bg-glass-l1 overflow-hidden ${
        wide ? "lg:col-span-2" : ""
      }`}
    >
      <header className="border-b border-glass-l1 px-4 py-3">
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
        <p className="mt-0.5 text-xs text-text-muted">{description}</p>
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main aggregator
// ---------------------------------------------------------------------------

export function ObservabilityDashboard(): JSX.Element {
  return (
    <div className="min-h-screen bg-background text-text-primary">
      {/* Page header */}
      <header className="sticky top-0 z-10 bg-glass-chrome backdrop-blur-md border-b border-glass-chrome">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Activity className="w-4 h-4 text-accent" aria-hidden="true" />
          <div>
            <h1 className="text-lg font-semibold">Observability</h1>
            <p className="text-xs text-text-muted">
              Live visualisation of platform health, behaviour, and authorisation
            </p>
          </div>
        </div>
      </header>

      {/* Composed grid */}
      <main aria-label="Observability dashboard" className="max-w-7xl mx-auto px-4 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Server resource metrics — CPU / memory / disk / network / uptime */}
          <ObservabilitySection
            title="System Metrics"
            description="CPU, memory, disk, and network utilisation with uptime"
          >
            <SystemMetricsPanel />
          </ObservabilitySection>

          {/* Traffic + per-broker latency monitoring */}
          <ObservabilitySection
            title="Traffic & Latency"
            description="Requests per second, error rate, and per-broker latency behaviour"
          >
            <MonitoringSection />
          </ObservabilitySection>

          {/* Security tracker + rate-limit / banned-IP authorisation controls */}
          <ObservabilitySection
            title="Security & Rate Limiting"
            description="Threat counters, rate-limit offenders, and banned-IP authorisation"
          >
            <SecuritySection />
          </ObservabilitySection>

          {/* Append-only audit / activity log — spans full width */}
          <ObservabilitySection
            title="Audit Trail"
            description="Append-only log of orders, sessions, and account events"
            wide
          >
            <div className="h-[28rem] overflow-hidden rounded-glass-inner border border-glass-l1">
              <AuditTrailWidget />
            </div>
          </ObservabilitySection>
        </div>
      </main>
    </div>
  );
}

export default ObservabilityDashboard;
