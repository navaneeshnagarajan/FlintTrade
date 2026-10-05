import { useEffect, useState, version as reactVersion, type ReactNode } from "react";
import { version as reactDomVersion } from "react-dom";
import { BUILD_VERSIONS } from "@/lib/versionInventory";
import { useAuthStore } from "@/stores/authStore";
import { getVersionInventory, getOllamaVersionInventory, type BackendVersionInventory, type OllamaVersionInventory } from "@/services/ftApi.versions";

interface Snapshot<T> { token: string; value?: T; failed?: boolean }
interface Row { name: string; values: ReactNode[] }

function VersionTable({ title, columns, rows }: { title: string; columns: string[]; rows: Row[] }) {
  return <div className="space-y-2">
    <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">{title}</h3>
    <div className="overflow-x-auto rounded border border-border-default">
      <table aria-label={title} className="w-full text-xs text-left">
        <thead className="bg-surface-card text-text-muted"><tr>
          <th scope="col" className="px-3 py-2 font-medium">Component</th>
          {columns.map((column) => <th key={column} scope="col" className="px-3 py-2 font-medium">{column}</th>)}
        </tr></thead>
        <tbody>{rows.map((row) => <tr key={row.name} className="border-t border-border-default">
          <th scope="row" className="px-3 py-2 font-normal text-text-muted">{row.name}</th>
          {row.values.map((value, index) => <td key={index} className="px-3 py-2 text-text-primary font-mono break-words">{value}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
  </div>;
}

export function VersionInventory() {
  const token = useAuthStore((state) => state.token);
  const demo = token === "demo-user" || token === "dev-bypass";
  const [backend, setBackend] = useState<Snapshot<BackendVersionInventory> | null>(null);
  const [ollama, setOllama] = useState<Snapshot<OllamaVersionInventory> | null>(null);
  useEffect(() => {
    if (!token || demo) return;
    let current = true;
    const controller = new AbortController();
    void getVersionInventory(controller.signal).then(
      (value) => { if (current) setBackend({ token, value }); },
      () => { if (current) setBackend({ token, failed: true }); },
    );
    // Pure bounded version read: never reconcile operations, start the runtime or request models.
    void getOllamaVersionInventory(controller.signal).then(
      (value) => { if (current) setOllama({ token, value }); },
      () => { if (current) setOllama({ token, failed: true }); },
    );
    return () => { current = false; controller.abort(); };
  }, [token, demo]);
  const backendState = backend?.token === token ? backend : null;
  const ollamaState = ollama?.token === token ? ollama : null;
  const data = !demo && token ? backendState?.value : undefined;
  const localAi = !demo && token ? ollamaState?.value : undefined;
  const desktop = window.flintDesktop;
  const unavailable = "Unavailable";

  return <div className="space-y-5">
    <div className="space-y-1">
      <h3 className="text-sm font-semibold text-text-primary">Runtime and dependency versions</h3>
      <p className="text-xs text-text-secondary">Running versions, installed packages, configured pins and declared ranges are separate sources. This inventory does not establish broker or model qualification.</p>
    </div>
    <VersionTable title="Frontend libraries" columns={["Running / build-resolved", "Declared range"]} rows={BUILD_VERSIONS.libraries.map((row) => ({
      name: row.name === "react" ? "React" : row.name === "react-dom" ? "ReactDOM" : row.name,
      values: [row.name === "react" ? reactVersion : row.name === "react-dom" ? reactDomVersion : row.installed ?? unavailable, row.declared ?? unavailable],
    }))} />
    <p className="text-xs text-text-secondary">React and ReactDOM report their bundled runtime version. Other frontend versions are resolved from the installed packages when this terminal is built.</p>
    <VersionTable title="Build tools" columns={["Used for this build", "Declared range"]} rows={BUILD_VERSIONS.buildTools.map((row) => ({ name: row.name, values: [row.installed ?? unavailable, row.declared ?? "Not applicable"] }))} />
    <VersionTable title="Configured tool pins" columns={["Configured pin"]} rows={BUILD_VERSIONS.pins.map((row) => ({ name: row.name, values: [row.version ?? unavailable] }))} />
    <p className="text-xs text-text-secondary">Bootstrap pins describe installer configuration, not currently running tools. Source commit supplied at build: <span className="font-mono break-all">{BUILD_VERSIONS.commit ?? "Unavailable"}</span>.</p>
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">Desktop runtimes</h3>
      {!desktop ? <p className="text-xs text-text-secondary">Not running in a desktop shell. Electron, Chromium, Node.js and V8 versions are not applicable to this browser session.</p>
        : !desktop.runtimeVersions ? <p className="text-xs text-text-secondary">Runtime metadata is unavailable in this desktop shell version.</p>
        : <VersionTable title="Desktop shell" columns={["Running"]} rows={([
          ["electron", "Electron"], ["chrome", "Chromium"], ["node", "Node.js (desktop)"], ["v8", "V8"],
        ] as const).map(([key, name]) => ({ name, values: [desktop.runtimeVersions?.[key] ?? unavailable] }))} />}
    </div>
    {demo || !token ? <p role="status" className="text-xs text-text-secondary">{demo ? "Backend and Ollama versions are unavailable in Demo. No local runtime is queried." : "Sign in to view backend, broker SDK and Ollama versions."}</p> : <>
      {!data ? <p role="status" className="text-xs text-text-secondary">{backendState?.failed ? "Backend version information is unavailable. The backend may be offline or may need updating." : "Loading backend versions…"}</p> : <>
        <VersionTable title="Backend runtimes" columns={["Running"]} rows={[
          { name: "FlintTrade backend", values: [data.app_version ?? unavailable] },
          ...data.runtimes.map((row) => ({ name: row.name, values: [row.version ?? unavailable] })),
        ]} />
        <VersionTable title="Backend packages" columns={["Installed distribution", "Configured lockfile pin"]} rows={data.packages.map((row) => ({ name: row.name, values: [row.installed ?? "Not installed / unavailable", row.configured ?? unavailable] }))} />
        <p className="text-xs text-text-secondary">flinttrade-ticks is a compiled Rust/Python extension distribution. A Rust compiler version is not reported by the running backend.</p>
        <VersionTable title="Broker SDKs" columns={["Installed distribution", "Configured pin"]} rows={data.brokers.map((row) => ({ name: row.name, values: [row.installed ?? "Not installed / unavailable", row.configured ?? unavailable] }))} />
        {data.brokers.filter((row) => row.source_commit || row.installed_commit || row.release_version !== undefined).map((row) => <div key={row.name} className="text-xs text-text-secondary space-y-1">
          {row.release_version !== undefined && <p>{row.name} release compatibility baseline: <span className="font-mono">{row.release_version ?? unavailable}</span></p>}
          <p>{row.name} configured Git revision: <span className="font-mono break-all">{row.source_commit ?? unavailable}</span></p>
          <p>{row.name} installed Git revision (distribution metadata): <span className="font-mono break-all">{row.installed_commit ?? "Not reported"}</span></p>
        </div>)}
      </>}
      {!localAi ? <p role="status" className="text-xs text-text-secondary">{ollamaState?.failed ? "Ollama version information is unavailable. The status endpoint may be offline or inaccessible." : "Loading Ollama versions…"}</p> : <>
        <VersionTable title="Ollama" columns={["Version"]} rows={[
          { name: "Configured managed pin", values: [localAi.configured ?? unavailable] },
          { name: "Reported running server", values: [localAi.status === "reported" ? localAi.reported ?? unavailable : localAi.status === "not_responding" ? "Not responding" : unavailable] },
        ]} />
        <p className="text-xs text-text-secondary">The server version is reported by the managed loopback endpoint; this does not prove ownership or model readiness. No model inference is performed.</p>
      </>}
    </>}
  </div>;
}
