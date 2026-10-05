import type {ExecutionEvidence} from "./execution-evidence.ts";

export type ClaimDecision="PASS"|"FAIL"|"INDETERMINATE"|"BLOCKED";
export interface ExecutionClaim {
  claim_id:string;
  statement:string;
  snapshot:{repository:string;commit:string;tree:string};
  required_kind:"CI"|"TEST"|"BUILD"|"LINT"|"SECURITY_SCAN"|"OTHER";
  evidence_ids:string[];
}
export interface ExecutionVerification {
  claim_id:string;
  decision:ClaimDecision;
  matched_execution_ids:string[];
  reason:string;
}
export function verifyExecutionClaim(
  claim:ExecutionClaim,
  evidence:ExecutionEvidence[]
):ExecutionVerification{
  const scoped=evidence.filter(e=>
    claim.evidence_ids.includes(e.execution_id) &&
    e.repository===claim.snapshot.repository &&
    e.commit===claim.snapshot.commit &&
    e.tree===claim.snapshot.tree &&
    e.kind===claim.required_kind
  );
  if(scoped.length===0) return {claim_id:claim.claim_id,decision:"BLOCKED",matched_execution_ids:[],reason:"No execution evidence matches the exact required artifact and execution kind."};
  if(scoped.some(e=>e.status==="PASSED")) return {claim_id:claim.claim_id,decision:"PASS",matched_execution_ids:scoped.filter(e=>e.status==="PASSED").map(e=>e.execution_id),reason:"A matching execution authority reports PASSED."};
  if(scoped.some(e=>["FAILED","CANCELLED","TIMED_OUT"].includes(e.status))) return {claim_id:claim.claim_id,decision:"FAIL",matched_execution_ids:scoped.map(e=>e.execution_id),reason:"Matching execution evidence does not establish successful execution."};
  return {claim_id:claim.claim_id,decision:"INDETERMINATE",matched_execution_ids:scoped.map(e=>e.execution_id),reason:"Execution exists but its result is not observable as a successful run."};
}
