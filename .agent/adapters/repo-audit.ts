#!/usr/bin/env -S deno run --allow-read --allow-run
const EXCLUDES=new Set([".git","node_modules","target",".venv","dist","build"]);
const SUSPICIOUS=/TODO|FIXME|XXX|HACK|unsafe|disable|bypass|skip|allowAll|permitAll|verify.*false/i;
async function walk(root:string):Promise<string[]>{
 const out:string[]=[];
 for await(const e of Deno.readDir(root)){
  if(EXCLUDES.has(e.name)) continue;
  const p=root+"/"+e.name;
  if(e.isDirectory) out.push(...await walk(p)); else out.push(p);
 }
 return out;
}
function digest(s:string){let h=2166136261;for(const c of s){h^=c.charCodeAt(0);h=Math.imul(h,16777619)}return (h>>>0).toString(16).padStart(8,"0")}
async function main(){
 const files=await walk(".");
 const evidence:any[]=[];
 const counts={files:files.length, suspicious:0};
 for(const path of files){
  let text="";
  try{text=await Deno.readTextFile(path)}catch{continue}
  const lines=text.split(/\r?\n/);
  for(let i=0;i<lines.length;i++) if(SUSPICIOUS.test(lines[i])){
   counts.suspicious++;
   evidence.push({status:"OBSERVED",kind:"suspicious-pattern",path,line:i+1,observation:lines[i].trim().slice(0,300)});
  }
 }
 const snapshot=new TextDecoder().decode((await new Deno.Command("git",{args:["rev-parse","HEAD"]}).output()).stdout).trim();
 const report={stage:"audit",status:"COMPLETE",authority:"local-filesystem+git",snapshot,scope:{root:".",file_count:files.length},counts,evidence,output_digest:digest(JSON.stringify({files,evidence,snapshot}))};
 console.log(JSON.stringify(report,null,2));
}
if(import.meta.main) await main();
