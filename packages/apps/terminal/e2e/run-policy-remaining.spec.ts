import fs from "node:fs/promises";
import type { Locator, Page, TestInfo } from "@playwright/test";
import { test, expect, setup, checkpoint, sha } from "./run-policy-core-fixture";
import { installDecodedReadHold } from "./run-policy-negative-seams";

const policy = "/v1/model-runs/r46-paper-a/configuration";
const selected = policy + "/control?action=learning-rights&subject=source";
type Core = Awaited<ReturnType<typeof setup>>;
async function paint(page: Page, assertion: () => Promise<void>) {
  for (let step = 0; step < 20; step++) {
    await page.clock.runFor(25);
    try { await assertion(); return; } catch (error) { if (step === 19) throw error; }
  }
}
async function open(page: Page, core: Core) {
  core.registerRead("/api/v1/backtest/strategies", 1);
  core.registerRead("/api/v1/execution-sessions", 1);
  await page.clock.install();
  await page.goto("/testing");
  await expect(page.getByRole("tab", {name:"Forward Test",exact:true})).toBeVisible();
  await core.finish(); await page.clock.pauseAt(new Date());
  await page.getByRole("tab", {name:"Forward Test",exact:true}).click();
  const run=page.getByRole("region",{name:"Paper run r46-paper-a",exact:true});
  await paint(page,()=>expect(run).toBeVisible({timeout:100}));
  await run.getByRole("button",{name:"Configure run policy",exact:true}).click();
  const panel=page.getByRole("region",{name:"Run policy r46-paper-a",exact:true});
  await core.completedBodies("GET",policy,1);
  await paint(page,()=>expect(panel.getByLabel("Policy workflow")).toBeVisible({timeout:100}));
  return panel;
}
async function rights(panel:Locator, core:Core) {
  await panel.getByLabel("Policy workflow").selectOption("rights-source");
  for(const [name,value] of Object.entries(core.bootstrap.values["rights-source"])) {
    if (["subject","fields"].includes(name)) continue;
    if(name === "selection") {
      for(const [key,nested] of Object.entries(value as Record<string,string>)) await panel.locator(`[name="selection.${key}"]`).fill(nested);
    } else await panel.locator(`[name="${name}"]`).fill(typeof value === "object" ? JSON.stringify(value) : String(value));
  }
}
async function geometry(target:Locator,info:TestInfo,name:string) {
  await target.evaluate(element=>element.scrollIntoView({block:"center",inline:"nearest"}));
  const value=await target.evaluate(element=>{
    const box=(r:DOMRect)=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height});
    const own=element.getBoundingClientRect(), range=document.createRange();range.selectNodeContents(element);
    const ranges=[...range.getClientRects()].map(box), ancestors=[];
    let complete=ranges.every(r=>r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight);
    let visible=true;
    for(let node:Element|null=element;node;node=node.parentElement){
      const css=getComputedStyle(node),r=node.getBoundingClientRect();
      visible=visible&&css.opacity!=="0"&&css.visibility!=="hidden"&&css.display!=="none";
      if(/hidden|clip|auto|scroll/.test(css.overflowX+css.overflowY)) {
        ancestors.push({box:box(r),overflowX:css.overflowX,overflowY:css.overflowY,scrollTop:node.scrollTop,clientHeight:node.clientHeight,scrollHeight:node.scrollHeight});
        if(/hidden|clip|auto|scroll/.test(css.overflowX))complete=complete&&ranges.every(v=>v.left>=r.left&&v.right<=r.right);
        if(/hidden|clip|auto|scroll/.test(css.overflowY))complete=complete&&ranges.every(v=>v.top>=r.top&&v.bottom<=r.bottom);
      }
    }
    const hit=document.elementFromPoint(own.left+own.width/2,own.top+own.height/2);
    return {literal:element.textContent,box:box(own),ranges,ancestors,viewport:{width:innerWidth,height:innerHeight},complete,visible,painted:!!hit&&(element.contains(hit)||hit.contains(element))};
  });
  await fs.writeFile(info.outputPath(name+".literal-geometry.json"),JSON.stringify(value,null,2));
  expect(value.complete).toBe(true);expect(value.visible).toBe(true);expect(value.painted).toBe(true);
}

test("R62 malformed ACK actual core write one independent read never verified success",async({page,syntheticApi},info)=>{
  const core=await setup(page,syntheticApi,info);
  core.registerRead(policy,1);core.registerRead(selected,2);
  const proposal={action:"learning-rights",expected_revision:0,value:core.bootstrap.values["rights-source"]};
  core.register("POST",policy+"/preview",1,request=>expect(request.postDataJSON()).toEqual(proposal));
  core.registerCorruptedAck(policy+"/confirm",request=>expect(request.postDataJSON()).toEqual({...proposal,confirmation:expect.any(String)}));
  const panel=await open(page,core);await rights(panel,core);
  await panel.getByRole("button",{name:"Read selected control",exact:true}).click();
  await core.completedBodies("GET",selected,1);
  await paint(page,()=>expect(panel.getByLabel("Selected control evidence")).toContainText("proven unissued",{timeout:100}));
  await panel.getByRole("button",{name:"Preview policy",exact:true}).click();
  await core.completedBodies("POST",policy+"/preview",1);
  await paint(page,()=>expect(panel.getByRole("button",{name:"Confirm exact policy",exact:true})).toBeVisible({timeout:100}));
  await panel.getByRole("button",{name:"Confirm exact policy",exact:true}).click();
  await core.completedBodies("GET",selected,2);
  await paint(page,()=>expect(panel.getByRole("alert")).toHaveText("Confirm outcome unknown or malformed. One exact read attempted; never replay confirmation.",{timeout:100}));
  await expect(panel).not.toContainText("Policy verified by exact readback");
  await expect(panel.getByRole("button",{name:"Confirm exact policy",exact:true})).toHaveCount(0);
  const durable=core.rows.filter(row=>row.path===selected).at(-1)!.response as {exact_control:{revision:number}};
  expect(durable.exact_control.revision).toBe(1);
  expect(core.rows.filter(row=>row.path===policy+"/confirm")).toHaveLength(1);
  await geometry(panel.getByRole("alert"),info,"malformed-ack-warning");await checkpoint(page,info,"malformed-ack-screen");
});

for(const phase of ["selected", "confirmed"] as const) for(const retirement of ["run","Activity"] as const) test(`R62 real decoded GET delivery after ${retirement} retirement${phase === "confirmed" ? " after real confirmation" : ""}`,async({page,syntheticApi},info)=>{
  const core=await setup(page,syntheticApi,info);
  core.registerRead(policy,retirement==="Activity"?2:1);core.registerRead(selected,phase==="confirmed"?2:1);
  if(retirement==="run")core.registerRead("/v1/model-runs/r46-paper-b/configuration",1);
  const panel=await open(page,core);await rights(panel,core);
  if (phase === "confirmed") {
    const proposal={action:"learning-rights",expected_revision:0,value:core.bootstrap.values["rights-source"]};
    core.register("POST",policy+"/preview",1,request=>expect(request.postDataJSON()).toEqual(proposal));
    core.register("POST",policy+"/confirm",1,request=>expect(request.postDataJSON()).toEqual({...proposal,confirmation:expect.any(String)}));
    await panel.getByRole("button",{name:"Read selected control",exact:true}).click();await core.completedBodies("GET",selected,1);
    await paint(page,()=>expect(panel.getByLabel("Selected control evidence")).toContainText("proven unissued",{timeout:100}));
    await panel.getByRole("button",{name:"Preview policy",exact:true}).click();await core.completedBodies("POST",policy+"/preview",1);
    await paint(page,()=>expect(panel.getByRole("button",{name:"Confirm exact policy",exact:true})).toBeVisible({timeout:100}));
  }
  const hold=await installDecodedReadHold(page,selected);
  const failures:string[]=[];
  page.on("requestfailed",request=>{if(request.url().endsWith(selected))failures.push(request.failure()?.errorText??"missing");});
  try {
    await panel.getByRole("button",{name:phase==="confirmed"?"Confirm exact policy":"Read selected control",exact:true}).click();
    await core.completedBodies("GET",selected,phase==="confirmed"?2:1);
    await expect.poll(async()=>(await hold.snapshot()).entered).toBe(1);
    const before=await hold.snapshot();expect(before.delivered).toBe(0);
    expect(sha(before.originalText!)).toBe(core.rows.filter(row=>row.path===selected).at(-1)!.responseSha256);
    expect((JSON.parse(before.originalText!) as {exact_control:{revision:number}}).exact_control.revision).toBe(phase==="confirmed"?1:0);
    let replacement:Locator;
    if(retirement==="run") {
      await page.getByRole("region",{name:"Paper run r46-paper-b",exact:true}).getByRole("button",{name:"Configure run policy",exact:true}).click();
      replacement=page.getByRole("region",{name:"Run policy r46-paper-b",exact:true});
    } else {
      await page.getByRole("navigation",{name:"Apps",exact:true}).getByRole("link",{name:"Learn",exact:true}).click();
      await paint(page,()=>expect(page.getByRole("region",{name:"Learn app",exact:true})).toBeVisible({timeout:100}));
      await page.getByRole("navigation",{name:"Apps",exact:true}).getByRole("link",{name:"Testing",exact:true}).click();
      replacement=page.getByRole("region",{name:"Run policy r46-paper-a",exact:true});
    }
    await paint(page,()=>expect(replacement.getByLabel("Policy workflow")).toBeVisible({timeout:100}));
    const baseline=await replacement.innerText();const reads=core.rows.length;
    await hold.release();await expect.poll(async()=>(await hold.snapshot()).delivered).toBe(1);
    await page.clock.runFor(25);
    const after=await hold.snapshot();
    expect(after.decodedAfter).toBe(before.decodedBefore);expect(after.sameReference).toBe(true);expect(after.failures).toEqual([]);expect(failures).toEqual([]);
    expect(await replacement.innerText()).toBe(baseline);
    await expect(replacement.getByRole("alert")).toHaveCount(0);await expect(replacement.getByLabel("Selected control evidence")).toHaveCount(0);
    await replacement.getByLabel("Policy workflow").selectOption("rights-source");
    await expect(replacement.locator('[name="documents"]')).toHaveValue("");
    expect(core.rows.length).toBe(reads);expect(core.rows.filter(row=>row.method!=="GET")).toHaveLength(phase==="confirmed"?2:0);
    await expect(replacement).not.toContainText("Policy verified by exact readback");
    await expect(replacement.getByRole("button",{name:"Confirm exact policy",exact:true})).toHaveCount(0);
    await fs.writeFile(info.outputPath("decoded-delivery.json"),JSON.stringify({before,after,baseline,reads,failures,retirement,phase},null,2));
    await geometry(replacement.getByRole("heading",{name:"Run policy and learning",exact:true}),info,"decoded-retired-heading");
    await checkpoint(page,info,"decoded-retired-screen");
  } finally {await hold.restore();}
});

test("R62 preview-auth scoped backtest refused by unchanged normal core",async({page,syntheticApi},info)=>{
  const core=await setup(page,syntheticApi,info);
  core.registerRead("/api/v1/backtest/strategies",1);
  const body={data_manifest_id:core.bootstrap.snapshot_id,symbol:"test-equity",exchange:"XNAS",interval:"1m",strategy:"EMACrossover",initial_capital:100000,position_size_pct:10,start_date:"",end_date:"",run_id:"r46-paper-a"};
  core.register("POST","/api/v1/backtest/run",1,request=>{
    expect(request.postDataJSON()).toEqual(body);expect(request.headers()["authorization"]).toBe("Bearer "+core.bootstrap.preview_session!.token);
    expect(request.headers()["x-api-key"]).toBeUndefined();
  });
  await page.clock.install();await page.goto("/testing");await core.finish();await page.clock.pauseAt(new Date());
  await page.getByRole("tab",{name:"Experiment evidence",exact:true}).click();
  await paint(page,()=>expect(page.getByLabel("Optional backtest run ID")).toBeVisible({timeout:100}));
  core.registerRead("/api/v1/native/accounts",1);
  await core.replaceAuth("preview");
  await core.completedBodies("GET","/api/v1/native/accounts",4);
  await expect.poll(()=>core.rows.filter(row=>row.status===401).map(row=>row.path).sort()).toEqual(["/api/v1/native/accounts","/api/v1/advisor/status","/api/v1/system/diagnostics","/v1/sandbox/funds","/v1/config/llm","/v1/sandbox/positions"].sort());
  await page.clock.runFor(25);
  await page.getByRole("tab",{name:"Experiment evidence",exact:true}).click();
  for(const [label,value] of Object.entries({"Optional backtest run ID":"r46-paper-a","History manifest ID":core.bootstrap.snapshot_id,"History instrument":"test-equity","History venue":"XNAS","History interval":"1m","Backtest strategy":"EMACrossover"}))await page.getByLabel(label,{exact:true}).fill(value);
  await page.getByRole("button",{name:"Run immutable backtest",exact:true}).click();
  const alert=page.getByRole("region",{name:"Testing app",exact:true}).getByRole("alert");
  await paint(page,()=>expect(alert).toContainText("Registered-run backtests are unavailable in the preview; the selector cannot label a simulated result.",{timeout:100}));
  expect(core.rows.filter(row=>row.method!=="GET")).toHaveLength(0);
  // Explicit hostile transport control, separate from the mounted preflight:
  // the same preview sentinel cannot acquire authority at the unchanged core.
  const refused=await page.evaluate(async body=>{
    const response=await fetch("/api/v1/backtest/run",{method:"POST",headers:{"Content-Type":"application/json",Authorization:"Bearer demo-user"},body:JSON.stringify(body)});
    return {status:response.status,body:await response.text()};
  },body);
  await core.completedBodies("POST","/api/v1/backtest/run",1);
  const row=core.rows.find(row=>row.method==="POST")!;
  expect(row.status).toBe(401);expect(refused.status).toBe(401);expect(row.trial).toBeUndefined();expect(row.experiment).toBeUndefined();
  await fs.writeFile(info.outputPath("preview-boundaries.json"),JSON.stringify({mountedWrites:0,explicitNegativeWrites:1,refused,preview:"demo-user sentinel, not a signed session"},null,2));
  await expect(page.getByLabel("Exact core evidence")).toHaveCount(0);
  expect(core.rows.filter(row=>row.method!=="GET")).toHaveLength(1);
  await geometry(alert,info,"preview-auth-refusal");await checkpoint(page,info,"preview-auth-screen");
  // Explicitly retire preview authority after its actual local/HTTP refusal.
  // Continue observing the complete case through a genuine replacement login;
  // neither the observation window nor an HTTP ledger is cleared here.
  await syntheticApi.retireRead("/api/v1/native/accounts");core.registerRead("/api/v1/native/accounts",3);
  await core.replaceAuth("replacement");await page.clock.resume();
  await core.completedBodies("GET","/api/v1/native/accounts",7);
  await expect.poll(async()=>(await core.queries()).filter(q=>JSON.stringify(q.key)==='["timings"]'&&q.observers>0).map(q=>[q.status,q.fetchStatus,q.failures])).toEqual([["error","idle",3]]);
  await page.clock.pauseAt((await page.evaluate(()=>Date.now()))+100);
  expect(core.rows.filter(row=>row.method!=="GET")).toHaveLength(1);
  expect(core.rows.filter(row=>row.status===403)).toEqual([]);
});

for (const replacement of ["issued auth", "backend"] as const) test(`R62 genuine ${replacement} replacement retires reviewed private draft`,async({page,syntheticApi},info)=>{
  if (replacement === "backend") await page.context().setExtraHTTPHeaders({ Connection: "close" });
  const core=await setup(page,syntheticApi,info);core.registerRead(policy,2);core.registerRead(selected,1);
  const proposal={action:"learning-rights",expected_revision:0,value:core.bootstrap.values["rights-source"]};
  core.register("POST",policy+"/preview",1,request=>expect(request.postDataJSON()).toEqual(proposal));
  const panel=await open(page,core);await rights(panel,core);
  await panel.getByRole("button",{name:"Read selected control",exact:true}).click();await core.completedBodies("GET",selected,1);
  await paint(page,()=>expect(panel.getByLabel("Selected control evidence")).toBeVisible({timeout:100}));
  await panel.getByRole("button",{name:"Preview policy",exact:true}).click();await core.completedBodies("POST",policy+"/preview",1);
  await paint(page,()=>expect(panel.getByRole("button",{name:"Confirm exact policy",exact:true})).toBeVisible({timeout:100}));
  // This is a new authenticated shell lifetime, not an allowance donated to
  // original startup or to a mutation-induced read.
  core.registerRead("/api/v1/native/accounts",3);
  await syntheticApi.retireRead("/api/v1/backtest/strategies");
  core.registerRead("/api/v1/backtest/strategies",1);
  await syntheticApi.retireRead("/api/v1/execution-sessions");
  core.registerRead("/api/v1/execution-sessions",1);
  const oldDraft = await panel.locator('[name="documents"]').elementHandle();
  if (replacement === "backend") await core.replaceBackend();
  await core.replaceAuth("replacement");
  await page.clock.resume();
  await core.completedBodies("GET","/api/v1/native/accounts",6);
  await expect.poll(async()=>(await core.queries()).filter(q=>JSON.stringify(q.key)==='["timings"]'&&q.observers>0).map(q=>[q.status,q.fetchStatus,q.failures])).toEqual([["error","idle",3]]);
  await page.clock.pauseAt((await page.evaluate(()=>Date.now()))+100);
  await page.getByRole("tab",{name:"Forward Test",exact:true}).click();
  await core.completedBodies("GET","/api/v1/execution-sessions",2);
  const run=page.getByRole("region",{name:"Paper run r46-paper-a",exact:true});
  await paint(page,()=>expect(run).toBeVisible({timeout:100}));
  if(await run.getByRole("button",{name:"Configure run policy",exact:true}).isVisible())await run.getByRole("button",{name:"Configure run policy",exact:true}).click();
  await paint(page,()=>expect(panel.getByLabel("Policy workflow")).toBeVisible({timeout:100}));
  expect(await page.evaluate(element => element !== null && !element.isConnected, oldDraft)).toBe(true);
  await expect(panel.getByRole("button",{name:"Confirm exact policy",exact:true})).toHaveCount(0);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await panel.getByLabel("Policy workflow").selectOption("rights-source");
  await expect(panel.locator('[name="documents"]')).toHaveValue("");await expect(panel.locator('[name="review_statement"]')).toHaveValue("");
  expect(core.rows.filter(row=>row.method!=="GET")).toHaveLength(1);
  await geometry(panel.getByRole("heading",{name:"Run policy and learning",exact:true}),info,"auth-retired-heading");await checkpoint(page,info,"auth-retired-screen");
});

test("R62 protection requires canonical owned entry negative not positive qualification",async({page,syntheticApi},info)=>{
  const core=await setup(page,syntheticApi,info);core.registerRead(policy,1);
  const url="/api/v1/protection/grants/r46-paper-a";core.registerRead(url,2);
  const value={policy_revision:"r62-missing-entry-negative",valid_until:core.bootstrap.times.valid_until,position:{symbol:"RELIANCE",exchange:"NSE",product:"MIS",entry_order_ids:["r62-not-an-owned-entry"],quantity:1},hedge_scope:[],risk_policy:"unhedged-cash-reduction-only",max_quantity:1,max_notional:100,read:{selector:"dhan:synthetic-unavailable",valid_until:core.bootstrap.times.valid_until,max_reads:2,max_age_seconds:30}};
  core.register("POST","/api/v1/protection/grants",1,request=>expect(request.postDataJSON()).toEqual({run_id:"r46-paper-a",expected_revision:0,policy:value}));
  await open(page,core);
  const run=page.getByRole("region",{name:"Paper run r46-paper-a",exact:true});
  await run.getByRole("button",{name:"Hide run policy",exact:true}).click();await run.getByRole("button",{name:"Protection policy",exact:true}).click();
  const panel=page.getByRole("region",{name:"Protection policy r46-paper-a",exact:true});
  await core.completedBodies("GET",url,1);
  await paint(page,()=>expect(panel).toContainText("Authority: not_issued · Supervision: unavailable",{timeout:100}));
  for(const [key,item] of Object.entries(value)) {
    if(["hedge_scope","risk_policy"].includes(key))continue;
    if(typeof item==="object")for(const [field,v]of Object.entries(item))await panel.locator(`[name="${key}.${field}"]`).fill(Array.isArray(v)?v.join("\n"):String(v));
    else await panel.locator(`[name="${key}"]`).fill(String(item));
  }
  await panel.getByRole("button",{name:"Review protection policy",exact:true}).click();await panel.getByRole("button",{name:"Approve exact protection policy",exact:true}).click();
  await core.completedBodies("GET",url,2);
  await paint(page,()=>expect(panel.getByRole("alert")).toHaveText("Protection outcome unknown or changed. Exact read attempted; read and reconcile. No automatic replay.",{timeout:100}));
  const reads=core.rows.filter(row=>row.path===url);expect(reads[1].response).toEqual(reads[0].response);
  expect(core.rows.filter(row=>row.method!=="GET").map(row=>[row.path,row.status])).toEqual([["/api/v1/protection/grants",403]]);
  await expect(panel).not.toContainText("Protection policy readback verified");
  await geometry(panel.getByRole("alert"),info,"protection-entry-refusal");await checkpoint(page,info,"protection-entry-screen");
});
