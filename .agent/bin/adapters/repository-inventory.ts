export interface InventoryFile {path:string;size?:number;content?:string}
export interface Inventory {
  schema:"agent.repository-inventory/1";
  repository:string;
  ref:string;
  snapshot_commit:string;
  files:InventoryFile[];
  directories:string[];
  generated_at:string;
}
export function inventory(input:{repository:string;ref:string;snapshot_commit:string;files:InventoryFile[]}):Inventory {
  if(!input.snapshot_commit) throw new Error("BLOCKED: inventory requires exact snapshot commit");
  const paths=input.files.map(x=>x.path).sort();
  const dirs=new Set<string>();
  for(const p of paths){
    const parts=p.split("/");
    for(let i=1;i<parts.length;i++) dirs.add(parts.slice(0,i).join("/"));
  }
  return {
    schema:"agent.repository-inventory/1",
    repository:input.repository,ref:input.ref,snapshot_commit:input.snapshot_commit,
    files:input.files.slice().sort((a,b)=>a.path.localeCompare(b.path)),
    directories:[...dirs].sort(),generated_at:new Date().toISOString()
  };
}
