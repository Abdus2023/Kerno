#!/usr/bin/env -S deno run --allow-read --allow-write
/**
 * Deterministic workflow runner.
 *
 * This runner deliberately performs orchestration only. Evidence-producing
 * operations belong to adapters. A missing adapter is BLOCKED, never PASS.
 */
type Status = "PENDING"|"RUNNING"|"COMPLETE"|"BLOCKED"|"FAILED";
type Phase = "DISCOVER"|"FREEZE"|"MODEL"|"IMPLEMENT"|"TEST"|"VERIFY"|"RELEASE_GATE"|"TAG";

interface Stage {
  id:string;
  status:Status;
  phase:Phase;
  input_digest?:string;
  output_digest?:string;
  evidence_ids:string[];
  blockers:string[];
  authority:string;
  started_at?:string;
  completed_at?:string;
}

interface State {
  schema:"agent.continuation-state/1";
  objective:string;
  snapshot:{repository:string; ref:string; commit:string; tree?:string};
  phase:Phase;
  stages:Stage[];
  completed:string[];
  open:string[];
  blocked:string[];
  next:string[];
  evidence_digest?:string;
}

const ORDER: Array<[string,Phase]> = [
 ["snapshot","FREEZE"], ["audit","MODEL"], ["evidence","TEST"],
 ["verify","VERIFY"], ["trust-design","MODEL"], ["protocol","MODEL"],
 ["federation","MODEL"], ["market","MODEL"], ["plan","IMPLEMENT"],
 ["release-gate","RELEASE_GATE"]
];

function fail(message:string):never { throw new Error("BLOCKED: "+message); }

async function readJson(path:string):Promise<any> {
  return JSON.parse(await Deno.readTextFile(path));
}

function now(){ return new Date().toISOString(); }

function validate(s:State){
  if(s.schema!=="agent.continuation-state/1") fail("unsupported state schema");
  if(!s.snapshot?.repository || !s.snapshot?.commit) fail("repository snapshot is incomplete");
  if(!Array.isArray(s.stages)) fail("stages missing");
  const ids=new Set<string>();
  for(const x of s.stages){
    if(ids.has(x.id)) fail("duplicate stage: "+x.id);
    ids.add(x.id);
    if(x.status==="COMPLETE" && !x.output_digest) fail("complete stage lacks output digest: "+x.id);
    if(x.status==="COMPLETE" && !x.evidence_ids?.length && x.id!=="snapshot")
      fail("complete stage lacks evidence: "+x.id);
  }
}

function transition(s:State,id:string,status:Status,reason?:string){
  const x=s.stages.find(v=>v.id===id);
  if(!x) fail("unknown stage: "+id);
  if(status==="COMPLETE" && id!=="snapshot" && !x.evidence_ids.length)
    fail("cannot complete without evidence: "+id);
  x.status=status;
  if(status==="RUNNING") x.started_at=now();
  if(status==="COMPLETE") x.completed_at=now();
  if(status==="BLOCKED" && reason) x.blockers=[reason];
}

async function main(){
  const statePath=Deno.args[0] ?? ".agent/state/continuation.json";
  const state=await readJson(statePath) as State;
  validate(state);

  const manifest=await readJson(".agent/tools/workflow.json");
  const required=new Set(manifest.stages.filter((x:any)=>x.required).map((x:any)=>x.id));

  for(const id of required){
    const stage=state.stages.find(x=>x.id===id);
    if(!stage) fail("required stage absent: "+id);
  }

  const pending=ORDER.map(x=>x[0]).find(id=>{
    const s=state.stages.find(x=>x.id===id);
    return s && s.status!=="COMPLETE";
  });

  if(!pending){
    state.phase="TAG";
    state.next=[];
    await Deno.writeTextFile(statePath, JSON.stringify(state,null,2)+"\n");
    if(pending==="snapshot") {
    console.log(JSON.stringify({decision:"SNAPSHOT_REQUIRED",stage:"snapshot",message:"Bind the workflow to an exact commit and tree before audit."},null,2));
    return;
  }
  console.log(JSON.stringify({decision:"READY_FOR_TAG",phase:state.phase}));
    return;
  }

  const stage=state.stages.find(x=>x.id===pending)!;
  if(stage.status==="BLOCKED"){
    console.log(JSON.stringify({
      decision:"BLOCKED",
      stage:pending,
      blockers:stage.blockers,
      instruction:"Add new evidence or change the scoped input; do not override state."
    },null,2));
    return;
  }

  transition(state,pending,"RUNNING");
  state.next=[pending];
  await Deno.writeTextFile(statePath, JSON.stringify(state,null,2)+"\n");

  // Execution adapters are intentionally external. The runner never
  // fabricates evidence merely because a stage exists.
  console.log(JSON.stringify({
    decision:"ADAPTER_REQUIRED",
    stage:pending,
    phase:stage.phase,
    authority:stage.authority,
    message:"Execute the stage adapter, attach evidence, then rerun the runner."
  },null,2));
}

if(import.meta.main) await main();
