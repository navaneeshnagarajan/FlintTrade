import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { exportKnowledgeVersion, retireKnowledgeVersion, type KnowledgeSkill } from "@/services/knowledgeApi";
import { captureKnowledgeBinding, knowledgeLocalScopeKey, knowledgeScopeKey } from "@/services/knowledgeScope";

/** Canonical core controls only: no file moves, self-validation or promotion. */
export function KnowledgeVersionActions({ skill, scope, available }: { skill: KnowledgeSkill; scope: string; available: boolean }) {
  const client = useQueryClient();
  const reasonId = useId();
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [exported, setExported] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const current = () => scope === knowledgeScopeKey(client);
  async function run(action: () => Promise<void>) {
    if (!current() || !available) return;
    setBusy(true); setError(""); setNotice("");
    try { await action(); }
    catch (error) { if (current()) setError(error instanceof Error ? error.message : "Canonical operation unavailable"); }
    finally { if (current()) setBusy(false); }
  }
  return <div className="space-y-2">
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" size="sm" disabled={busy || !available} onClick={() => void run(async () => {
        setExported("");
        const value = await exportKnowledgeVersion(skill, captureKnowledgeBinding(client));
        if (current()) setExported(JSON.stringify(value, null, 2));
      })}>Export canonical version</Button>
      <Button variant="outline" size="sm" disabled={busy || !available || skill.state === "retired"} onClick={() => { setConfirming(true); setNotice(""); setError(""); }}>Retire version</Button>
    </div>
    {confirming && <fieldset aria-label="Confirm retirement" className="space-y-2 rounded border border-border-default p-3">
      <legend className="text-sm font-semibold">Retire this exact version?</legend>
      <p className="break-all text-xs">{skill.name} · {skill.version_id}</p>
      <p className="text-xs text-warning">Retirement prevents future use of this version, including run-pinned use. It does not delete history or retained source files, select a replacement, stop a run or close positions.</p>
      <label htmlFor={reasonId} className="text-xs">Retirement reason</label>
      <Input id={reasonId} value={reason} maxLength={4096} disabled={busy} onChange={event => setReason(event.target.value)} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="destructive" disabled={busy || !available || !reason.trim()} onClick={() => void run(async () => {
          const result = await retireKnowledgeVersion(skill, reason, captureKnowledgeBinding(client));
          if (!current()) return;
          client.setQueryData(["knowledge", "skills", knowledgeLocalScopeKey(client)], result.catalogue);
          setConfirming(false); setReason("");
          setNotice(`Retirement verified: ${result.version}. Receipt: ${result.receipt}. History and source preserved.`);
        })}>Confirm retirement</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirming(false)}>Cancel retirement</Button>
      </div>
    </fieldset>}
    {error && <p role="alert" className="text-xs text-warning">{error}. A failed acknowledgement is not proof that no change occurred. Refresh the exact version before trying again.</p>}
    {notice && <p role="status" className="break-all text-xs">{notice}</p>}
    {exported && <details open><summary>Canonical portable package</summary>
      <pre aria-label="Canonical version export" className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{exported}</pre>
      <a className="text-xs text-accent underline" href={`data:application/json;charset=utf-8,${encodeURIComponent(exported)}`} download={`${skill.name}-${skill.package_hash}.json`}>Download canonical JSON</a>
    </details>}
  </div>;
}
