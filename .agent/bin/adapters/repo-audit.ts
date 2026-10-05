import {record} from "./evidence-record.ts";

export interface AuditFinding {
  id:string;
  category:"IDENTITY"|"STRUCTURE"|"CI"|"TEST"|"SECURITY"|"AUTHORITY"|"NEGATIVE_SEARCH";
  severity:"INFO"|"LOW"|"MEDIUM"|"HIGH"|"BLOCKER";
  observation:string;
  locator:string;
  status:"OBSERVED"|"NOT_FOUND"|"NOT_PRESENT"|"NOT_OBSERVABLE";
}

export interface AuditResult {
  schema:"agent.repo-audit/1";
  repository:string;
  ref:string;
  snapshot_commit:string;
  findings:AuditFinding[];
  evidence:any[];
  limitations:string[];
}

const patterns = [
  ["NEGATIVE_SEARCH","TODO","TODO markers"],
  ["NEGATIVE_SEARCH","FIXME","FIXME markers"],
  ["NEGATIVE_SEARCH","unsafe","unsafe-code surface"],
  ["NEGATIVE_SEARCH","skip","test/check bypass indicators"],
  ["NEGATIVE_SEARCH","disable","disabled-check indicators"],
  ["CI",".github/workflows","CI workflow directory"],
  ["TEST","test","test-related paths"],
  ["SECURITY","auth","authentication/authorization indicators"],
  ["AUTHORITY","verify","verification authority indicators"]
] as const;

export function audit(input:{
  repository:string;
  ref:string;
  snapshot_commit:string;
  files:Array<{path:string;content?:string}>;
}):AuditResult {
  if(!input.snapshot_commit) throw new Error("BLOCKED: audit requires exact snapshot commit");
  const findings:AuditFinding[]=[];
  const evidence:any[]=[];
  const paths=input.files.map(x=>x.path);
  const all=input.files.map(x=>x.content?x.path+"\n"+x.content:"").join("\n");

  for(const [category,needle,label] of patterns){
    const hits=input.files.filter(x=>
      x.path.toLowerCase().includes(needle.toLowerCase()) ||
      (x.content??"").toLowerCase().includes(needle.toLowerCase())
    );
    if(hits.length){
      for(const h of hits.slice(0,50)){
        const f:AuditFinding={
          id:"AUD-"+category+"-"+needle.toUpperCase()+"-"+findings.length.toString().padStart(3,"0"),
          category, severity:category==="SECURITY"?"MEDIUM":"INFO",
          observation:label+" observed in repository material",
          locator:h.path,status:"OBSERVED"
        };
        findings.push(f);
        evidence.push(record({
          status:"OBSERVED",source:"repo-deep-audit",locator:h.path,
          scope:input.repository+"@"+input.snapshot_commit,
          observation:f.observation,snapshot_commit:input.snapshot_commit,
          extraction_method:"deterministic path/content scan",limitations:[]
        }));
      }
    } else {
      const f:AuditFinding={
        id:"AUD-"+category+"-"+needle.toUpperCase()+"-"+findings.length.toString().padStart(3,"0"),
        category,severity:"INFO",observation:label+" not found by this scan",
        locator:"repository-wide scan",status:"NOT_FOUND"
      };
      findings.push(f);
      evidence.push(record({
        status:"NOT_FOUND",source:"repo-deep-audit",locator:"repository-wide scan",
        scope:input.repository+"@"+input.snapshot_commit,
        observation:f.observation,snapshot_commit:input.snapshot_commit,
        extraction_method:"deterministic path/content scan",limitations:[]
      }));
    }
  }

  if(!paths.length) throw new Error("BLOCKED: empty repository inventory");
  return {
    schema:"agent.repo-audit/1",repository:input.repository,ref:input.ref,
    snapshot_commit:input.snapshot_commit,findings,evidence,
    limitations:["This adapter performs static repository inspection only; it cannot establish remote CI execution or runtime behavior."]
  };
}
