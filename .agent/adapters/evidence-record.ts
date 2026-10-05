#!/usr/bin/env -S deno run --allow-read
function digest(s:string){let h=2166136261;for(const c of s){h^=c.charCodeAt(0);h=Math.imul(h,16777619)}return (h>>>0).toString(16).padStart(8,"0")}
const raw=Deno.args[0]; if(!raw) throw new Error("BLOCKED: evidence input required");
const x=JSON.parse(raw);
if(!x.source||!x.scope||!x.observation) throw new Error("BLOCKED: source, scope and observation are required");
const normalized={source:x.source,locator:x.locator??null,scope:x.scope,observation:x.observation,snapshot:x.snapshot??null,extraction_method:x.extraction_method??"direct"};
const id="fnv1a:"+digest(JSON.stringify(normalized));
console.log(JSON.stringify({evidence_id:id,status:x.status??"OBSERVED",...normalized},null,2));
