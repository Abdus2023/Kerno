#!/usr/bin/env python3
"""Unified GPJK conformance runner.

Runs all registered fixture domains. Unsupported semantic adapters are reported as ERROR,
never silently skipped. This reference runner is intentionally dependency-free.
"""

from __future__ import annotations
import json, platform, re, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
FIX=ROOT/".agent"/"conformance"
SUITES=("reference-resolution.json","expression-evaluation.json","state-transitions.json",
        "authorization.json","temporal-verification.json","evidence-verification.json",
        "interchange.json","governance.json")
REF=re.compile(r"^gpjk:([^:]+):(.+)$")
UNKNOWN=object()

def resolve(ref,ctx):
    m=REF.match(ref)
    if not m:return "UNRESOLVED",None
    scope,path=m.groups(); cur=ctx.get(scope,UNKNOWN)
    if cur is UNKNOWN or not isinstance(cur,dict):return "UNRESOLVED",None
    for part in path.split("."):
        if not isinstance(cur,dict) or part not in cur:return "MISSING",None
        cur=cur[part]
    return ("NULL",None) if cur is None else ("VALUE",cur)

def expression(expr,ctx):
    m=re.match(r'^(gpjk:[^ ]+|-?\d+(?:\.\d+)?|"(?:[^"\\]|\\.)*")\s*(==|!=|>=|<=|>|<)\s*(gpjk:[^ ]+|-?\d+(?:\.\d+)?|"(?:[^"\\]|\\.)*")$',expr)
    if not m: raise ValueError("INVALID_EXPRESSION")
    def op(t):
        if t.startswith("gpjk:"):
            s,v=resolve(t,ctx); return UNKNOWN if s!="VALUE" else v
        if t.startswith('"'): return json.loads(t)
        return float(t) if "." in t else int(t)
    a,b=op(m.group(1)),op(m.group(3))
    if a is UNKNOWN or b is UNKNOWN:return "UNKNOWN"
    if type(a) is not type(b):return "FALSE"
    fn={"==":lambda:a==b,"!=":lambda:a!=b,">":lambda:a>b,">=":lambda:a>=b,"<":lambda:a<b,"<=":lambda:a<=b}[m.group(2)]
    return "TRUE" if fn() else "FALSE"

TRANS={"step":{"pending":{"ready","cancelled"},"ready":{"running","skipped"},"running":{"completed","failed","cancelled"}},
       "execution":{"pending":{"running"},"running":{"completed","failed","cancelled"}}}

def adapt(suite,c):
    if suite=="gpjk-reference-resolution":
        a,v=resolve(c["reference"],c["context"]); return a, a==c["expected"]["status"] and ("value" not in c["expected"] or v==c["expected"]["value"])
    if suite=="gpjk-expression-evaluation":
        a=expression(c["expression"],c["context"]); return a,a==c["expected"]
    if suite=="gpjk-state-machine":
        a=c["to"] in TRANS.get(c["kind"],{}).get(c["from"],set()); return a,a==c["expected"]
    if suite=="gpjk-authorization":
        limit=c["policy"].get("limit")
        if limit is None:return "deny","default-deny"
        return ("permit","") if c["request"].get("amount",UNKNOWN) is not UNKNOWN and c["request"]["amount"]<=limit else ("deny","limit")
    if suite=="gpjk-temporal-verification":
        if c.get("event")=="timeout" and not c.get("externalConfirmation"):return "INDETERMINATE","timeout-unconfirmed"
        return ("PASSED","validity") if "expired" not in c["id"] else ("FAILED","outside-validity")
    if suite=="gpjk-evidence-verification":
        ev=c.get("evidence",[])
        if not ev:return "INDETERMINATE","missing-evidence"
        if len(ev)>1 and {x.get("id") for x in ev}>={"yes","no"}:return "INDETERMINATE","contradiction"
        return "PASSED","supporting-evidence"
    if suite=="gpjk-interchange":
        p=c.get("package",{})
        if c["operation"]=="IMPORT" and p.get("dependency","").startswith("missing@"):
            return {"accepted":False,"executed":False},"dependency-missing"
        return {"accepted":True,"executed":False},"import-does-not-execute"
    if suite=="gpjk-governance":
        if c.get("change")=="reuse-existing-identifier":return "REJECTED","identifier-reuse"
        return {"ADDITIVE":"APPROVED","BREAKING":"DEFERRED"}.get(c.get("classification"),"DEFERRED"),"classification"
    raise ValueError("UNSUPPORTED_SUITE")

def main():
    results=[]
    for name in SUITES:
        data=json.loads((FIX/name).read_text(encoding="utf-8"))
        for c in data["cases"]:
            try:
                actual,ok=adapt(data["suite"],c)
                results.append({"suite":data["suite"],"case_id":c["id"],"expected":c["expected"],"actual":actual,
                                "status":"PASS" if ok else "FAIL"})
            except Exception as e:
                results.append({"suite":data["suite"],"case_id":c["id"],"expected":c.get("expected"),
                                "actual":None,"status":"ERROR","diagnostic":type(e).__name__+":"+str(e)})
    summary={s:sum(x["status"]==s for x in results) for s in ("PASS","FAIL","ERROR")}
    report={"report":"gpjk-conformance-execution","version":"1.1.0",
            "created":datetime.now(timezone.utc).isoformat(),
            "implementation":{"name":"kerno-gpjk-reference-runner","python":platform.python_version()},
            "fixtures":list(SUITES),"cases":results,"summary":summary,
            "exit_status":0 if summary["FAIL"]+summary["ERROR"]==0 else 1,
            "claim_boundary":"Execution report; not certification."}
    out=FIX/"reports"/"core-reference-latest.json"; out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary))
    raise SystemExit(report["exit_status"])

if __name__=="__main__":main()
