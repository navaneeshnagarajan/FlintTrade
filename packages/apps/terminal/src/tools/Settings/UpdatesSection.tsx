/** Settings -> Updates for the Electron source/runtime and shell update flows. */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Box, GitBranch, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  applyShellUpdate,
  applySourceUpdate,
  checkShellUpdate,
  checkSourceUpdate,
  getUpdateState,
  isDesktopShell,
  onUpdateProgress,
  type UpdateKind,
  type UpdateSnapshot,
} from "@/lib/desktopShell";
import { SectionTitle } from "./shared";

interface FlowState {
  error: string | null;
  loading: boolean;
  pending: "check" | "apply" | null;
  snapshot: Readonly<UpdateSnapshot> | null;
}

type FlowStates = Record<UpdateKind, FlowState>;

const INITIAL_FLOW: FlowState = {
  error: null,
  loading: true,
  pending: null,
  snapshot: null,
};

function initialFlows(): FlowStates {
  return {
    shell: { ...INITIAL_FLOW },
    source: { ...INITIAL_FLOW },
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function shouldAcceptSnapshot(
  current: Readonly<UpdateSnapshot> | null,
  candidate: Readonly<UpdateSnapshot>,
): boolean {
  if (!current) return true;
  if (candidate.attempt !== current.attempt) return candidate.attempt > current.attempt;
  return candidate.heartbeatAt >= current.heartbeatAt;
}

function shortRevision(revision: string | null): ReactNode {
  if (!revision) return "Not reported";
  return (
    <span className="font-mono" title={revision}>
      {revision.slice(0, 12)}
    </span>
  );
}

function shellVersion(version: string | null): ReactNode {
  if (!version) return "Not reported";
  return <span className="font-mono">v{version.replace(/^v/, "")}</span>;
}

interface UpdateFlowCardProps {
  applyLabel: string;
  checkLabel: string;
  currentLabel: string;
  description: string;
  flow: FlowState;
  icon: ReactNode;
  onApply: () => void;
  onCheck: () => void;
  renderVersion: (version: string | null) => ReactNode;
  targetLabel: string;
  title: string;
}

function UpdateFlowCard({
  applyLabel,
  checkLabel,
  currentLabel,
  description,
  flow,
  icon,
  onApply,
  onCheck,
  renderVersion,
  targetLabel,
  title,
}: UpdateFlowCardProps) {
  const snapshot = flow.snapshot;
  const active = flow.pending !== null || snapshot?.status === "checking" || snapshot?.status === "applying";
  const applying = flow.pending === "apply" || snapshot?.status === "applying";
  const failure = flow.error ?? snapshot?.failure ?? null;
  const statusMessage = flow.pending === "check"
    ? "Checking for updates"
    : flow.pending === "apply"
      ? snapshot?.message ?? "Starting the update"
      : flow.loading
        ? "Reading updater state"
        : snapshot?.message ?? "Updater state is unavailable";

  return (
    <section className="space-y-3 rounded-lg border border-border-default bg-surface-card p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 flex-none items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          <p className="mt-0.5 text-xs leading-relaxed text-text-secondary">{description}</p>
        </div>
      </div>

      <dl className="grid gap-2 rounded-md border border-border-default bg-surface-base p-3 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-text-muted">{currentLabel}</dt>
          <dd className="mt-0.5 text-text-primary">{renderVersion(snapshot?.currentVersion ?? null)}</dd>
        </div>
        <div>
          <dt className="text-text-muted">{targetLabel}</dt>
          <dd className="mt-0.5 text-text-primary">
            {snapshot?.status === "available" || snapshot?.status === "applying"
              ? renderVersion(snapshot.version)
              : "None selected"}
          </dd>
        </div>
      </dl>

      {failure ? (
        <p className="text-xs text-loss" role="alert">{failure}</p>
      ) : (
        <p
          className="flex items-center gap-2 text-xs text-text-secondary"
          role={active ? "status" : undefined}
        >
          {active ? <Loader2 size={13} className="animate-spin" /> : null}
          {statusMessage}
        </p>
      )}

      {snapshot?.progress != null && (snapshot.status === "applying" || snapshot.status === "complete") ? (
        <div
          aria-label={`${title} update progress`}
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={snapshot.progress}
          className="h-1.5 overflow-hidden rounded-full bg-surface-hover"
          role="progressbar"
        >
          <div
            className="h-full rounded-full bg-accent transition-[width]"
            style={{ width: `${Math.max(0, Math.min(100, snapshot.progress))}%` }}
          />
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" className="text-xs" onClick={onCheck} disabled={active}>
          {flow.pending === "check" || snapshot?.status === "checking"
            ? <Loader2 size={13} className="animate-spin" />
            : <RefreshCw size={13} />}
          {checkLabel}
        </Button>
        {snapshot?.status === "available" ? (
          <Button type="button" size="sm" className="text-xs" onClick={onApply} disabled={active}>
            {applying ? <Loader2 size={13} className="animate-spin" /> : null}
            {applyLabel}
          </Button>
        ) : null}
      </div>
    </section>
  );
}

export function UpdatesSection() {
  if (!isDesktopShell()) return null;
  return <DesktopUpdatesSection />;
}

function DesktopUpdatesSection() {
  const [flows, setFlows] = useState<FlowStates>(initialFlows);
  const mounted = useRef(true);
  const requestIds = useRef<Record<UpdateKind, number>>({ shell: 0, source: 0 });
  const snapshots = useRef<Record<UpdateKind, Readonly<UpdateSnapshot> | null>>({ shell: null, source: null });

  const acceptSnapshot = useCallback((snapshot: Readonly<UpdateSnapshot>) => {
    if (!mounted.current) return;
    const previous = snapshots.current[snapshot.kind];
    if (!shouldAcceptSnapshot(previous, snapshot)) return;
    snapshots.current[snapshot.kind] = snapshot;
    setFlows((current) => {
      const flow = current[snapshot.kind];
      return {
        ...current,
        [snapshot.kind]: {
          ...flow,
          error: null,
          loading: false,
          pending: null,
          snapshot,
        },
      };
    });
  }, []);

  const fail = useCallback((kind: UpdateKind, error: unknown) => {
    if (!mounted.current) return;
    setFlows((current) => ({
      ...current,
      [kind]: {
        ...current[kind],
        error: errorMessage(error),
        loading: false,
        pending: null,
      },
    }));
  }, []);

  useEffect(() => {
    mounted.current = true;
    const unsubscribe = onUpdateProgress((snapshot) => {
      acceptSnapshot(snapshot);
    });

    for (const kind of ["source", "shell"] as const) {
      const requestId = ++requestIds.current[kind];
      const baseline = snapshots.current[kind];
      void getUpdateState(kind).then(
        (snapshot) => {
          if (requestIds.current[kind] === requestId) acceptSnapshot(snapshot);
        },
        (error: unknown) => {
          if (requestIds.current[kind] === requestId && snapshots.current[kind] === baseline) {
            fail(kind, error);
          }
        },
      );
    }

    return () => {
      mounted.current = false;
      unsubscribe();
    };
  }, [acceptSnapshot, fail]);

  const run = useCallback(async (
    kind: UpdateKind,
    operation: "check" | "apply",
    action: () => Promise<Readonly<UpdateSnapshot>>,
  ) => {
    const requestId = ++requestIds.current[kind];
    const baseline = snapshots.current[kind];
    setFlows((current) => ({
      ...current,
      [kind]: { ...current[kind], error: null, pending: operation },
    }));
    try {
      const snapshot = await action();
      if (requestIds.current[kind] === requestId) acceptSnapshot(snapshot);
    } catch (error) {
      if (requestIds.current[kind] === requestId && snapshots.current[kind] === baseline) {
        fail(kind, error);
      }
    }
  }, [acceptSnapshot, fail]);

  return (
    <div className="space-y-5">
      <SectionTitle>Updates</SectionTitle>

      <UpdateFlowCard
        applyLabel="Stage, verify and restart"
        checkLabel="Check source update"
        currentLabel="Current revision"
        description="Electron checks trusted main, stages a sibling checkout, builds the terminal, and verifies isolated health before it restarts onto the promoted source."
        flow={flows.source}
        icon={<GitBranch size={18} />}
        onApply={() => void run("source", "apply", applySourceUpdate)}
        onCheck={() => void run("source", "check", checkSourceUpdate)}
        renderVersion={shortRevision}
        targetLabel="Checked revision"
        title="Source and runtime"
      />

      <UpdateFlowCard
        applyLabel="Install and relaunch"
        checkLabel="Check shell update"
        currentLabel="Current shell version"
        description="Shell release discovery and the packaged installer handoff are owned by Electron. Installation relaunches the app when the new shell is ready."
        flow={flows.shell}
        icon={<Box size={18} />}
        onApply={() => void run("shell", "apply", applyShellUpdate)}
        onCheck={() => void run("shell", "check", checkShellUpdate)}
        renderVersion={shellVersion}
        targetLabel="Available shell version"
        title="Electron shell"
      />

      <p className="text-xs leading-relaxed text-text-muted">
        Source/runtime updates and Electron-shell installers are independent. Each check and apply
        action stays in the desktop process; this page only presents its typed, redacted state.
      </p>
    </div>
  );
}
