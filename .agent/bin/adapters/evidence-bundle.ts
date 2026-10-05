import {inventory, type InventoryFile} from "./adapters/repository-inventory.ts";
import {audit} from "./adapters/repo-audit.ts";

export interface SnapshotInput {
  repository:string;
  ref:string;
  commit:string;
  tree:string;
  files:InventoryFile[];
}

export function buildEvidenceBundle(input:SnapshotInput){
  if(!input.commit || !input.tree) throw new Error("BLOCKED: exact commit and tree are required");
  const inv=inventory({
    repository:input.repository,ref:input.ref,
    snapshot_commit:input.commit,files:input.files
  });
  const auditResult=audit({
    repository:input.repository,ref:input.ref,
    snapshot_commit:input.commit,files:inv.files
  });
  const snapshot={
    schema:"agent.repository-snapshot/1",
    repository:input.repository,ref:input.ref,
    commit:input.commit,tree:input.tree
  };
  return {
    schema:"agent.evidence-bundle/1",
    snapshot,inventory:inv,
    audit:auditResult,
    evidence:auditResult.evidence
  };
}
