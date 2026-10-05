export type EvidenceStatus =
  "OBSERVED"|"DERIVED"|"VERIFIED"|"NOT_FOUND"|"NOT_PRESENT"|"NOT_REACHABLE"|
  "NOT_OBSERVABLE"|"PARTIAL"|"STALE"|"MISMATCH"|"CONTRADICTED";

export interface EvidenceRecord {
  schema:"agent.evidence-record/1";
  evidence_id:string;
  status:EvidenceStatus;
  source:string;
  locator:string;
  scope:string;
  observation:string;
  snapshot_commit:string;
  extraction_method:string;
  limitations:string[];
}
function stableId(x:string){let h=2166136261;for(const c of x){h^=c.charCodeAt(0);h=Math.imul(h,16777619)}return (h>>>0).toString(16).padStart(8,"0")}
export function record(input:Omit<EvidenceRecord,"schema"|"evidence_id">):EvidenceRecord {
  if(!input.source||!input.scope||!input.snapshot_commit) throw new Error("BLOCKED: evidence scope/source/snapshot required");
  const canonical=JSON.stringify(input);
  return {schema:"agent.evidence-record/1",evidence_id:"fnv1a:"+stableId(canonical),...input};
}
