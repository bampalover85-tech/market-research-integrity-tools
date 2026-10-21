# Explicit record-candidate reconciliation

`match_records(left_rows, right_rows, rules)` finds **all supplied candidate rows** matching explicit field rules. It is a standard-library-only, in-memory comparison tool, not a source verifier or a one-to-one assignment algorithm.

**`UNIQUE` means exactly one supplied right-hand candidate matched the chosen rules for that left row. It does not establish original/native identity, completeness, provenance, causality, or a global bijection. Always inspect `shared_candidates`.** A rule that floors time is an intentionally lossy projection, not a statement of exact timestamp equality.

## Rows and identity

Both sides are iterables of dictionaries with a unique, nonempty string `row_id` on that side. IDs are opaque: no float conversion, integer conversion, trimming, case folding or positional tie-break occurs. The same ID may appear on opposite sides; uniqueness is checked separately. Duplicate IDs on one side, missing mapped fields and invalid values raise `ValueError`; invalid candidates are never silently skipped. All rows are validated even if no rows on the other side can match them.

The function copies the original rows and rules into its output, preserving literal values and extra payload fields. It does not mutate inputs, access files or networks, authenticate row IDs, or derive a hidden record key. Supply manageable finite input collections: results include copies of both inputs and details for every match, so a highly ambiguous match can produce large output.

## Rules

Supply at least one rule. Every rule explicitly names `left_field`, `right_field` and `mode`. Unknown modes, extra rule keys and missing rule keys are rejected rather than ignored. Field names are literal top-level dictionary keys, not paths or aliases. The rules form an AND: every rule must match.

| Mode | Input and comparison |
| --- | --- |
| `exact_text` | Both values must be strings. Compare exactly; case, whitespace, leading zeros and empty strings remain meaningful. No text normalization is performed. |
| `decimal_numeric` | Both values must be decimal strings matching `-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?`. Compare finite `Decimal(text)` values directly. Numeric equality intentionally treats `1.0` and `1.00` alike; original text and per-candidate `literal_equal` remain visible. Floats, integers, booleans, Decimal objects, whitespace, underscores and non-finite values are rejected. No `normalize`, `quantize`, float conversion or context-rounded arithmetic is used. |
| `integer_time_floor` | Both values must be integers (not booleans) or plain integer strings matching `-?[0-9]+`. The right value is floored into the left unit using integer arithmetic. Explicit units and compatible declared semantics are mandatory; see below. |

For exact text and decimal numeric modes, only those three base keys are allowed. There are no tolerances or fuzzy matches. Decimal numeric comparison is an explicitly selected value-equivalence rule, not literal equality or a validation of what the value means.

### Explicit time projection

A time-floor rule additionally requires all four keys:

```json
{
  "left_field": "time_ms",
  "right_field": "tick_us",
  "mode": "integer_time_floor",
  "left_unit": "ms",
  "right_unit": "us",
  "left_semantics": "synthetic_capture_clock",
  "right_semantics": "synthetic_capture_clock"
}
```

Units are exactly `s`, `ms`, `us`, or `ns`. The right unit must be finer than or equal to the left unit. Comparing coarser right data to a finer left field is rejected rather than inventing precision. The comparison is:

`left_integer == right_integer // (left_unit_nanoseconds // right_unit_nanoseconds)`

For example, right ticks `100001` and `100999` in microseconds both project to left tick `100` in milliseconds and can both remain candidates. There is no nearest rounding: `100999` does not become `101`. Negative values use mathematical floor, so `-1` microsecond projects to `-1` millisecond, not zero. Same-unit comparison has divisor one and discards no ticks.

Time-semantic labels must be equal nonempty strings. They are **caller declarations, not evidence**: the function cannot prove that clocks share an epoch, origin, synchronization, event meaning or acquisition process. Do not equate event time with receipt time merely because the numeric values coincide. No time field, epoch, offset or clock relation is guessed.

Every matched time rule exposes `time_projection` with operation, divisor, `potential_precision_loss` and `discarded_right_ticks` (the integer remainder). Potential loss remains true whenever the chosen divisor exceeds one, even when this particular right value has zero remainder. Original integer values or strings remain in the echoed rows. This mode never claims recovered higher-precision time or exact underlying timestamp equality.

## Results and collision checks

- `left_rows`, `right_rows`, `rules`: independent copies of supplied data and configuration.
- `matches`: one result per left row, in left input order. Each has `left_id`, `status`, sorted `candidate_ids`, and `candidate_details`.
- `UNMATCHED`: no supplied candidate satisfied every rule. This does not prove no real counterpart exists elsewhere.
- `UNIQUE`: one supplied candidate matched. It is not automatically selected, assigned or certified.
- `AMBIGUOUS`: multiple candidates matched; all are retained, even if their other field values are identical.
- `candidate_details`: each candidate has a `right_id` and one comparison entry per rule. `literal_equal` is strict type-and-value equality of the two original values, independent of numeric equivalence or time projection. Time rules additionally report projection details.
- `shared_candidates`: every right row referenced by more than one left row, with sorted `left_ids`. Two left rows can each be `UNIQUE` and still share the same right row. There is no implicit global one-to-one reconciliation.

Candidate IDs are sorted only for stable reporting, never to pick a winner. Permuting right input preserves `matches`; echoed `right_rows` retains the supplied order. Permuting left input changes result ordering but not the per-ID candidate sets or shared-candidate membership.

## Scope is explicit, not inferred

Choose rules that include every identity boundary relevant to your use case, such as source/provider, stream, instrument and record type. The example maps source, stream and instrument explicitly. Omit these rules and otherwise identical records from different scopes may match; the function does not silently invent domain fields or certify that your rule set is sufficient.

This utility does not validate the semantics of a trade, reconstruct venue order, deduplicate raw records, fill missing data, pick an arbitrary tie, infer a trading signal, or estimate fills/PnL. It does not replace exact input-binding validators or ingestion review. The tests use invented records to validate this comparison contract, not real-source reconciliation quality.
