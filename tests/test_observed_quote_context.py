# SPDX-License-Identifier: Apache-2.0
"""Synthetic contract tests; no external feeds or recorded market data."""

from copy import deepcopy
from decimal import Decimal, localcontext
from itertools import product
import json
from pathlib import Path

import pytest

from src.observed_quote_context import annotate_quote_context


def event(kind, position, **changes):
    row = {
        "source": "synthetic-provider",
        "stream": "demo-feed",
        "instrument": "TEST",
        "batch": "batch-A",
        "event_id": f"synthetic-{kind}-{position}",
        "kind": kind,
        "position": position,
    }
    if kind == "quote":
        row.update(bid="10.00", ask="10.50")
    if kind == "trade":
        row["price"] = "10.25"
    row.update(changes)
    return row


def context(*events):
    return annotate_quote_context(events)[-1]["context"]


def test_empty_input_and_no_state_between_calls():
    assert annotate_quote_context([]) == []
    annotate_quote_context([event("quote", 0)])
    result = context(event("trade", 1))
    assert result == {"status": "UNKNOWN", "reason": "no_prior_quote", "quote": None}


def test_contiguous_trade_uses_latest_quote_and_literal_prices():
    rows = [event("quote", 0), event("quote", 1, bid="010.100", ask="010.900"),
            event("trade", 2), event("trade", 3)]
    result = annotate_quote_context(iter(rows))
    assert len(result) == len(rows)
    assert [entry["event"] for entry in result] == rows
    assert result[1]["context"]["status"] == "NOT_APPLICABLE"
    for entry in result[2:]:
        assert entry["context"]["status"] == "OBSERVED"
        quote = entry["context"]["quote"]
        assert quote["event_id"] == rows[1]["event_id"]
        assert (quote["bid"], quote["ask"]) == ("010.100", "010.900")
        assert quote["locked"] is False


def test_future_quote_never_revises_earlier_trade():
    result = annotate_quote_context([event("trade", 0), event("quote", 1), event("trade", 2)])
    assert result[0]["context"]["status"] == "UNKNOWN"
    assert result[0]["context"]["quote"] is None
    assert result[2]["context"]["status"] == "OBSERVED"


def test_inputs_and_each_output_are_independent():
    rows = [event("quote", 0, metadata={"labels": ["invented"]}),
            event("trade", 1), event("trade", 2)]
    original = deepcopy(rows)
    result = annotate_quote_context(rows)
    assert rows == original
    result[0]["event"]["metadata"]["labels"].append("changed")
    result[1]["context"]["quote"]["bid"] = "999"
    assert rows == original
    assert result[2]["context"]["quote"]["bid"] == "10.00"


@pytest.mark.parametrize("bad", [None, True, False, 10, 10.0, Decimal("10"),
                                 "", " ", "NaN", "sNaN", "Infinity", "-Infinity",
                                 "0", "0.00", "-1", "+1", "1e1", "1_0",
                                 " 10", "10 ", ".5", "10.", "１０"])
@pytest.mark.parametrize("side", ["bid", "ask"])
def test_invalid_latest_quote_erases_older_quote(side, bad):
    result = context(event("quote", 0), event("quote", 1, **{side: bad}), event("trade", 2))
    assert result == {"status": "UNKNOWN", "reason": "invalid_quote", "quote": None}


@pytest.mark.parametrize("side", ["bid", "ask"])
def test_missing_quote_side_erases_older_quote(side):
    quote = event("quote", 1)
    del quote[side]
    assert context(event("quote", 0), quote, event("trade", 2))["reason"] == "invalid_quote"


def test_crossed_quote_invalidates_but_locked_quote_is_explicit():
    result = context(event("quote", 0), event("quote", 1, bid="12", ask="11"), event("trade", 2))
    assert result == {"status": "UNKNOWN", "reason": "crossed_quote", "quote": None}
    locked = context(event("quote", 0, bid="10.0", ask="10.00"), event("trade", 1))
    assert locked["status"] == "OBSERVED"
    assert locked["quote"]["locked"] is True


def test_comparison_is_exact_even_with_small_decimal_precision():
    with localcontext() as ctx:
        ctx.prec = 2
        rows = [event("quote", 0, bid="10.0000000000000000000000000002",
                      ask="10.0000000000000000000000000001"), event("trade", 1)]
        assert context(*rows)["reason"] == "crossed_quote"
        rows[0]["bid"], rows[0]["ask"] = rows[0]["ask"], rows[0]["bid"]
        assert context(*rows)["status"] == "OBSERVED"


@pytest.mark.parametrize("field", ["source", "stream", "instrument", "batch"])
def test_identity_boundary_erases_context_and_return_does_not_restore_it(field):
    other = event("trade", 1, **{field: "synthetic-other"})
    result = annotate_quote_context([event("quote", 0), other, event("trade", 2)])
    for entry in result[1:]:
        assert entry["context"]["status"] == "UNKNOWN"
        assert entry["context"]["quote"] is None
    expected = "batch_change" if field == "batch" else "scope_change"
    assert result[1]["context"]["reason"] == expected


def test_original_position_gap_is_not_reindexed_or_bridged():
    result = annotate_quote_context([event("quote", 4), event("trade", 6), event("trade", 7)])
    assert [entry["event"]["position"] for entry in result] == [4, 6, 7]
    assert all(entry["context"]["reason"] == "position_gap" for entry in result[1:])


@pytest.mark.parametrize("position", [3, 4])
@pytest.mark.parametrize("kind", ["quote", "trade"])
def test_non_increasing_position_cannot_seed_or_reuse_context(position, kind):
    result = annotate_quote_context([event("quote", 4),
                                    event(kind, position, event_id="synthetic-new-id"),
                                    event("trade", position + 1)])
    assert all(entry["context"]["status"] == "UNKNOWN" for entry in result[1:])
    assert all(entry["context"]["reason"] == "non_increasing_position" for entry in result[1:])


def test_rewind_cannot_reseed_quote_at_conflicting_original_position():
    rows = [event("quote", 4), event("trade", 3),
            event("quote", 4, event_id="synthetic-conflict", bid="11", ask="12"),
            event("trade", 5), event("quote", 6), event("trade", 7)]
    result = annotate_quote_context(rows)
    assert all(entry["context"]["quote"] is None for entry in result[1:4])
    assert result[2]["context"]["reason"] == "non_increasing_position"
    assert result[-1]["context"]["quote"]["event_id"] == rows[4]["event_id"]


@pytest.mark.parametrize("field", ["source", "stream", "instrument", "batch"])
def test_scope_return_does_not_forget_original_position_high_water(field):
    rows = [event("quote", 4), event("trade", 0, **{field: "synthetic-other"}),
            event("quote", 4, event_id="synthetic-conflict"), event("trade", 5)]
    result = annotate_quote_context(rows)
    assert result[2]["context"]["reason"] == "non_increasing_position"
    assert result[-1]["context"]["quote"] is None


@pytest.mark.parametrize("boundary", [{"position": 9}, {"batch": "batch-B"},
                                      {"source": "synthetic-other"}])
def test_valid_quote_can_seed_a_fresh_run_after_a_boundary(boundary):
    quote = event("quote", 1, **{key: value for key, value in boundary.items() if key != "position"})
    quote["position"] = boundary.get("position", 1)
    trade = event("trade", quote["position"] + 1,
                  source=quote["source"], batch=quote["batch"])
    result = context(event("quote", 0), quote, trade)
    assert result["status"] == "OBSERVED"
    assert result["quote"]["event_id"] == quote["event_id"]


@pytest.mark.parametrize("kind, reason", [("reset", "explicit_reset"),
                                          ("unrecognized", "unsupported_event_kind")])
def test_reset_and_unknown_record_kinds_erase_context(kind, reason):
    result = context(event("quote", 0), event(kind, 1), event("trade", 2))
    assert result == {"status": "UNKNOWN", "reason": reason, "quote": None}
    recovered = context(event(kind, 0), event("quote", 1), event("trade", 2))
    assert recovered["status"] == "OBSERVED"


@pytest.mark.parametrize("field", ["source", "stream", "instrument", "batch", "event_id", "kind"])
@pytest.mark.parametrize("value", [None, "", "  ", 1, True])
def test_invalid_identity_is_rejected(field, value):
    row = event("trade", 0)
    row[field] = value
    with pytest.raises(ValueError, match=f"invalid {field}"):
        annotate_quote_context([row])


@pytest.mark.parametrize("position", [None, -1, True, False, 0.0, "0"])
def test_invalid_position_is_rejected(position):
    with pytest.raises(ValueError, match="invalid position"):
        annotate_quote_context([event("trade", position)])


def test_duplicate_identity_rejected_without_silent_deduplication():
    with pytest.raises(ValueError, match="duplicate event identity"):
        annotate_quote_context([event("quote", 0, event_id="synthetic-same"),
                                event("trade", 1, event_id="synthetic-same")])
    rows = [event("trade", 0, event_id="synthetic-reused"),
            event("trade", 0, event_id="synthetic-reused", batch="batch-B")]
    assert len(annotate_quote_context(rows)) == 2


def test_non_dict_record_rejected():
    with pytest.raises(ValueError, match="expected a dict"):
        annotate_quote_context([None])


def test_short_synthetic_sequences_obey_no_future_or_post_reset_quote_rule():
    for kinds in product(("quote", "trade", "reset", "unknown"), repeat=4):
        rows = [event(kind, pos) for pos, kind in enumerate(kinds)]
        result = annotate_quote_context(rows)
        latest = None
        for row, entry in zip(rows, result):
            if row["kind"] == "quote":
                latest = row
            elif row["kind"] != "trade":
                latest = None
            else:
                quote = entry["context"]["quote"]
                assert (quote is not None) == (latest is not None)
                if latest is not None:
                    assert quote["event_id"] == latest["event_id"]
                    assert quote["position"] < row["position"]


def test_documented_json_example():
    path = Path(__file__).resolve().parents[1] / "examples" / "observed_quote_context.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    result = annotate_quote_context(rows)
    trades = [entry for entry in result if entry["event"]["kind"] == "trade"]
    assert [entry["context"]["status"] for entry in trades] == ["OBSERVED", "UNKNOWN", "UNKNOWN"]
    assert [entry["context"]["reason"] for entry in trades] == [
        "same_batch_contiguous_recording", "crossed_quote", "batch_change"]
