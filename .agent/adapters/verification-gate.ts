#!/usr/bin/env -S deno run --allow-read
interface Claim{claim_id:string;statement:string;scope:string;required_status:string;evidence_ids:string[]}
interface Evidence{evidence_id:string;status:string;scope:string}
function main(){
 const input=JSON.parse(Deno.args.length?Deno.args[0]:"{}") as {claim:Claim;evidence:Evidence[]};
 const ids=new Set(input.evidence.map(x=>x.evidence_id));
 const missing=input.claim.evidence_ids.filter(x=>!ids.has(x));
 const usable=input.evidence.filter(x=>input.claim.evidence_ids.includes(x.evidence_id)&&["VERIFIED","PROVED"].includes(x.status));
 const decision=missing.length||!usable.length?"BLOCKED":"PASS";
 console.log(JSON.stringify({decision,status:decision==="PASS"?"VERIFIED":"BLOCKED",claim_id:input.claim.claim_id,missing_evidence:missing,usable_evidence:usable.map(x=>x.evidence_id)},null,2));
}
if(import.meta.main) main();
