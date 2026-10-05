import type {EvidenceRecord} from "./evidence-record.ts";
export type Decision="PASS"|"FAIL"|"INDETERMINATE"|"BLOCKED";
export interface Claim {claim_id:string;statement:string;scope:string;required_status:"PROVED"|"VERIFIED";evidence_ids:string[]}
export function verify(claim:Claim,evidence:EvidenceRecord[]):{decision:Decision;status:string;reasons:string[];missing:string[]} {
  const byId=new Map(evidence.map(x=>[x.evidence_id,x]));
  const missing=claim.evidence_ids.filter(id=>!byId.has(id));
  if(missing.length) return {decision:"BLOCKED",status:"BLOCKED",reasons:["required evidence is missing"],missing};
  const selected=claim.evidence_ids.map(id=>byId.get(id)!);
  if(selected.some(x=>x.status==="CONTRADICTED"||x.status==="MISMATCH"||x.status==="STALE"))
    return {decision:"FAIL",status:"BLOCKED",reasons:["evidence contradicts or does not match claim scope"],missing:[]};
  if(claim.required_status==="VERIFIED" && selected.some(x=>x.status!=="VERIFIED"))
    return {decision:"INDETERMINATE",status:"PARTIALLY_VERIFIED",reasons:["evidence exists but does not establish VERIFIED"],missing:[]};
  return {decision:"PASS",status:claim.required_status,reasons:["all referenced evidence satisfies required status"],missing:[]};
}
