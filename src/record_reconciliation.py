# SPDX-License-Identifier: Apache-2.0
"""Retain all record-matching candidates under explicit comparison rules.

One candidate is not proof of original identity or a one-to-one assignment.
Time-floor rules are declared lossy projections, not timestamp equality.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re


_DECIMAL_TEXT = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_INTEGER_TEXT = re.compile(r"-?[0-9]+\Z")
_UNIT_NS = {"s": 1_000_000_000, "ms": 1_000_000, "us": 1_000, "ns": 1}
_BASE_FIELDS = {"left_field", "right_field", "mode"}
_TIME_FIELDS = {"left_unit", "right_unit", "left_semantics", "right_semantics"}


def _compile_rules(rules):
    compiled = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"rule {index}: expected a dict")
        mode = rule.get("mode")
        if mode not in ("exact_text", "decimal_numeric", "integer_time_floor"):
            raise ValueError(f"rule {index}: unsupported mode")
        required = _BASE_FIELDS | (_TIME_FIELDS if mode == "integer_time_floor" else set())
        if set(rule) != required:
            raise ValueError(f"rule {index}: missing or unsupported fields")
        for field in ("left_field", "right_field"):
            if not isinstance(rule[field], str) or not rule[field].strip():
                raise ValueError(f"rule {index}: invalid {field}")
        divisor = 1
        if mode == "integer_time_floor":
            for field in ("left_unit", "right_unit"):
                if not isinstance(rule[field], str) or rule[field] not in _UNIT_NS:
                    raise ValueError(f"rule {index}: unsupported {field}")
            for field in ("left_semantics", "right_semantics"):
                if not isinstance(rule[field], str) or not rule[field].strip():
                    raise ValueError(f"rule {index}: invalid {field}")
            if rule["left_semantics"] != rule["right_semantics"]:
                raise ValueError(f"rule {index}: incompatible declared time semantics")
            left_tick, right_tick = _UNIT_NS[rule["left_unit"]], _UNIT_NS[rule["right_unit"]]
            if right_tick > left_tick:
                raise ValueError(f"rule {index}: right time must be at least as fine as left time")
            divisor = left_tick // right_tick
        compiled.append((deepcopy(rule), divisor))
    if not compiled:
        raise ValueError("at least one explicit comparison rule is required")
    return compiled


def _integer(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and _INTEGER_TEXT.fullmatch(value) is not None:
        return int(value)
    raise ValueError("time values must be integers or plain integer strings, not floats/bools")


def _value(value, mode):
    if mode == "exact_text":
        if not isinstance(value, str):
            raise ValueError("exact_text requires a string")
        return value
    if mode == "integer_time_floor":
        return _integer(value)
    if not isinstance(value, str) or _DECIMAL_TEXT.fullmatch(value) is None:
        raise ValueError("decimal_numeric requires decimal text")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal text") from exc
    if not number.is_finite():
        raise ValueError("decimal_numeric requires a finite value")
    # Direct equality/hash retain arbitrary precision without normalize/quantize.
    return number


def _prepare(rows, side, compiled):
    prepared = []
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{side} row {index}: expected a dict")
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or not row_id.strip():
            raise ValueError(f"{side} row {index}: row_id must be a nonempty string")
        if row_id in seen:
            raise ValueError(f"{side} row {index}: duplicate row_id")
        seen.add(row_id)
        key = []
        for rule, divisor in compiled:
            field = rule[side + "_field"]
            if field not in row:
                raise ValueError(f"{side} row {index}: missing mapped field")
            try:
                value = _value(row[field], rule["mode"])
            except ValueError as exc:
                raise ValueError(f"{side} row {index}: {exc}") from exc
            if side == "right" and rule["mode"] == "integer_time_floor":
                value //= divisor
            key.append(value)
        prepared.append((deepcopy(row), tuple(key)))
    return prepared


def match_records(left_rows, right_rows, rules):
    """Return all candidates under explicit field/value rules, never pick a tie.

    Rules map left_field to right_field with exact_text, decimal_numeric or
    integer_time_floor. The last mode requires explicit units (s/ms/us/ns) and
    matching declared time semantics; only right-finer to left-coarser floor is
    allowed. Input row_id strings are unique on each side, not coerced.

    Original rows/rules are copied into output. Candidate IDs are sorted for
    reproducibility. UNIQUE means one supplied candidate after these rules,
    not a proven native identity or a bijection; inspect shared_candidates.
    """
    compiled = _compile_rules(rules)
    left = _prepare(left_rows, "left", compiled)
    right = _prepare(right_rows, "right", compiled)
    index = {}
    for row, key in right:
        index.setdefault(key, []).append(row)
    for candidates in index.values():
        candidates.sort(key=lambda row: row["row_id"])

    matches = []
    shared = {}
    for row, key in left:
        candidates = index.get(key, [])
        details = []
        for candidate in candidates:
            comparisons = []
            for rule_number, (rule, divisor) in enumerate(compiled):
                left_value, right_value = row[rule["left_field"]], candidate[rule["right_field"]]
                comparison = {
                    "rule_index": rule_number,
                    "literal_equal": type(left_value) is type(right_value) and left_value == right_value,
                }
                if rule["mode"] == "integer_time_floor":
                    comparison["time_projection"] = {
                        "operation": "floor_right_to_left_unit",
                        "divisor": divisor,
                        "potential_precision_loss": divisor > 1,
                        "discarded_right_ticks": _integer(right_value) % divisor,
                    }
                comparisons.append(comparison)
            details.append({"right_id": candidate["row_id"], "comparisons": comparisons})
            shared.setdefault(candidate["row_id"], []).append(row["row_id"])
        status = "UNMATCHED" if not candidates else "UNIQUE" if len(candidates) == 1 else "AMBIGUOUS"
        matches.append({
            "left_id": row["row_id"],
            "status": status,
            "candidate_ids": [candidate["row_id"] for candidate in candidates],
            "candidate_details": details,
        })

    return {
        "left_rows": [row for row, _ in left],
        "right_rows": [row for row, _ in right],
        "rules": [rule for rule, _ in compiled],
        "matches": matches,
        "shared_candidates": [
            {"right_id": row_id, "left_ids": sorted(left_ids)}
            for row_id, left_ids in sorted(shared.items()) if len(left_ids) > 1
        ],
    }
