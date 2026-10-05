export interface RemoteFile {path:string; content:string; size:number}
export interface RemoteSnapshot {
  repository:string; ref:string; commit:string; tree:string; files:RemoteFile[];
  source:"github";
}
export interface GitHubSource {
  getRef(input:{repository:string;ref:string}):Promise<{commit:string;tree:string}>;
  getTree(input:{repository:string;tree:string}):Promise<Array<{path:string;type:string;size?:number}>>;
  getFile(input:{repository:string;commit:string;path:string}):Promise<string>;
}
export async function acquirePinnedSnapshot(source:GitHubSource,input:{repository:string;ref:string;commit:string;tree:string}):Promise<RemoteSnapshot>{
  const identity=await source.getRef({repository:input.repository,ref:input.ref});
  if(identity.commit!==input.commit || identity.tree!==input.tree)
    throw new Error("BLOCKED: remote ref does not match requested snapshot");
  const entries=await source.getTree({repository:input.repository,tree:input.tree});
  const files=entries.filter(e=>e.type==="blob").sort((a,b)=>a.path.localeCompare(b.path));
  const out:RemoteFile[]=[];
  for(const f of files){
    const content=await source.getFile({repository:input.repository,commit:input.commit,path:f.path});
    out.push({path:f.path,content,size:f.size ?? content.length});
  }
  return {repository:input.repository,ref:input.ref,commit:input.commit,tree:input.tree,files:out,source:"github"};
}
