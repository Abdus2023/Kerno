export type ExecutionStatus="PASSED"|"FAILED"|"CANCELLED"|"TIMED_OUT"|"NOT_OBSERVABLE";
export interface ExecutionEvidence {
  schema:"agent.execution-evidence/1";
  execution_id:string;
  authority:string;
  kind:"CI"|"TEST"|"BUILD"|"LINT"|"SECURITY_SCAN"|"OTHER";
  repository:string;
  ref:string;
  commit:string;
  tree:string;
  status:ExecutionStatus;
  command?:string;
  run_url?:string;
  started_at?:string;
  finished_at?:string;
  observed_at:string;
  output_digest?:string;
  limitations:string[];
}
export function recordExecution(input:Omit<ExecutionEvidence,"schema"|"observed_at"> & {observed_at?:string}):ExecutionEvidence{
  if(!input.execution_id || !input.authority || !input.commit || !input.tree)
    throw new Error("BLOCKED: execution evidence requires execution identity and exact artifact identity");
  return {...input,schema:"agent.execution-evidence/1",observed_at:input.observed_at ?? new Date().toISOString()};
}
export function bindExecutionToSnapshot(e:ExecutionEvidence,s:{repository:string;ref:string;commit:string;tree:string}){
  if(e.repository!==s.repository || e.commit!==s.commit || e.tree!==s.tree)
    throw new Error("MISMATCH: execution evidence is bound to a different repository snapshot");
  return e;
}
