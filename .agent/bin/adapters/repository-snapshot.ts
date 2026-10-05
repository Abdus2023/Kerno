export interface Snapshot {
  schema:"agent.repository-snapshot/1";
  repository:string;
  ref:string;
  commit:string;
  tree:string;
  parent?:string;
  observed_at:string;
  source:string;
}
export function createSnapshot(input:{repository:string;ref:string;commit:string;tree:string;parent?:string;source:string}):Snapshot {
  if(!input.commit || !input.tree) throw new Error("BLOCKED: exact commit and tree are required");
  return {schema:"agent.repository-snapshot/1",...input,observed_at:new Date().toISOString()};
}
