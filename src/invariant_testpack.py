#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,hashlib,json,math,os
from pathlib import Path

PROFILE_SCHEMA="MRI_INVARIANT_PROFILE_R1"
RESULT_SCHEMA="MRI_INVARIANT_RESULT_R1"
class Hold(RuntimeError): pass
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def meta(p):
    p=Path(p);b=p.read_bytes();return {"path":str(p),"bytes":len(b),"sha256":sha_bytes(b)}
def verify_binding(row,name):
    p=Path(row["path"])
    if not p.is_file(): raise Hold("HOLD_BINDING_MISSING:"+name)
    m=meta(p)
    if m["bytes"]!=int(row["bytes"]) or m["sha256"]!=row["sha256"]: raise Hold("HOLD_BINDING_MISMATCH:"+name)
    return m
def nonempty(v):return v is not None and str(v).strip()!=""
def resolve(cm,name):
    if name not in cm: raise Hold("HOLD_UNKNOWN_SEMANTIC:"+str(name))
    return cm[name]
def values(rows,col):
    return [(i,str(r.get(col,"")).strip()) for i,r in enumerate(rows) if nonempty(r.get(col))]
def idmap(rows,col):
    out={}
    for i,v in values(rows,col):
        if v in out: raise Hold("HOLD_DUPLICATE_ID:"+col+":"+v)
        out[v]=i
    return out
def close(a,b,abs_tol,rel_tol):return math.isclose(a,b,abs_tol=abs_tol,rel_tol=rel_tol)
def _coverage(total,eligible,checked,missing):
    return {"rows_total":total,"eligible":eligible,"checked":checked,"missing_required":missing}
def run_rule(rule,rows,cm):
    t=rule["type"]; rid=rule["id"]
    try:
      if t=="row_count":
        ok=len(rows)==int(rule["expected"]);detail={"actual":len(rows),"expected":int(rule["expected"]),"coverage":_coverage(len(rows),len(rows),len(rows),0)}
      elif t=="unique":
        c=resolve(cm,rule["field"]); vals=[v for _,v in values(rows,c)];ok=len(vals)==len(set(vals));detail={"field":c,"count":len(vals),"unique":len(set(vals)),"coverage":_coverage(len(rows),len(vals),len(vals),len(rows)-len(vals))}
      elif t=="subset":
        ca=resolve(cm,rule["child"]);cb=resolve(cm,rule["parent"]);a=set(idmap(rows,ca));b=set(idmap(rows,cb));ok=a<=b;detail={"child_only":sorted(a-b)[:20],"child_count":len(a),"parent_count":len(b),"coverage":{"child_nonempty":len(a),"parent_nonempty":len(b)}}
      elif t=="equal_set":
        ca=resolve(cm,rule["a"]);cb=resolve(cm,rule["b"]);a=set(idmap(rows,ca));b=set(idmap(rows,cb));ok=a==b;detail={"a_only":sorted(a-b)[:20],"b_only":sorted(b-a)[:20],"coverage":{"a_nonempty":len(a),"b_nonempty":len(b)}}
      elif t=="partition":
        pc=resolve(cm,rule["parent"]);parent=set(idmap(rows,pc));child_cols=[resolve(cm,x) for x in rule["children"]];children=[set(idmap(rows,c)) for c in child_cols]
        union=set().union(*children) if children else set(); overlap=set()
        for i in range(len(children)):
          for j in range(i+1,len(children)):overlap|=children[i]&children[j]
        allow_empty=bool(rule.get("allow_empty_basis",False));basis_known=bool(parent) or allow_empty
        ok=basis_known and union==parent and not overlap
        detail={"basis_semantic":rule["parent"],"basis_column":pc,"basis_count":len(parent),"allow_empty_basis":allow_empty,"basis_known":basis_known,
                "child_counts":{rule["children"][i]:len(children[i]) for i in range(len(children))},"union_count":len(union),"overlap":sorted(overlap)[:20],"missing":sorted(parent-union)[:20],"extra":sorted(union-parent)[:20]}
        if not basis_known: detail["reason"]="PARTITION_BASIS_EMPTY_WITHOUT_EXPLICIT_ALLOWANCE"
      elif t=="ordered":
        first=idmap(rows,resolve(cm,rule["first"]));later=idmap(rows,resolve(cm,rule["later"]));bad=[k for k,v in later.items() if k not in first or v<first[k]]
        ok=not bad;detail={"bad_ids":bad[:20],"later_count":len(later),"first_count":len(first)}
      elif t=="empty":
        bad={}
        for x in rule["fields"]:
          c=resolve(cm,x); n=len(values(rows,c))
          if n:bad[c]=n
        ok=not bad;detail={"nonempty":bad,"empty_requirement_explicit":True,"rows_total":len(rows)}
      elif t=="domain":
        c=resolve(cm,rule["field"]); allowed={str(x) for x in rule["allowed"]};vals=values(rows,c);bad=sorted({v for _,v in vals if v not in allowed})
        ok=not bad;detail={"bad_values":bad[:20],"allowed":sorted(allowed),"coverage":_coverage(len(rows),len(vals),len(vals),len(rows)-len(vals))}
      elif t=="count":
        c=resolve(cm,rule["field"]); n=len(values(rows,c));e=int(rule["expected"]);ok=n==e;detail={"actual":n,"expected":e,"rows_total":len(rows)}
      elif t=="open_tail":
        entries=set(idmap(rows,resolve(cm,rule["entries"])));term=set()
        for x in rule["terminals"]:term|=set(idmap(rows,resolve(cm,x)))
        actual=sorted(entries-term);expected=sorted(str(x) for x in rule["expected_open"])
        ok=actual==expected;detail={"actual_open":actual[:50],"expected_open":expected[:50],"entries_count":len(entries),"terminal_count":len(term)}
      elif t=="numeric_chain":
        cols=[resolve(cm,x) for x in rule["fields"]];direction=rule["direction"]
        abs_tol=float(rule["abs_tol"]);rel_tol=float(rule["rel_tol"]);bad=[];checked=0;missing=0
        for i,r in enumerate(rows):
          if not all(nonempty(r.get(c)) for c in cols):missing+=1;continue
          xs=[float(r[c]) for c in cols];checked+=1
          for a,b in zip(xs,xs[1:]):
            good=(a<b or close(a,b,abs_tol,rel_tol)) if direction=="ascending" else (a>b or close(a,b,abs_tol,rel_tol))
            if not good:bad.append({"row":i,"values":xs});break
        eligible=checked
        ok=(checked>0 and not bad);detail={"checked":checked,"bad":bad[:10],"direction":direction,"abs_tol":abs_tol,"rel_tol":rel_tol,"normalization":rule["normalization"],"coverage":_coverage(len(rows),eligible,checked,missing)}
        if checked==0: detail["reason"]="NO_COMPARABLE_ROWS_REQUIRED_INPUT_MISSING"
      elif t=="time_offset":
        l=resolve(cm,rule["lhs"]);rcol=resolve(cm,rule["rhs"]);off=int(rule["offset"]);bad=[];checked=0;missing=0
        for i,r in enumerate(rows):
          if not(nonempty(r.get(l)) and nonempty(r.get(rcol))):missing+=1;continue
          checked+=1
          lv=float(r[l]);rv=float(r[rcol])
          if not lv.is_integer() or not rv.is_integer():bad.append(i);continue
          if int(lv)!=int(rv)+off:bad.append(i)
        ok=(checked>0 and not bad);detail={"checked":checked,"bad_rows":bad[:20],"offset":off,"normalization":rule["normalization"],"coverage":_coverage(len(rows),checked,checked,missing)}
        if checked==0: detail["reason"]="NO_COMPARABLE_ROWS_REQUIRED_INPUT_MISSING"
      else: raise Hold("HOLD_RULE_UNSUPPORTED:"+t)
      return {"id":rid,"type":t,"status":"PASS" if ok else "HOLD","detail":detail}
    except Hold: raise
    except Exception as e: return {"id":rid,"type":t,"status":"HOLD","detail":{"error":repr(e)}}
def evaluate(profile_path):
    pp=Path(profile_path);pb=pp.read_bytes();p=json.loads(pb.decode("utf-8-sig"))
    if p.get("schema")!=PROFILE_SCHEMA: raise Hold("HOLD_PROFILE_SCHEMA")
    actual={k:verify_binding(v,k) for k,v in p["bindings"].items()}
    c=p["adapter_contract"]
    if c.get("dataset_format")!="csv":raise Hold("HOLD_DATASET_FORMAT_UNSUPPORTED")
    ip=Path(p["bindings"]["input"]["path"])
    with ip.open("r",encoding="utf-8-sig",newline="") as f:rows=list(csv.DictReader(f))
    cm=c["column_map"]
    header=list(rows[0].keys()) if rows else []
    missing=sorted({v for v in cm.values() if v not in header})
    if missing:raise Hold("HOLD_DATASET_COLUMNS_MISSING:"+",".join(missing))
    results=[run_rule(r,rows,cm) for r in c["invariants"]]
    status="PASS" if all(x["status"]=="PASS" for x in results) else "HOLD"
    digest=sha_bytes(json.dumps({"header":header,"results":results},sort_keys=True,separators=(",",":")).encode())
    return {"schema":RESULT_SCHEMA,"status":status,"profile":meta(pp),"bindings":actual,"row_count":len(rows),"rules":results,"state_digest":digest}
def write_out(out,obj):
    p=Path(out)
    if p.exists():raise Hold("HOLD_OUTPUT_EXISTS")
    p.parent.mkdir(parents=True,exist_ok=True)
    b=(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:os.write(fd,b);os.fsync(fd)
    finally:os.close(fd)
    return {"path":str(p),"bytes":len(b),"sha256":sha_bytes(b)}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--profile",required=True);ap.add_argument("--output")
    a=ap.parse_args();res=evaluate(a.profile)
    out=write_out(a.output,res) if a.output else None
    print(json.dumps({"status":res["status"],"result":res,"output":out},ensure_ascii=False,sort_keys=True))
    return 0 if res["status"]=="PASS" else 2
if __name__=="__main__":
    try: raise SystemExit(main())
    except Hold as e:
        print(json.dumps({"status":"HOLD","reason":str(e)},sort_keys=True));raise SystemExit(2)
