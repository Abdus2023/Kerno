import {acquirePinnedSnapshot, type GitHubSource} from "./adapters/github-acquisition.ts";
import {buildEvidenceBundle} from "./adapters/evidence-bundle.ts";

export async function acquireAndAudit(
  source:GitHubSource,
  input:{repository:string;ref:string;commit:string;tree:string}
){
  const remote=await acquirePinnedSnapshot(source,input);
  const bundle=buildEvidenceBundle({
    repository:remote.repository,
    ref:remote.ref,
    commit:remote.commit,
    tree:remote.tree,
    files:remote.files
  });
  return {acquired:remote,bundle};
}
