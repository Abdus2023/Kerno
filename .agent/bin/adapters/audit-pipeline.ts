import {inventory, type InventoryFile} from "./adapters/repository-inventory.ts";
import {audit} from "./adapters/repo-audit.ts";

export interface AuditPipelineInput {
  repository:string;
  ref:string;
  snapshot_commit:string;
  files:InventoryFile[];
}

export function runAuditPipeline(input:AuditPipelineInput){
  const inv=inventory(input);
  const auditResult=audit({
    repository:input.repository,
    ref:input.ref,
    snapshot_commit:input.snapshot_commit,
    files:inv.files
  });
  return {inventory:inv,audit:auditResult};
}
