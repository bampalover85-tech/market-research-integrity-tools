#!/usr/bin/env python3
from __future__ import annotations
import argparse,collections,hashlib,json,math,os
from pathlib import Path

SPEC_SCHEMA="MRI_DIFFERENTIAL_SPEC_R1"
RESULT_SCHEMA="MRI_DIFFERENTIAL_RESULT_R1"
MODES={"exact","numeric_close","set_equal","ordered_equal"}
class Hold(RuntimeError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def meta(p):
 p=Path(p);b=p.read_bytes();return {"path":str(p),"bytes":len(b),"sha256":sha(b)}
def verify(row,label):
 p=Path(row["path"])
 if not p.is_file():raise Hold("HOLD_BINDING_MISSING:"+label)
 m=meta(p)
 if m["bytes"]!=int(row["bytes"]) or m["sha256"]!=row["sha256"]:raise Hold("HOLD_BINDING_MISMATCH:"+label)
 return p,m
def get(obj,path):
 cur=obj
 for seg in path.split("."):
  if isinstance(cur,list):
   try:cur=cur[int(seg)]
   except Exception:raise Hold("HOLD_PATH:"+path)
  elif isinstance(cur,dict) and seg in cur:cur=cur[seg]
  else:raise Hold("HOLD_PATH:"+path)
 return cur

def strict_equal(a,b):
 if type(a) is not type(b): return False
 if isinstance(a,dict):
  return list(a.keys())==list(b.keys()) and all(strict_equal(a[k],b[k]) for k in a)
 if isinstance(a,list): return len(a)==len(b) and all(strict_equal(x,y) for x,y in zip(a,b))
 return a==b

def typed_token(v):
 if v is None:return ("null","null")
 if isinstance(v,bool):return ("bool","true" if v else "false")
 if isinstance(v,int) and not isinstance(v,bool):return ("int",str(v))
 if isinstance(v,float):return ("float",repr(v))
 if isinstance(v,str):return ("str",v)
 if isinstance(v,list):return ("list",json.dumps([[*typed_token(x)] for x in v],ensure_ascii=False,separators=(",",":")))
 if isinstance(v,dict):
  items=[[str(k),[*typed_token(val)]] for k,val in v.items()]
  return ("dict",json.dumps(items,ensure_ascii=False,separators=(",",":")))
 raise Hold("HOLD_UNSUPPORTED_JSON_VALUE_TYPE:"+type(v).__name__)

def validate_row(row,i):
 if not isinstance(row,dict):raise Hold(f"HOLD_COMPARISON_INVALID:{i}")
 mode=row.get("mode")
 if mode not in MODES:raise Hold("HOLD_MODE:"+str(mode))
 for k in ("lhs_path","rhs_path"):
  if not isinstance(row.get(k),str) or not row[k]:raise Hold(f"HOLD_COMPARISON_KEY:{i}:{k}")
 if "id" in row and (not isinstance(row["id"],str) or not row["id"]):raise Hold(f"HOLD_COMPARISON_KEY:{i}:id")
 if mode=="numeric_close":
  for k in ("abs_tol","rel_tol"):
   v=row.get(k)
   if isinstance(v,bool) or not isinstance(v,(int,float)) or v<0:raise Hold(f"HOLD_COMPARISON_TOLERANCE:{i}:{k}")
  if row.get("normalization")!="none":raise Hold(f"HOLD_COMPARISON_NORMALIZATION:{i}")
 if mode=="set_equal":
  if row.get("normalization")!="none":raise Hold(f"HOLD_COMPARISON_NORMALIZATION:{i}")
  if row.get("duplicate_policy") not in ("discard","preserve"):raise Hold(f"HOLD_COMPARISON_DUPLICATE_POLICY:{i}")
 if mode in ("exact","ordered_equal") and row.get("normalization","none")!="none":
  raise Hold(f"HOLD_COMPARISON_NORMALIZATION:{i}")

def cmp(mode,a,b,row):
 if mode=="exact":return strict_equal(a,b),{"lhs":a,"rhs":b,"type_match":type(a) is type(b),"normalization":"none"}
 if mode=="ordered_equal":
  if not isinstance(a,list) or not isinstance(b,list):raise Hold("HOLD_ORDERED_EQUAL_REQUIRES_LIST")
  return strict_equal(a,b),{"lhs":a,"rhs":b,"normalization":"none"}
 if mode=="set_equal":
  if not isinstance(a,list) or not isinstance(b,list):raise Hold("HOLD_SET_EQUAL_REQUIRES_LIST")
  aa=[typed_token(x) for x in a];bb=[typed_token(x) for x in b];policy=row["duplicate_policy"]
  if policy=="discard":ok=set(aa)==set(bb);lhs=sorted(set(aa));rhs=sorted(set(bb))
  else:ok=collections.Counter(aa)==collections.Counter(bb);lhs=sorted(collections.Counter(aa).items());rhs=sorted(collections.Counter(bb).items())
  return ok,{"lhs_typed":lhs,"rhs_typed":rhs,"duplicate_policy":policy,"normalization":"none"}
 if mode=="numeric_close":
  if isinstance(a,bool) or isinstance(b,bool) or not isinstance(a,(int,float)) or not isinstance(b,(int,float)):
   raise Hold("HOLD_NUMERIC_CLOSE_REQUIRES_JSON_NUMBER")
  at=float(row["abs_tol"]);rt=float(row["rel_tol"])
  ok=math.isclose(float(a),float(b),abs_tol=at,rel_tol=rt)
  return ok,{"lhs":a,"rhs":b,"lhs_type":type(a).__name__,"rhs_type":type(b).__name__,"abs_tol":at,"rel_tol":rt,"normalization":"none"}
 raise Hold("HOLD_MODE:"+str(mode))
def write_out(p,obj):
 p=Path(p)
 if p.exists():raise Hold("HOLD_OUTPUT_EXISTS")
 p.parent.mkdir(parents=True,exist_ok=True)
 b=(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
 try:os.write(fd,b);os.fsync(fd)
 finally:os.close(fd)
 return {"path":str(p),"bytes":len(b),"sha256":sha(b)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--spec",required=True);ap.add_argument("--output")
 a=ap.parse_args();sp=Path(a.spec);sb=sp.read_bytes();spec=json.loads(sb.decode("utf-8-sig"))
 if spec.get("schema")!=SPEC_SCHEMA:raise Hold("HOLD_SPEC_SCHEMA")
 lp,lm=verify(spec["lhs"],"lhs");rp,rm=verify(spec["rhs"],"rhs")
 lhs=json.loads(lp.read_text(encoding="utf-8-sig"));rhs=json.loads(rp.read_text(encoding="utf-8-sig"))
 rows=[]
 comps=spec.get("comparisons")
 if not isinstance(comps,list) or not comps:raise Hold("HOLD_COMPARISONS_MISSING")
 seen=set()
 for i,row in enumerate(comps):
  validate_row(row,i);rid=row.get("id",str(i))
  if rid in seen:raise Hold("HOLD_COMPARISON_ID_DUPLICATE:"+rid)
  seen.add(rid)
  mode=row["mode"];av=get(lhs,row["lhs_path"]);bv=get(rhs,row["rhs_path"]);ok,detail=cmp(mode,av,bv,row)
  rows.append({"id":rid,"mode":mode,"status":"PASS" if ok else "HOLD","detail":detail})
 status="PASS" if all(x["status"]=="PASS" for x in rows) else "HOLD"
 result={"schema":RESULT_SCHEMA,"status":status,"spec":meta(sp),"lhs":lm,"rhs":rm,"comparisons":rows}
 om=write_out(a.output,result) if a.output else None
 print(json.dumps({"status":status,"result":result,"output":om},ensure_ascii=False,sort_keys=True))
 return 0 if status=="PASS" else 2
if __name__=="__main__":
 try:raise SystemExit(main())
 except Hold as e:
  print(json.dumps({"status":"HOLD","reason":str(e)},sort_keys=True));raise SystemExit(2)
