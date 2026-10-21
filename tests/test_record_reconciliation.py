# SPDX-License-Identifier: Apache-2.0
"""Synthetic candidate-set tests, not source-identity or market validation."""

from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path

import pytest

from src.record_reconciliation import match_records


def rule(mode="exact_text", **options):
    return {"left_field": "value", "right_field": "raw_value", "mode": mode, **options}


def time_rule(**options):
    return rule("integer_time_floor", **{
        "left_unit": "ms", "right_unit": "us",
        "left_semantics": "synthetic_capture_clock",
        "right_semantics": "synthetic_capture_clock", **options,
    })


def left(value, row_id="synthetic-left", **extras):
    return {"row_id": row_id, "value": value, **extras}


def right(value, row_id="synthetic-right", **extras):
    return {"row_id": row_id, "raw_value": value, **extras}


def one(left_value, right_value, comparison):
    return match_records([left(left_value)], [right(right_value)], [comparison])["matches"][0]


def test_no_implicit_numeric_or_text_normalization():
    for a, b in [("1.0", "1.00"), ("TEST", "test"), ("TEST", " TEST"), ("01", "1")]:
        assert one(a, b, rule())["status"] == "UNMATCHED"
    assert one("", "", rule())["status"] == "UNIQUE"


@pytest.mark.parametrize("a,b", [("1.0", "1.00"), ("1e2", "100"),
                                  ("-0.00", "0"), ("-12.30", "-12.3")])
def test_numeric_equality_preserves_lexical_difference(a, b):
    result = match_records([left(a)], [right(b)], [rule("decimal_numeric")])
    match = result["matches"][0]
    assert match["status"] == "UNIQUE"
    assert match["candidate_details"][0]["comparisons"][0]["literal_equal"] is False
    assert result["left_rows"][0]["value"] == a
    assert result["right_rows"][0]["raw_value"] == b


def test_arbitrary_precision_equality_does_not_use_decimal_context_rounding():
    a = "1.00000000000000000000000000000000001"
    b = "1.00000000000000000000000000000000002"
    with localcontext() as ctx:
        ctx.prec = 2
        assert one(a, b, rule("decimal_numeric"))["status"] == "UNMATCHED"
        assert one(a, a + "00", rule("decimal_numeric"))["status"] == "UNIQUE"
        assert one("9e1000", "90e999", rule("decimal_numeric"))["status"] == "UNIQUE"


@pytest.mark.parametrize("value", [None, True, False, 1, 1.0, Decimal("1"), "", " ",
                                  "NaN", "sNaN", "Infinity", "-Infinity", "1_0",
                                  " 1", "1 ", "１", ".5", "1.", "+1"])
@pytest.mark.parametrize("side", ["left", "right"])
def test_invalid_numeric_values_fail_instead_of_silently_dropping_rows(value, side):
    rows = ([left(value)], [right("1")]) if side == "left" else ([left("1")], [right(value)])
    with pytest.raises(ValueError, match="decimal"):
        match_records(*rows, [rule("decimal_numeric")])


@pytest.mark.parametrize("value", [None, 1, 1.0, True])
def test_exact_text_rejects_nontext(value):
    with pytest.raises(ValueError, match="requires a string"):
        one(value, "1", rule())


def test_time_floor_retains_ambiguous_candidates_and_exposes_projection():
    rows = [right(100_999, "synthetic-b"), right(100_001, "synthetic-a")]
    result = match_records([left(100)], rows, [time_rule()])
    match = result["matches"][0]
    assert match["status"] == "AMBIGUOUS"
    assert match["candidate_ids"] == ["synthetic-a", "synthetic-b"]
    details = [item["comparisons"][0]["time_projection"] for item in match["candidate_details"]]
    assert details == [
        {"operation": "floor_right_to_left_unit", "divisor": 1000,
         "potential_precision_loss": True, "discarded_right_ticks": 1},
        {"operation": "floor_right_to_left_unit", "divisor": 1000,
         "potential_precision_loss": True, "discarded_right_ticks": 999},
    ]
    assert result["right_rows"] == rows


@pytest.mark.parametrize("left_unit,right_unit,factor", [
    ("s", "s", 1), ("s", "ms", 1000), ("s", "us", 1_000_000), ("s", "ns", 1_000_000_000),
    ("ms", "ms", 1), ("ms", "us", 1000), ("ms", "ns", 1_000_000),
    ("us", "us", 1), ("us", "ns", 1000), ("ns", "ns", 1),
])
def test_only_declared_finer_to_coarser_integer_projection(left_unit, right_unit, factor):
    match = one("123", str(123 * factor), time_rule(left_unit=left_unit, right_unit=right_unit))
    assert match["status"] == "UNIQUE"
    projection = match["candidate_details"][0]["comparisons"][0]["time_projection"]
    assert projection["divisor"] == factor
    assert projection["potential_precision_loss"] is (factor > 1)
    assert projection["discarded_right_ticks"] == 0


def test_floor_is_not_nearest_rounding_including_negative_ticks():
    assert one(100, 100_999, time_rule())["status"] == "UNIQUE"
    assert one(101, 100_999, time_rule())["status"] == "UNMATCHED"
    assert one(-1, -1, time_rule())["status"] == "UNIQUE"
    assert one(0, -1, time_rule())["status"] == "UNMATCHED"


def test_large_integer_ticks_are_not_coerced_through_float():
    coarse = 10**35 + 7
    assert one(str(coarse), str(coarse * 1000 + 123), time_rule())["status"] == "UNIQUE"
    assert one(str(coarse + 1), str(coarse * 1000 + 123), time_rule())["status"] == "UNMATCHED"


@pytest.mark.parametrize("value", [True, False, 1.0, "1.0", "1e3", None, " 1", "+1", "1_000"])
@pytest.mark.parametrize("side", ["left", "right"])
def test_invalid_integer_time_is_rejected(value, side):
    args = (value, 1000) if side == "left" else (1, value)
    with pytest.raises(ValueError, match="time values"):
        one(*args, time_rule())


@pytest.mark.parametrize("options", [
    {"left_unit": "us", "right_unit": "ms"}, {"left_unit": "ns", "right_unit": "s"},
    {"left_unit": "minutes"}, {"right_unit": 1000},
    {"left_semantics": "event_clock", "right_semantics": "receipt_clock"},
    {"left_semantics": ""}, {"right_semantics": None},
])
def test_incompatible_units_or_semantics_rejected(options):
    with pytest.raises(ValueError):
        one(1, 1000, time_rule(**options))


def test_unique_per_left_does_not_hide_shared_candidate_collision():
    result = match_records([left("1.0", "synthetic-left-a"), left("1.00", "synthetic-left-b")],
                           [right("1")], [rule("decimal_numeric")])
    assert [row["status"] for row in result["matches"]] == ["UNIQUE", "UNIQUE"]
    assert result["shared_candidates"] == [{
        "right_id": "synthetic-right", "left_ids": ["synthetic-left-a", "synthetic-left-b"]}]


def test_equal_values_with_distinct_ids_are_never_deduplicated_or_arbitrarily_selected():
    rows = [right("x", "synthetic-b"), right("x", "synthetic-a")]
    a = match_records([left("x")], rows, [rule()])
    b = match_records([left("x")], reversed(rows), [rule()])
    assert a["matches"] == b["matches"]
    assert a["matches"][0]["status"] == "AMBIGUOUS"
    assert a["matches"][0]["candidate_ids"] == ["synthetic-a", "synthetic-b"]


def test_explicit_source_stream_instrument_mapping_prevents_cross_scope_matches():
    scope_rules = [{"left_field": key, "right_field": key, "mode": "exact_text"}
                   for key in ("source", "stream", "instrument")]
    query = left("x", source="synthetic-source", stream="demo-feed", instrument="TEST")
    good = right("x", source="synthetic-source", stream="demo-feed", instrument="TEST")
    rows = [good]
    for field in ("source", "stream", "instrument"):
        rows.append({**good, "row_id": "synthetic-other-" + field, field: "other"})
    result = match_records([query], rows, [rule(), *scope_rules])
    assert result["matches"][0]["candidate_ids"] == ["synthetic-right"]
    # Rules alone define the key: omitting scope checks is deliberately not repaired.
    assert match_records([query], rows, [rule()])["matches"][0]["status"] == "AMBIGUOUS"


@pytest.mark.parametrize("side", ["left", "right"])
def test_missing_mapped_field_or_duplicate_id_is_rejected(side):
    missing = {"row_id": "synthetic-row"}
    with pytest.raises(ValueError, match="missing mapped field"):
        match_records([missing] if side == "left" else [left("x")],
                      [missing] if side == "right" else [right("x")], [rule()])
    with pytest.raises(ValueError, match="duplicate row_id"):
        match_records([left("x"), left("y")] if side == "left" else [left("x")],
                      [right("x"), right("y")] if side == "right" else [right("x")], [rule()])


@pytest.mark.parametrize("row_id", [None, "", " ", 1, 1.0, True])
def test_ids_are_opaque_nonempty_strings_not_coerced(row_id):
    with pytest.raises(ValueError, match="row_id"):
        match_records([left("x", row_id)], [right("x")], [rule()])


@pytest.mark.parametrize("rules", [[], [None], [{}], [rule("unknown")],
                                  [rule(left_field="")], [rule(right_field=1)],
                                  [rule(extra=True)], [rule("integer_time_floor")]])
def test_missing_or_unsupported_rules_are_rejected(rules):
    with pytest.raises(ValueError):
        match_records([left("x")], [right("x")], rules)


def test_empty_inputs_and_unmatched_rows_remain_explicit():
    assert match_records([], [], [rule()])["matches"] == []
    result = match_records([left("x")], [], [rule()])
    assert result["matches"] == [{"left_id": "synthetic-left", "status": "UNMATCHED",
                                    "candidate_ids": [], "candidate_details": []}]
    assert result["shared_candidates"] == []


def test_original_rows_and_rules_are_independent_copies():
    inputs = ([left("1.0", notes=["invented"])], [right("1.00")], [rule("decimal_numeric")])
    original = deepcopy(inputs)
    result = match_records(*inputs)
    assert inputs == original
    result["left_rows"][0]["notes"].append("changed")
    result["right_rows"][0]["raw_value"] = "changed"
    result["rules"][0]["mode"] = "changed"
    assert inputs == original


def test_documented_synthetic_example_has_ambiguity_collision_and_no_match():
    path = Path(__file__).resolve().parents[1] / "examples" / "record_reconciliation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    result = match_records(**data)
    assert [row["status"] for row in result["matches"]] == ["AMBIGUOUS", "UNIQUE", "UNIQUE", "UNMATCHED"]
    assert result["shared_candidates"] == [{"right_id": "synthetic-r3",
                                            "left_ids": ["synthetic-l2", "synthetic-l3"]}]
