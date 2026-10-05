#!/usr/bin/env python3
"""Deterministic GPJK core conformance runner.

Runs the first three fixture domains without third-party dependencies:
reference resolution, expression comparison, and lifecycle transitions.
The report records execution facts; it does not grant certification.
"""

from __future__ import annotations
import json, platform, re, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
FIX=ROOT/".agent"/"conformance"
REF=re.compile(r"^gpjk:([^:]+):(.+)$")
OPS={">":lambda a,b:a>b,">=":lambda a,b:a>=b,"<":lambda a,b:a<b,
     "<=":lambda a,b:a<=b,"==":lambda a,b:a==b,"!=":lambda a,b:a!=b}
TRANS={
 "step":{"pending":{"ready","cancelled"},"ready":{"running","skipped"},
         "running":{"completed","failed","cancelled"}},
 "execution":{"pending":{"running"},"running":{"completed","failed","cancelled"}}
}
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

def operand(tok,ctx):
    if tok.startswith("gpjk:"):
        s,v=resolve(tok,ctx); return UNKNOWN if s!="VALUE" else v
    if tok.startswith('"'): return json.loads(tok)
    return float(tok) if "." in tok else int(tok)

EXPR=re.compile(r'^(gpjk:[^ ]+|-?d+(?:.d+)?|"(?:[^"\\]|\\.)*")\s*(==|!=|>=|<=|>|<)\s*(gpjk:[^ ]+|-?d+(?:.d+)?|"(?:[^"\\]|\\.)*")$')
def evaluate(expr,ctx):
    m=EXPR.match(expr)
    if not m: raise ValueError("INVALID_EXPRESSION")
    a,op,b=operand(m.group(1),ctx),m.group(2),operand(m.group(3),ctx)
    if a is UNKNOWN or b is UNKNOWN:return "UNKNOWN"
    if type(a) is not type(b):return "FALSE"
    return "TRUE" if OPS[op](a,b) else "FALSE"

def run_case(suite,c):
    if suite=="gpjk-reference-resolution":
        actual,val=resolve(c["reference"],c["context"])
        ok=actual==c["expected"]["status"] and ("value" not in c["expected"] or val==c["expected"]["value"])
        return actual,ok
    if suite=="gpjk-expression-evaluation":
        actual=evaluate(c["expression"],c["context"]); return actual,actual==c["expected"]
    if suite=="gpjk-state-machine":
        actual=c["to"] in TRANS.get(c["kind"],{}).get(c["from"],set())
        return actual,actual==c["expected"]
    return "UNSUPPORTED",False

def main():
    suites=["reference-resolution.json","expression-evaluation.json","state-transitions.json"]
    cases=[]; errors=0
    for name in suites:
        data=json.loads((FIX/name).read_text())
        for c in data["cases"]:
            try:
                actual,ok=run_case(data["suite"],c)
                cases.append({"suite":data["suite"],"case_id":c["id"],
                              "expected":c.get("expected"),"actual":actual,
                              "status":"PASS" if ok else "FAIL"})
                errors += not ok
            except Exception as e:
                cases.append({"suite":data["suite"],"case_id":c["id"],
                              "expected":c.get("expected"),"actual":None,
                              "status":"ERROR","diagnostic":type(e).__name__+":"+str(e)})
                errors += 1
    report={"report":"gpjk-conformance-execution","version":"1.0.0",
            "created":datetime.now(timezone.utc).isoformat(),
            "implementation":{"name":"kerno-reference-fixture-runner","python":platform.python_version()},
            "fixtures":suites,"cases":cases,
            "summary":{"total":len(cases),"passed":sum(x["status"]=="PASS" for x in cases),
                       "failed":sum(x["status"]=="FAIL" for x in cases),
                       "errors":sum(x["status"]=="ERROR" for x in cases)},
            "exit_status":0 if not errors else 1,
            "claim_boundary":"Execution report; not certification."}
    out=FIX/"reports"/"core-reference-latest.json"; out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report["summary"]))
    raise SystemExit(report["exit_status"])
if __name__=="__main__": main()
