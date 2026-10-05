#!/usr/bin/env -S deno run --allow-run --allow-read
type Snapshot={repository:string;ref:string;commit:string;tree:string;parent:string|null;observed_at:string;source:string};
async function run(ref=Deno.args[0]??"HEAD"):Promise<Snapshot>{
  const cmd=new Deno.Command("git",{args:["rev-parse",ref]}); const commit=(await cmd.output()).stdout;
  if(!commit.length) throw new Error("BLOCKED: cannot resolve git ref");
  const out=new TextDecoder().decode(commit).trim();
  const tree=new TextDecoder().decode((await new Deno.Command("git",{args:["rev-parse",out+"^{tree}"]}).output()).stdout).trim();
  const parentText=new TextDecoder().decode((await new Deno.Command("git",{args:["rev-list","--parents","-n","1",out]}).output()).stdout).trim().split(/\s+/);
  const remote=new TextDecoder().decode((await new Deno.Command("git",{args:["config","--get","remote.origin.url"]}).output()).stdout).trim();
  const repository=remote.replace(/\.git$/,"").split("/").slice(-2).join("/");
  return {repository,ref,commit:out,tree,parent:parentText[1]??null,observed_at:new Date().toISOString(),source:"git"};
}
if(import.meta.main) console.log(JSON.stringify(await run(),null,2));
