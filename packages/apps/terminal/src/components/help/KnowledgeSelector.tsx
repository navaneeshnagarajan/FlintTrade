import { useState, useSyncExternalStore } from "react";
import { onlineManager, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { KnowledgeVersionActions } from "./KnowledgeVersionActions";
import { useAuthStore } from "@/stores/authStore";
import { assertKnowledgeBinding, listKnowledgeSkills, readKnowledgeSkill, sameKnowledgeIdentity, type KnowledgeIdentity, type KnowledgeSkill } from "@/services/knowledgeApi";
import { captureKnowledgeBinding, knowledgeLocalScopeKey, knowledgeScopeKey, observeKnowledgeScope, sameKnowledgeScope, useKnowledgeScope } from "@/services/knowledgeScope";

const EMPTY_SELECTION: KnowledgeIdentity[] = [];
function useCatalogue() {
  const scope = useKnowledgeScope();
  const client = useQueryClient();
  const local = knowledgeLocalScopeKey(client);
  const authenticated = useAuthStore(state => state.status === "logged-in" && !!state.token);
  const online = useSyncExternalStore(onlineManager.subscribe.bind(onlineManager), () => onlineManager.isOnline());
  const query = useQuery({
    queryKey: ["knowledge", "skills", local],
    queryFn: async () => {
      const started = knowledgeScopeKey(client);
      const catalogue = await listKnowledgeSkills(() => started === knowledgeScopeKey(client));
      observeKnowledgeScope(client, catalogue.scope);
      return catalogue;
    },
    enabled: authenticated, retry: false, staleTime: 10_000,
  });
  let matches = false;
  if (query.data) {
    try { matches = sameKnowledgeScope(captureKnowledgeBinding(client).scope, query.data.scope); } catch { /* Not yet observed. */ }
  }
  return { ...query, scope, current: matches && authenticated && online && query.isSuccess && !query.isStale && !query.isFetching };
}

/** Store exact local choices; the public task wire contract remains skill:<name>. */
export function useSelectedKnowledge() {
  const client = useQueryClient();
  const catalog = useCatalogue();
  const key = ["knowledge", "selected-skills", catalog.scope];
  const { data = EMPTY_SELECTION } = useQuery<KnowledgeIdentity[]>({
    queryKey: key, initialData: EMPTY_SELECTION, queryFn: async () => EMPTY_SELECTION, enabled: false,
  });
  const selected = catalog.current && data.every(identity => catalog.data?.skills.some(row => row.enabled && sameKnowledgeIdentity(row, identity))) ? data : [];
  return [selected.map(row => `skill:${row.name}`), (refs: string[]) => {
    if (catalog.scope !== knowledgeScopeKey(client) || !catalog.current) return;
    client.setQueryData(key, refs.flatMap(ref => {
      const row = catalog.data?.skills.find(item => item.enabled && ref === `skill:${item.name}`);
      return row ? [{ name: row.name, version_id: row.version_id, package_hash: row.package_hash }] : [];
    }));
  }] as const;
}

/** R15 calls this immediately before dispatch. Core still re-resolves at send. */
export async function revalidateSelectedKnowledge(client: QueryClient): Promise<string[]> {
  const scope = knowledgeScopeKey(client);
  const current = () => scope === knowledgeScopeKey(client);
  const identities = client.getQueryData<KnowledgeIdentity[]>(["knowledge", "selected-skills", scope]) ?? EMPTY_SELECTION;
  if (!onlineManager.isOnline()) throw new Error("Knowledge cannot be verified while offline");
  const binding = captureKnowledgeBinding(client);
  const catalogue = await listKnowledgeSkills(current);
  assertKnowledgeBinding(binding, catalogue.scope);
  const bodies = await Promise.all(identities.map(identity => readKnowledgeSkill(identity.name, identity, binding)));
  if (!current()) throw new Error("Knowledge scope changed before dispatch");
  const latest = client.getQueryData<KnowledgeIdentity[]>(["knowledge", "selected-skills", scope]) ?? EMPTY_SELECTION;
  if (identities.length !== latest.length || identities.some((identity, index) => !sameKnowledgeIdentity(identity, latest[index]))) {
    throw new Error("Knowledge selection changed before dispatch");
  }
  return bodies.map(body => body.reference);
}

type SelectorProps = { selected: string[]; onSelection: (refs: string[]) => void };
export function KnowledgeSelector(props: SelectorProps) {
  const scope = useKnowledgeScope();
  return <ScopedKnowledgeSelector key={scope} {...props} scope={scope} />;
}
function ScopedKnowledgeSelector({ selected, onSelection, scope }: SelectorProps & { scope: string }) {
  const client = useQueryClient();
  const catalog = useCatalogue();
  const [procedure, setProcedure] = useState<{ identity: KnowledgeIdentity; value: Awaited<ReturnType<typeof readKnowledgeSkill>> } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const current = () => scope === knowledgeScopeKey(client);
  async function read(skill: KnowledgeSkill) {
    if (!current() || !catalog.current) return;
    setBusy(true); setError(""); setProcedure(null);
    try {
      const value = await readKnowledgeSkill(skill.name, skill, captureKnowledgeBinding(client));
      if (current()) setProcedure({ identity: skill, value });
    } catch (error) {
      if (current()) setError(error instanceof Error ? error.message : "Procedure unavailable");
    } finally { if (current()) setBusy(false); }
  }
  const available = catalog.current && procedure && catalog.data?.skills.some(row => row.enabled && sameKnowledgeIdentity(row, procedure.identity));
  return <section className="space-y-3" aria-label="Shared knowledge catalogue">
    <h3 className="font-semibold">Shared knowledge catalogue</h3>
    <p className="text-xs text-text-secondary">Read complete canonical procedures, then explicitly select advisory context. Candidates are not activated here. Selection does not enable learning, training or trading. Core re-resolves canonical names and rights at send time; this is not a version pin.</p>
    <Button size="sm" variant="outline" disabled={catalog.isFetching} onClick={() => void catalog.refetch()}>Refresh catalogue</Button>
    {catalog.error && <p role="alert" className="text-warning">Catalogue unavailable: {catalog.error.message}</p>}
    {error && <p role="alert" className="text-warning">{error}</p>}
    {catalog.isPending && <p role="status">Reading installed knowledge…</p>}
    {catalog.data && !catalog.current && <p role="status">Catalogue is not current. Refresh before selecting a procedure.</p>}
    {catalog.current && catalog.data?.skills.length === 0 && <p>No procedures returned by core.</p>}
    <ul className="space-y-3">{catalog.data?.skills.map(skill => <li key={skill.version_id} className="space-y-2 rounded border border-border-default p-3">
      <p>{skill.name}</p><p className="break-all font-mono text-xs">{skill.version_id}</p>
      <p className="text-xs">{skill.state} · {skill.origin}{skill.validated ? " · Validated" : " · Not validated"}{skill.default ? " · Default" : ""}{skill.run_pinned ? " · Run-pinned" : ""}{skill.enabled ? " · Enabled" : " · Not enabled"}</p>
      {skill.description && <p className="text-xs">{skill.description}</p>}
      {skill.unavailable_reason && <p className="text-xs text-warning">{skill.unavailable_reason}</p>}
      {skill.enabled && <Button size="sm" variant="outline" disabled={busy || !catalog.current} onClick={() => void read(skill)}>Read procedure {skill.name}</Button>}
      <KnowledgeVersionActions skill={skill} scope={scope} available={catalog.current} />
    </li>)}</ul>
    {available && procedure && <div className="space-y-3 rounded border border-border-default p-3">
      <p aria-label="Procedure identity" className="break-all font-mono text-xs">{procedure.value.reference} · {procedure.value.version} · {procedure.value.classification}</p>
      <pre aria-label="Complete procedure body" className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{procedure.value.body}</pre>
      <Button size="sm" onClick={() => {
        if (current()) onSelection(selected.includes(procedure.value.reference) ? selected.filter(ref => ref !== procedure.value.reference) : [...selected, procedure.value.reference]);
      }}>{selected.includes(procedure.value.reference) ? "Unselect this procedure" : "Select this procedure"}</Button>
      <details><summary>Version and influence receipt</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(procedure.value.receipt, null, 2)}</pre></details>
    </div>}
    <p className="break-all text-xs">Explicit task selection: {catalog.current && selected.length ? selected.join(", ") : "None"}</p>
  </section>;
}
export default function KnowledgeLibrary() {
  const [selected, setSelected] = useSelectedKnowledge();
  const navigate = useNavigate();
  return <div className="space-y-4 p-4"><KnowledgeSelector selected={selected} onSelection={setSelected} /><Button disabled={!selected.length} onClick={() => navigate("/automation", { state: { openWidget: { widgetId: "model-routing" } } })}>Prepare advisory task</Button></div>;
}
