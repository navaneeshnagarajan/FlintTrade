import { useState } from "react";
import {
  Workflow,
  Clock,
  Activity,
  FileText,
  Settings2,
  ChevronRight,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Section registry
// ---------------------------------------------------------------------------

type SectionId = "flows" | "schedules" | "monitors" | "logs" | "settings";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof Workflow;
  desc: string;
}

const SECTIONS: SectionDef[] = [
  { id: "flows", label: "Flow Builder", icon: Workflow, desc: "Visual 54-node automation builder" },
  { id: "schedules", label: "Schedules", icon: Clock, desc: "Cron jobs & timed executions" },
  { id: "monitors", label: "Monitors", icon: Activity, desc: "Live strategy monitoring" },
  { id: "logs", label: "Execution Logs", icon: FileText, desc: "History of automated actions" },
  { id: "settings", label: "Automation Settings", icon: Settings2, desc: "Kill switches, limits, Telegram alerts" },
];

// ---------------------------------------------------------------------------
// Section content components
// ---------------------------------------------------------------------------

function FlowsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Flow Builder
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Build trading automations visually with a 54-node drag-and-drop flow builder.
          Connect market data triggers, conditions, and order actions without writing code.
          Flows run server-side and persist across sessions.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Node Types</p>
            <p className="text-2xl font-mono font-bold text-text-primary">54</p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Categories</p>
            <p className="text-2xl font-mono font-bold text-text-primary">8</p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <p className="text-xs text-text-muted mb-1">Execution</p>
            <p className="text-2xl font-mono font-bold text-accent">Server-side</p>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-sm text-text-primary mb-2">
          Node Categories
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {[
            "Triggers", "Conditions", "Actions", "Orders",
            "Indicators", "Data", "Alerts", "Utilities",
          ].map((cat) => (
            <div
              key={cat}
              className="bg-surface-base border border-border-default rounded-lg p-3 text-center"
            >
              <p className="text-xs font-semibold text-text-primary">{cat}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function SchedulesSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Cron Scheduler
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Schedule trading actions on a cron-based timeline. Pre-market scans, market-open
          entries, intraday rebalancing, EOD square-off, and post-market analysis can all
          be automated with precise timing.
        </p>
        <div className="bg-surface-base border border-border-default rounded-lg p-4">
          <h4 className="text-sm font-semibold text-text-primary mb-2">Common Schedules</h4>
          <ul className="space-y-1.5 text-sm text-text-secondary">
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Pre-market scan at 9:00 AM IST
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Strategy entry at 9:20 AM (after opening volatility settles)
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Intraday rebalance every 30 minutes
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              EOD square-off at 3:15 PM IST
            </li>
            <li className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-accent shrink-0" />
              Post-market analysis at 4:00 PM IST
            </li>
          </ul>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Schedule management UI will be available in the next release. The Python automation
          package already supports cron-based scheduling.
        </p>
      </Card>
    </div>
  );
}

function MonitorsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Live Strategy Monitors
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Monitor running strategies and automations in real-time. Track execution status,
          P&L per strategy, open positions, and trigger conditions. Get instant alerts
          when strategies deviate from expected behavior.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Tracked Metrics</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Strategy P&L (real-time)</li>
              <li>Execution count & success rate</li>
              <li>Open positions per strategy</li>
              <li>Trigger condition status</li>
            </ul>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Alert Channels</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>In-app notifications</li>
              <li>Telegram bot alerts</li>
              <li>Browser push notifications</li>
              <li>Sound alerts</li>
            </ul>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Strategy monitoring will be wired to the Python engine package in the next release.
        </p>
      </Card>
    </div>
  );
}

function LogsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Execution Logs
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Complete history of all automated actions with SEBI-compliant audit trails.
          Every trigger, condition evaluation, and order execution is logged with
          timestamps, inputs, and results.
        </p>
        <div className="bg-surface-base border border-border-default rounded-lg p-4">
          <h4 className="text-sm font-semibold text-text-primary mb-2">Log Fields</h4>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {["Timestamp", "Strategy", "Action", "Symbol", "Side", "Qty", "Price", "Status"].map(
              (field) => (
                <div
                  key={field}
                  className="bg-surface-card border border-border-default rounded px-2 py-1 text-center"
                >
                  <p className="text-xs font-mono text-text-secondary">{field}</p>
                </div>
              ),
            )}
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Execution logs will be populated once automations are running. The data package
          already provides SEBI-compliant 5-year audit logging.
        </p>
      </Card>
    </div>
  );
}

function AutomationSettingsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Automation Settings
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Configure safety limits, kill switches, and notification preferences for all
          automated trading activities.
        </p>
        <div className="space-y-4">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Kill Switch</h4>
            <p className="text-xs text-text-muted">
              Emergency stop for all automated strategies. Accessible via Telegram bot
              with /kill command. Closes all positions and cancels pending orders.
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Order Limits</h4>
            <p className="text-xs text-text-muted">
              Max orders per minute, max position size, daily loss limit, max concurrent
              strategies. Safety guardrails that cannot be bypassed by automations.
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Telegram Alerts</h4>
            <p className="text-xs text-text-muted">
              Bot token, chat ID, alert frequency, message format. Receive trade
              notifications, P&L updates, and error alerts on Telegram.
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Execution Window</h4>
            <p className="text-xs text-text-muted">
              Market hours restriction, pre/post-market trading toggle, holiday calendar
              integration. Prevent accidental execution outside intended hours.
            </p>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-amber-500/20 text-amber-400 text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Settings will be persisted to workspace.json and configurable via form controls.
        </p>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function AutomateRoute() {
  const [activeSection, setActiveSection] = useState<SectionId>("flows");

  const sectionContent: Record<SectionId, React.ReactNode> = {
    flows: <FlowsSection />,
    schedules: <SchedulesSection />,
    monitors: <MonitorsSection />,
    logs: <LogsSection />,
    settings: <AutomationSettingsSection />,
  };

  return (
    <div className="h-full bg-surface-base flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4">
        <div className="flex items-center gap-3">
          <Workflow className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">Automation Hub</h1>
            <p className="text-xxs text-text-muted">
              54-node flow builder, cron scheduler, Telegram kill switch — no other broker has this
            </p>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <div className="w-56 border-r border-border-default bg-surface-card shrink-0 py-2">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            const isActive = activeSection === section.id;
            return (
              <button
                key={section.id}
                onClick={() => setActiveSection(section.id)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm font-sans transition-colors ${
                  isActive
                    ? "text-accent bg-accent/10 border-l-2 border-accent"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-base"
                }`}
              >
                <Icon className="w-4 h-4" />
                {section.label}
                <ChevronRight className={`w-3 h-3 ml-auto ${isActive ? "opacity-100" : "opacity-0"}`} />
              </button>
            );
          })}
        </div>

        {/* Content */}
        <ScrollArea className="flex-1">
          <div className="p-6 max-w-4xl">{sectionContent[activeSection]}</div>
        </ScrollArea>
      </div>
    </div>
  );
}
