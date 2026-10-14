import fs from "node:fs/promises";
import type { Locator, Page, TestInfo } from "@playwright/test";
import { test, expect, setup, checkpoint, declaredReticle, addWidget, observePolicyTiming } from "./run-policy-core-fixture";

async function paint(page: Page, assertion: () => Promise<void>) {
  for (let step = 0; step < 20; step++) {
    await observePolicyTiming(page, `paint-${step}-before`);
    await page.clock.runFor(25);
    await observePolicyTiming(page, `paint-${step}-after`);
    try { await assertion(); return; } catch (error) { if (step === 19) throw error; }
  }
}
type Core = Awaited<ReturnType<typeof setup>>;
const policyURL = "/v1/model-runs/r46-paper-a/configuration";
async function openPolicy(page: Page, core: Core, sessionReads = 1) {
  core.registerRead("/api/v1/backtest/strategies", 1);
  core.registerRead("/api/v1/execution-sessions", sessionReads);
  await page.clock.install();
  await page.goto("/testing");
  await expect(page.getByRole("tab", { name: "Forward Test", exact: true })).toBeVisible();
  await core.finish();
  await page.clock.pauseAt(new Date());
  await page.getByRole("tab", { name: "Forward Test", exact: true }).click();
  const row = page.getByRole("region", { name: "Paper run r46-paper-a", exact: true });
  await paint(page, () => expect(row).toBeVisible({ timeout: 100 }));
  await row.getByRole("button", { name: "Configure run policy", exact: true }).click();
  const panel = page.getByRole("region", { name: "Run policy r46-paper-a", exact: true });
  await paint(page, () => expect(panel.getByLabel("Policy workflow")).toBeVisible({ timeout: 100 }));
  return panel;
}
async function fillValue(panel: Locator, value: Record<string, unknown>) {
  for (const [key, item] of Object.entries(value)) {
    if (["subject", "fields", "role", "identity_scope"].includes(key)) continue;
    if (key === "operations") {
      for (const operation of item as string[]) await panel.getByLabel(operation, { exact: true }).check();
      continue;
    }
    if (["selection", "reservation", "controls"].includes(key)) {
      for (const [child, nested] of Object.entries(item as Record<string, unknown>)) {
        const input = panel.locator(`[name="${key}.${child}"]`);
        if (key === "controls") await input.selectOption(String(nested));
        else await input.fill(String(nested));
      }
    } else await panel.locator(`[name="${key}"]`).fill(typeof item === "object" ? JSON.stringify(item) : String(item));
  }
}

for (const mode of ["live", "practice"] as const) test(`R46 access grant revoke actual Testing Paper identity with unchanged ${mode} selection`, async ({ page, syntheticApi }, info) => {
  const core = await setup(page, syntheticApi, info, mode);
  if(mode==="live") core.registerRead("/api/v1/safety/config", 1);
  core.registerRead("/api/v1/backtest/strategies", 1);
  core.registerRead("/api/v1/execution-sessions", 1);
  const url = "/v1/model-runs/r46-paper-a/configuration";
  core.registerRead(url, 4);
  let previews = 0, confirmations = 0;
  const workflows = ["access", "grant", "revoke-grant"];
  core.register("POST", url + "/preview", 3, request => {
    const action = workflows[previews++];
    expect(request.postDataJSON()).toEqual({ action, expected_revision: action === "revoke-grant" ? 1 : 0, value: core.bootstrap.values[action] });
  });
  core.register("POST", url + "/confirm", 3, request => {
    const action = workflows[confirmations++];
    const body = request.postDataJSON();
    expect(body.confirmation).toEqual(expect.any(String));
    expect(body).toEqual({ action, expected_revision: action === "revoke-grant" ? 1 : 0, value: core.bootstrap.values[action], confirmation: body.confirmation });
  });
  // Install before the mounted queries create timers. Installing after startup
  // leaves their already-created native intervals outside the paused clock.
  await page.clock.install();
  await page.goto("/testing");
  await expect(page.getByRole("tab", { name: "Forward Test", exact: true })).toBeVisible();
  await core.finish();
  await page.clock.pauseAt(new Date());
  await observePolicyTiming(page, "clock-owned-from-before-startup");
  await page.getByRole("tab", { name: "Forward Test", exact: true }).click();
  const row = page.getByRole("region", { name: "Paper run r46-paper-a", exact: true });
  await paint(page, () => expect(row).toBeVisible({ timeout: 100 }));
  await row.getByRole("button", { name: "Configure run policy", exact: true }).click();
  const panel = page.getByRole("region", { name: "Run policy r46-paper-a", exact: true });
  await paint(page, () => expect(panel.getByLabel("Policy workflow")).toBeVisible({ timeout: 100 }));
  for (const action of workflows) {
    await panel.getByLabel("Policy workflow").selectOption(action);
    await fillValue(panel, core.bootstrap.values[action]);
    await panel.getByRole("button", { name: "Preview policy", exact: true }).click();
    await core.completedBodies("POST", url + "/preview", workflows.indexOf(action) + 1);
    await paint(page, () => expect(panel.getByRole("button", { name: "Confirm exact policy", exact: true })).toBeVisible({ timeout: 100 }));
    await panel.getByRole("button", { name: "Confirm exact policy", exact: true }).click();
    await core.completedBodies("GET", url, workflows.indexOf(action) + 2);
    await paint(page, () => expect(panel.getByRole("status")).toHaveText("Policy verified by exact readback. Not activated or qualified.", { timeout: 100 }));
  }
  expect(previews).toBe(3); expect(confirmations).toBe(3);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("flinttrade:mode")!).state.mode)).toBe(mode);
  await expect(page.getByRole("region", { name: "Execution sessions", exact: true })).toContainText("Native Live execution remains unavailable.");
  await panel.getByRole("status").scrollIntoViewIfNeeded();
  await checkpoint(page, info, "access-grant-revoke");
  await declaredReticle(info, [{ kind: "text", scope: '[aria-label="Run policy r46-paper-a"]', contains: "Policy verified by exact readback. Not activated or qualified.", visible: true }, { kind: "net", method: "POST", urlContains: url + "/confirm", count: 3 }]);
});

for (const workflow of ["rights-source", "rights-output", "evaluation", "candidate", "training-backend"] as const) {
  test(`R46 exact ${workflow} selected read preview confirmation independent GET`, async ({ page, syntheticApi }, info) => {
    const core = await setup(page, syntheticApi, info);
    const value = core.bootstrap.values[workflow];
    const action = workflow.startsWith("rights-") ? "learning-rights" : workflow;
    const selector: Record<string, string> = action === "learning-rights" ? { action, subject: String(value.subject) }
      : action === "candidate" ? { action, trial: String(value.candidate) } : action === "training-backend" ? { action, connection_id: String(value.connection_id) } : { action, trial: String(value.trial), suite: String(value.suite) };
    const exactURL = policyURL + "/control?" + new URLSearchParams(selector).toString();
    core.registerRead(policyURL, 1); core.registerRead(exactURL, 2);
    core.register("POST", policyURL + "/preview", 1, request => {
      expect(request.postDataJSON()).toEqual({ action, expected_revision: 0, value });
    });
    core.register("POST", policyURL + "/confirm", 1, request => {
      const body = request.postDataJSON();
      expect(body.confirmation).toEqual(expect.any(String));
      expect(body).toEqual({ action, expected_revision: 0, value, confirmation: body.confirmation });
    });
    const panel = await openPolicy(page, core);
    await panel.getByLabel("Policy workflow").selectOption(workflow);
    await fillValue(panel, value);
    await expect(panel.getByRole("button", { name: "Preview policy", exact: true })).toBeDisabled();
    await panel.getByRole("button", { name: "Read selected control", exact: true }).click();
    await paint(page, () => expect(panel.getByLabel("Selected control evidence")).toContainText("Not configured (proven unissued)", {timeout:100}));
    await panel.getByRole("button", { name: "Preview policy", exact: true }).click();
    await paint(page, () => expect(panel.getByRole("button", { name: "Confirm exact policy", exact: true })).toBeVisible({timeout:100}));
    await panel.getByRole("button", { name: "Confirm exact policy", exact: true }).click();
    await paint(page, () => expect(panel.getByRole("status")).toHaveText("Policy verified by exact readback. Not activated or qualified.", {timeout:100}));
    const readbacks = core.rows.filter(row => row.method === "GET" && row.path.endsWith(exactURL));
    expect(readbacks).toHaveLength(2);
    const before = readbacks[0].response as {exact_control: {identity: unknown}};
    const after = readbacks[1].response as {exact_control: {revision: number; identity: unknown; value: unknown}};
    const ack = core.rows.find(row => row.path.endsWith("/confirm"))!.response as {exact_control: unknown};
    const preview = core.rows.find(row => row.path.endsWith("/preview"))!.response as {target_identity: unknown};
    expect(after.exact_control.revision).toBe(1); expect(ack.exact_control).toEqual(after.exact_control);
    expect(preview.target_identity).toEqual(action === "learning-rights" ? null : before.exact_control.identity);
    if (action === "learning-rights") {
      expect(JSON.stringify(after)).not.toContain("Synthetic reviewed UTF-8 bytes only");
      await expect(panel.locator('[name="documents"]')).toHaveValue("");
      expect(after.exact_control.identity).toEqual(expect.objectContaining({event_id:expect.any(String),rights_digest:expect.any(String)}));
    } else expect(after.exact_control.identity).toEqual(before.exact_control.identity);
    await panel.getByRole("status").scrollIntoViewIfNeeded();
    await checkpoint(page, info, workflow + "-exact-readback");
    await declaredReticle(info, [{ kind: "text", scope: '[aria-label="Run policy r46-paper-a"]', contains: "Policy verified by exact readback. Not activated or qualified.", visible: true }, {kind:"net",method:"POST",urlContains:policyURL+"/confirm",count:1}, {kind:"net",method:"GET",urlContains:exactURL,count:2}]);
  });
}

const dimensions = ["requests", "input_tokens", "output_tokens", "currency_micros", "credits_micros", "compute_milliseconds", "bytes", "concurrency", "storage_bytes"];
for(const mismatch of [false,true]) test(`R46 ${mismatch?"mismatched reviewed rights refuse":"compact long document review keyboard cancel"}`,async({page,syntheticApi},info)=>{
  const core=await setup(page,syntheticApi,info);core.registerRead(policyURL,1);
  core.registerRead(policyURL+"/control?action=learning-rights&subject=source",1);
  const value=structuredClone(core.bootstrap.values["rights-source"]);
  if(mismatch) (value.documents as Record<string,string>)["r46-source"] += "Changed bytes without a matching fact digest";
  core.register("POST",policyURL+"/preview",1,request=>expect(request.postDataJSON()).toEqual({action:"learning-rights",expected_revision:0,value}));
  const panel=await openPolicy(page,core);await panel.getByLabel("Policy workflow").selectOption("rights-source");await fillValue(panel,value);
  await panel.getByRole("button",{name:"Read selected control",exact:true}).click();
  await paint(page,()=>expect(panel.getByLabel("Selected control evidence")).toBeVisible({timeout:100}));
  if(!mismatch){
    await page.setViewportSize({width:600,height:760});await page.clock.runFor(25);
    const document=panel.locator('[name="documents"]');await document.focus();await page.keyboard.press("Control+End");
    await expect(document).toHaveValue(JSON.stringify(value.documents));
    await checkpoint(page,info,"compact-long-reviewed-document");
  }
  await panel.getByRole("button",{name:"Preview policy",exact:true}).click();
  if(mismatch){
    await paint(page,()=>expect(panel.getByRole("alert")).toContainText("Policy unavailable or refused (400). Read exact policy before continuing.",{timeout:100}));
    await expect(panel.getByRole("button",{name:"Confirm exact policy",exact:true})).toHaveCount(0);
    expect(core.rows.filter(row=>row.method==="POST").map(row=>row.status)).toEqual([400]);
    expect(core.rows.find(row=>row.method==="POST")!.response).toEqual({code:"invalid_model_configuration"});
    await geometry(panel.getByRole("alert"),info,"mismatched-reviewed-rights");await checkpoint(page,info,"mismatched-reviewed-rights");
    await declaredReticle(info,[{kind:"net",method:"POST",urlContains:policyURL+"/preview",status:400,count:1},{kind:"net",method:"POST",urlContains:policyURL+"/confirm",count:0},{kind:"text",scope:'[aria-label="Run policy r46-paper-a"]',contains:"Policy unavailable or refused (400). Read exact policy before continuing.",visible:true}]);
  }else{
    const confirm=panel.getByRole("button",{name:"Confirm exact policy",exact:true});
    await paint(page,()=>expect(confirm).toBeVisible({timeout:100}));
    await geometry(confirm,info,"compact-policy-confirm");await confirm.focus();await page.keyboard.press("Tab");
    const cancel=panel.getByRole("button",{name:"Cancel proposal",exact:true});await expect(cancel).toBeFocused();
    await geometry(cancel,info,"compact-policy-cancel");await checkpoint(page,info,"compact-long-policy-review");
    await page.keyboard.press("Enter");await expect(confirm).toHaveCount(0);
    expect(core.rows.filter(row=>row.path.endsWith("/confirm"))).toEqual([]);
    await declaredReticle(info,[{kind:"net",method:"POST",urlContains:policyURL+"/preview",count:1},{kind:"net",method:"POST",urlContains:policyURL+"/confirm",count:0}]);
  }
});
test("R46 learning dataset nine explicit bounds separate consent and existing binding", async ({page, syntheticApi}, info) => {
  const core = await setup(page, syntheticApi, info);
  core.registerRead(policyURL, 5);
  for (const subject of ["source", "output"]) core.registerRead(policyURL + "/control?action=learning-rights&subject=" + subject, 2);
  let planned: {action: string; expected_revision: number; value: Record<string, unknown>};
  core.register("POST", policyURL + "/preview", 5, request => expect(request.postDataJSON()).toEqual(planned));
  core.register("POST", policyURL + "/confirm", 5, request => {
    const body = request.postDataJSON(); expect(body.confirmation).toEqual(expect.any(String));
    expect(body).toEqual({...planned, confirmation:body.confirmation});
  });
  let panel = await openPolicy(page, core);
  async function configure(workflow: string, value: Record<string, unknown>) {
    const action = workflow.startsWith("rights-") ? "learning-rights" : workflow;
    planned = {action, expected_revision:0, value};
    await panel.getByLabel("Policy workflow").selectOption(workflow); await fillValue(panel, value);
    if (action === "learning-rights") {
      await panel.getByRole("button", {name:"Read selected control",exact:true}).click();
      await paint(page, () => expect(panel.getByLabel("Selected control evidence")).toContainText("proven unissued", {timeout:100}));
    }
    await panel.getByRole("button", {name:"Preview policy",exact:true}).click();
    await paint(page, () => expect(panel.getByRole("button", {name:"Confirm exact policy",exact:true})).toBeVisible({timeout:100}));
    await panel.getByRole("button", {name:"Confirm exact policy",exact:true}).click();
    await paint(page, () => expect(panel.getByRole("status")).toHaveText("Policy verified by exact readback. Not activated or qualified.", {timeout:100}));
    return (core.rows.filter(row => row.path.endsWith("/confirm")).at(-1)!.response as {result: Record<string, unknown>}).result;
  }
  const source = await configure("rights-source",core.bootstrap.values["rights-source"]);
  const output = await configure("rights-output",core.bootstrap.values["rights-output"]);
  const dataset = await configure("learning-dataset", {source_rights:source.event_id,output_rights:output.event_id,as_of_start:core.bootstrap.times.now,as_of_end:core.bootstrap.times.end});
  const reservation = Object.fromEntries(dimensions.map(key => [key,0]));
  Object.assign(reservation,{requests:1,concurrency:1,input_tokens:32768,output_tokens:256,bytes:32768,currency_micros:1000});
  const policy = await configure("learning-policy", {selection:core.bootstrap.selection,reservation,controls:Object.fromEntries(dimensions.map(key => [key,"hard-local"])),controls_evidence:"R46 explicit synthetic controls",principal:"r46-synthetic-recipient",region:"test-region",terms_revision:"r46-terms",valid_until:core.bootstrap.times.valid_until,max_output_tokens:256,timeout_seconds:5});
  const proposal = {scope:dataset.scope,recipient:policy.recipient,purpose:"reflection",operations:["chat"],valid_from:core.bootstrap.times.now,valid_until:core.bootstrap.times.end,limits:Object.fromEntries(dimensions.map(key => [key,1000000])),max_rows:10,max_trials:10,retention:"synthetic-one-day",derivatives:"same-scope-no-publication",objective:"synthetic-reflection",rights:core.bootstrap.values["rights-source"].rights,supersedes:null};
  const consent = "/v1/learning/permissions"; let grant = "";
  core.register("POST",consent+"/preview",1,request => expect(request.postDataJSON()).toEqual(proposal));
  core.register("POST",consent+"/grants",1,request => { const body=request.postDataJSON();expect(body).toEqual({...proposal,confirmation:expect.any(String)});},row => {
    grant = (row.response as {grant_id:string}).grant_id;
    core.registerRead(consent+"/grants/"+grant,1);
  });
  await page.getByRole("navigation",{name:"Apps",exact:true}).getByRole("link",{name:"Settings",exact:true}).click();
  await addWidget(page,"Learning permissions");
  const permissions=page.getByRole("region",{name:"Learning permissions",exact:true});
  await paint(page,()=>expect(permissions.getByLabel("Complete learning proposal JSON")).toBeVisible({timeout:100}));
  await permissions.getByLabel("Complete learning proposal JSON").fill(JSON.stringify(proposal));
  await permissions.getByRole("button",{name:"Preview exact permission",exact:true}).click();
  await paint(page,()=>expect(permissions.getByRole("button",{name:"Confirm this exact permission",exact:true})).toBeEnabled({timeout:100}));
  await permissions.getByRole("button",{name:"Confirm this exact permission",exact:true}).click();
  await paint(page,()=>expect(permissions.getByLabel("Learning permission evidence")).toContainText('"egress_blocked": false',{timeout:100}));
  expect(grant).not.toBe("");
  await expect(permissions.getByLabel("Learning grant ID",{exact:true})).toHaveValue(grant);
  const consentRead = core.rows.find(row=>row.path.endsWith(consent+"/grants/"+grant))!;
  expect(JSON.parse(await permissions.getByLabel("Learning permission evidence").innerText())).toEqual(consentRead.response);
  await checkpoint(page,info,"separate-learning-consent");
  await page.getByRole("navigation",{name:"Apps",exact:true}).getByRole("link",{name:"Testing",exact:true}).click();
  panel=page.getByRole("region",{name:"Run policy r46-paper-a",exact:true});
  await paint(page,()=>expect(panel.getByLabel("Policy workflow")).toBeVisible({timeout:100}));
  await configure("learning-binding",{grant_id:grant});
  await checkpoint(page,info,"exact-existing-consent-binding");
  expect(core.rows.filter(row=>row.method==="POST")).toHaveLength(12);
  await declaredReticle(info,[{kind:"net",method:"POST",urlContains:policyURL+"/confirm",count:5},{kind:"net",method:"POST",urlContains:consent+"/grants",count:1},{kind:"text",scope:'[aria-label="Run policy r46-paper-a"]',contains:"Policy verified by exact readback. Not activated or qualified.",visible:true}]);
});

for(const reason of ["expired","revoked","expanded"]) test(`R46 binding refusal ${reason} retains no extra authority`,async({page,syntheticApi},info)=>{
  const core=await setup(page,syntheticApi,info);core.registerRead(policyURL,2);
  const value=core.bootstrap.values["learning-binding"];
  core.register("POST",policyURL+"/preview",1,request=>expect(request.postDataJSON()).toEqual({action:"learning-binding",expected_revision:0,value}));
  const panel=await openPolicy(page,core);await panel.getByLabel("Policy workflow").selectOption("learning-binding");await fillValue(panel,value);
  await panel.getByRole("button",{name:"Preview policy",exact:true}).click();
  await paint(page,()=>expect(panel.getByRole("alert")).toContainText("Policy unavailable or refused (400). Read exact policy before continuing.",{timeout:100}));
  await expect(panel.getByRole("button",{name:"Confirm exact policy",exact:true})).toHaveCount(0);
  await geometry(panel.getByRole("alert"),info,"binding-refusal-"+reason);await checkpoint(page,info,"binding-refusal-"+reason);
  await panel.getByRole("button",{name:"Read exact policy",exact:true}).click();
  await paint(page,()=>expect(panel.getByLabel("Policy workflow")).toBeVisible({timeout:100}));
  const readbacks=core.rows.filter(row=>row.method==="GET"&&row.path.endsWith(policyURL));
  expect(readbacks).toHaveLength(2);expect(readbacks[1].response).toEqual(readbacks[0].response);
  expect(core.rows.filter(row=>row.method!=="GET").map(row=>[row.method,row.status])).toEqual([["POST",400]]);
  expect(core.rows.find(row=>row.method==="POST")!.response).toEqual({code:"invalid_model_configuration"});
  await declaredReticle(info,[{kind:"net",method:"POST",urlContains:policyURL+"/preview",status:400,count:1},{kind:"net",method:"POST",urlContains:policyURL+"/confirm",count:0}]);
});
for (const runId of ["", "r46-paper-a", " r46-paper-a"]) {
  test(`R46 history selector ${runId === "" ? "blank omission" : runId.startsWith(" ") ? "malformed refusal" : "exact owned scope"}`, async ({page,syntheticApi},info) => {
    const core=await setup(page,syntheticApi,info);
    core.registerRead("/api/v1/backtest/strategies",1);
    const valid=!runId.startsWith(" "); let trial="", experiment="";
    const requestBody={data_manifest_id:core.bootstrap.snapshot_id,symbol:"test-equity",exchange:"XNAS",interval:"1m",strategy:"EMACrossover",initial_capital:100000,position_size_pct:10,start_date:"",end_date:"",...(runId ? {run_id:runId}:{})};
    if (valid) core.register("POST","/api/v1/backtest/run",1,request=>{
      expect(request.postDataJSON()).toEqual(requestBody);
      if(runId) {expect(request.headers()["authorization"]).toBe("Bearer "+core.bootstrap.session.token);expect(request.headers()["x-api-key"]).toBeUndefined();}
    },row=>{
      expect(row.status).toBe(200); trial=row.trial!;experiment=row.experiment!;
      expect(trial).toMatch(/^[A-Za-z0-9_.:-]+$/);expect(experiment).toMatch(/^[A-Za-z0-9_.:-]+$/);
      core.registerRead("/api/v1/backtest/trials/"+trial,1);
      core.registerRead("/api/v1/backtest/experiments/"+experiment,1);
    });
    await page.clock.install();await page.goto("/testing");await core.finish();await page.clock.pauseAt(new Date());
    await page.getByRole("tab",{name:"Experiment evidence",exact:true}).click();
    await paint(page,()=>expect(page.getByLabel("Optional backtest run ID")).toBeVisible({timeout:100}));
    await page.getByLabel("Optional backtest run ID").fill(runId);
    for(const [label,value] of Object.entries({"History manifest ID":core.bootstrap.snapshot_id,"History instrument":"test-equity","History venue":"XNAS","History interval":"1m","Backtest strategy":"EMACrossover"})) await page.getByLabel(label,{exact:true}).fill(value);
    await page.getByRole("button",{name:"Run immutable backtest",exact:true}).click();
    if(!valid){
      await paint(page,()=>expect(page.getByRole("region",{name:"Testing app",exact:true}).getByRole("alert")).toContainText("exact registered run selector",{timeout:100}));
      expect(core.rows.filter(row=>row.method!=="GET")).toEqual([]);
      await checkpoint(page,info,"history-malformed-refusal");
      await declaredReticle(info,[{kind:"net",method:"POST",count:0},{kind:"text",scope:'[aria-label="Testing app"]',contains:"exact registered run selector",visible:true}]);
      return;
    }
    await paint(page,()=>expect(page.getByLabel("Exact core evidence")).toContainText("completed",{timeout:100}));
    const receipts=page.getByRole("list",{name:"Captured backtest receipts",exact:true});
    if(runId) await expect(receipts).toContainText("Submitted run selector: r46-paper-a (not verified control scope)");
    else await expect(receipts).not.toContainText("Submitted run selector");
    await page.getByRole("button",{name:"Read experiment "+experiment,exact:true}).click();
    await paint(page,()=>expect(page.getByLabel("Exact core evidence")).toContainText(experiment,{timeout:100}));
    const stored=core.rows.find(row=>row.path.endsWith("/experiments/"+experiment))!.response as {data:{manifest:{control_scope?:unknown}}};
    expect(stored.data.manifest.control_scope ?? null).toEqual(runId ? core.bootstrap.runs[0] : null);
    await page.getByLabel("Exact core evidence").scrollIntoViewIfNeeded(); await checkpoint(page,info,"history-"+(runId?"scoped":"unscoped"));
    await declaredReticle(info,[{kind:"net",method:"POST",urlContains:"/api/v1/backtest/run",count:1},{kind:"text",scope:'[aria-label="Exact core evidence"]',contains:experiment,visible:true}]);
  });
}

for (const stage of ["preview", "ack", "readback"] as const) for (const retirement of ["run", "Activity"] as const) {
  test(`R46 held real ${stage} retires across ${retirement} without replay`, async ({page,syntheticApi},info)=>{
    const core=await setup(page,syntheticApi,info);let release!:()=>void, entered=false;
    const gate=new Promise<void>(resolve=>{release=resolve;});
    const hold=async()=>{entered=true;await gate;};
    const exactURL=policyURL+"/control?action=learning-rights&subject=source";
    core.registerRead(policyURL, retirement==="Activity"?2:1);
    if(retirement==="run") core.registerRead("/v1/model-runs/r46-paper-b/configuration",1);
    let reads=0;
    const retiredFailures:string[]=[];
    page.on("requestfailed",request=>{if(new URL(request.url()).pathname+new URL(request.url()).search === (process.env["R24_STAGE"] === "reticle"?"/ft-api":"")+exactURL) retiredFailures.push(request.failure()?.errorText ?? "missing failure");});
    // A required initial GET is complete. The separately declared retired
    // transport is expected to abort, NOT a late decoded read or startup abort.
    if(stage==="readback") core.register("GET",exactURL,2,undefined,async()=>{if(++reads===2) await hold();});
    else core.registerRead(exactURL,1);
    const value=core.bootstrap.values["rights-source"];
    const proposal={action:"learning-rights",expected_revision:0,value};
    core.register("POST",policyURL+"/preview",1,request=>expect(request.postDataJSON()).toEqual(proposal),stage==="preview"?hold:undefined);
    if(stage!=="preview") core.register("POST",policyURL+"/confirm",1,request=>expect(request.postDataJSON()).toEqual({...proposal,confirmation:expect.any(String)}),stage==="ack"?hold:undefined);
    try {
      const panel=await openPolicy(page,core);
      await panel.getByLabel("Policy workflow").selectOption("rights-source");await fillValue(panel,value);
      await panel.getByRole("button",{name:"Read selected control",exact:true}).click();
      await paint(page,()=>expect(panel.getByLabel("Selected control evidence")).toBeVisible({timeout:100}));
      await panel.getByRole("button",{name:"Preview policy",exact:true}).click();
      if(stage!=="preview"){
        await paint(page,()=>expect(panel.getByRole("button",{name:"Confirm exact policy",exact:true})).toBeVisible({timeout:100}));
        await panel.getByRole("button",{name:"Confirm exact policy",exact:true}).click();
      }
      await expect.poll(async()=>{await page.clock.runFor(25);return entered;},{timeout:8000}).toBe(true);
      let replacement:Locator;
      if(retirement==="run"){
        await page.getByRole("region",{name:"Paper run r46-paper-b",exact:true}).getByRole("button",{name:"Configure run policy",exact:true}).click();
        replacement=page.getByRole("region",{name:"Run policy r46-paper-b",exact:true});
      }else{
        await page.getByRole("navigation",{name:"Apps",exact:true}).getByRole("link",{name:"Learn",exact:true}).click();
        await paint(page,()=>expect(page.getByRole("region",{name:"Learn app",exact:true})).toBeVisible({timeout:100}));
        await page.getByRole("navigation",{name:"Apps",exact:true}).getByRole("link",{name:"Testing",exact:true}).click();
        replacement=page.getByRole("region",{name:"Run policy r46-paper-a",exact:true});
      }
      await paint(page,()=>expect(replacement.getByLabel("Policy workflow")).toBeVisible({timeout:100}));
      release();
      await page.clock.runFor(75);
      if(stage==="readback") await expect.poll(()=>retiredFailures).toEqual(["net::ERR_ABORTED"]);
      await expect(replacement).not.toContainText("Policy request pending");
      await expect(replacement).not.toContainText("Policy verified by exact readback");
      await expect(replacement.getByRole("alert")).toHaveCount(0);
      await expect(replacement.getByRole("button",{name:"Confirm exact policy",exact:true})).toHaveCount(0);
      await replacement.getByLabel("Policy workflow").selectOption("rights-source");
      await expect(replacement.locator('[name="documents"]')).toHaveValue("");
      await expect(replacement.locator('[name="review_statement"]')).toHaveValue("");
      expect(core.rows.filter(row=>row.method==="POST")).toHaveLength(stage==="preview"?1:2);
      expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain("Synthetic reviewed UTF-8 bytes only");
      await checkpoint(page,info,`retired-${stage}-${retirement}`);
      await declaredReticle(info,[{kind:"net",method:"POST",urlContains:policyURL+"/confirm",count:stage==="preview"?0:1},{kind:"text",scope:`[aria-label="Run policy ${retirement==="run"?"r46-paper-b":"r46-paper-a"}"]`,contains:"Run policy and learning",visible:true}]);
    }finally{release();}
  });
}

async function geometry(target:Locator,info:TestInfo,name:string){
  await target.evaluate(element=>element.scrollIntoView({block:"center",inline:"nearest"}));
  const observed=await target.evaluate(element=>{
    const box=(r:DOMRect)=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height});
    const own=element.getBoundingClientRect(); const range=document.createRange();range.selectNodeContents(element);
    const ranges=[...range.getClientRects()].map(box);const clipping=[];
    let complete=ranges.every(r=>r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight);
    for(let parent=element.parentElement;parent;parent=parent.parentElement){
      const css=getComputedStyle(parent),rect=parent.getBoundingClientRect();
      if(/hidden|clip|auto|scroll/.test(css.overflowX+css.overflowY)) clipping.push({box:box(rect),overflowX:css.overflowX,overflowY:css.overflowY,clientHeight:parent.clientHeight,scrollHeight:parent.scrollHeight,scrollTop:parent.scrollTop,minHeight:css.minHeight,flex:css.flex});
      if(/hidden|clip|auto|scroll/.test(css.overflowX)) complete=complete&&ranges.every(r=>r.left>=rect.left&&r.right<=rect.right);
      if(/hidden|clip|auto|scroll/.test(css.overflowY)) complete=complete&&ranges.every(r=>r.top>=rect.top&&r.bottom<=rect.bottom);
    }
    const hit=document.elementFromPoint(own.left+own.width/2,own.top+own.height/2);
    return {literal:element.textContent,ranges,clipping,box:box(own),complete,painted:!!hit&&(element.contains(hit)||hit.contains(element))};
  });
  await fs.writeFile(info.outputPath(name+".literal-geometry.json"),JSON.stringify(observed,null,2));
  expect.soft(observed.complete,"complete literal text in actual clipping ancestors").toBe(true);
  expect.soft(observed.painted,"native centre paint target").toBe(true);
}
for (const fault of [false,true]) {
  test(`R46 protection ${fault?"custody unavailable":"not issued compact review and keyboard cancel"}`,async({page,syntheticApi},info)=>{
    const core=await setup(page,syntheticApi,info);core.registerRead(policyURL,1);
    const url="/api/v1/protection/grants/r46-paper-a";core.registerRead(url,1);
    await openPolicy(page,core);
    const run=page.getByRole("region",{name:"Paper run r46-paper-a",exact:true});
    await run.getByRole("button",{name:"Hide run policy",exact:true}).click();
    await run.getByRole("button",{name:"Protection policy",exact:true}).click();
    const panel=page.getByRole("region",{name:"Protection policy r46-paper-a",exact:true});
    if(fault){
      await paint(page,()=>expect(panel.getByRole("alert")).toContainText("Protection custody unavailable. Authority, exposure and duty are unknown, not absent.",{timeout:100}));
      await expect(panel).not.toContainText("Authority: not_issued");
      await geometry(panel.getByRole("alert"),info,"protection-unavailable");await checkpoint(page,info,"protection-unavailable");
      expect(core.rows.find(row=>row.path.endsWith(url))?.status).toBe(503);
      await declaredReticle(info,[{kind:"net",method:"GET",urlContains:url,status:503,count:1},{kind:"net",method:"POST",count:0},{kind:"text",scope:'[aria-label="Protection policy r46-paper-a"]',contains:"unknown, not absent.",visible:true}]);
      return;
    }
    await paint(page,()=>expect(panel).toContainText("Authority: not_issued · Supervision: unavailable",{timeout:100}));
    await expect(panel).toContainText("Duty: not_granted · Remaining quantity: unknown");
    const value={policy_revision:"r46-review-only",valid_until:core.bootstrap.times.valid_until,"position.symbol":"RELIANCE","position.exchange":"NSE","position.product":"MIS","position.entry_order_ids":"r46-not-owned-no-approval","position.quantity":1,max_quantity:1,max_notional:100,"read.selector":"dhan:synthetic-unavailable","read.valid_until":core.bootstrap.times.valid_until,"read.max_reads":2,"read.max_age_seconds":30};
    for(const [name,v]of Object.entries(value))await panel.locator(`[name="${name}"]`).fill(String(v));
    await page.setViewportSize({width:600,height:560});await page.clock.runFor(25);
    await panel.getByRole("button",{name:"Review protection policy",exact:true}).click();
    const approve=panel.getByRole("button",{name:"Approve exact protection policy",exact:true});
    await expect(approve).toBeVisible();await geometry(approve,info,"compact-protection-approval");
    await approve.focus();await page.keyboard.press("Tab");
    const cancel=panel.getByRole("button",{name:"Cancel protection review",exact:true});
    await expect(cancel).toBeFocused();await geometry(cancel,info,"compact-protection-cancel");await checkpoint(page,info,"compact-protection-review");
    await page.keyboard.press("Enter");await expect(approve).toHaveCount(0);
    expect(core.rows.filter(row=>row.method!=="GET")).toEqual([]);
    await declaredReticle(info,[{kind:"net",method:"POST",count:0},{kind:"text",scope:'[aria-label="Protection policy r46-paper-a"]',contains:"Authority: not_issued",visible:true}]);
  });
}
