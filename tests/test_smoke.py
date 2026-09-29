import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def meta(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

def test_invariant_smoke(tmp_path):
    mod = load_module("invariant_testpack", ROOT / "src" / "invariant_testpack.py")
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("id,status,a,b\n1,ok,1,2\n2,ok,2,3\n", encoding="utf-8")
    profile = {
        "schema": "MRI_INVARIANT_PROFILE_R1",
        "bindings": {"input": meta(csv_path)},
        "adapter_contract": {
            "dataset_format": "csv",
            "column_map": {"id": "id", "status": "status", "a": "a", "b": "b"},
            "invariants": [
                {"id": "rows", "type": "row_count", "expected": 2},
                {"id": "ids", "type": "unique", "field": "id"},
                {"id": "status", "type": "domain", "field": "status", "allowed": ["ok"]},
                {"id": "chain", "type": "numeric_chain", "fields": ["a", "b"],
                 "direction": "ascending", "abs_tol": 0, "rel_tol": 0, "normalization": "none"}
            ]
        }
    }
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    result = mod.evaluate(profile_path)
    assert result["status"] == "PASS"

def test_differential_type_strict(tmp_path):
    mod = load_module("differential_validator", ROOT / "src" / "differential_validator.py")
    assert mod.strict_equal(1, 1) is True
    assert mod.strict_equal(1, 1.0) is False
    assert mod.strict_equal([1, "1", True], [1, "1", True]) is True
