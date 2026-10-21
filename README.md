# Market Research Integrity Tools

Small, fail-closed utilities for reproducible quantitative research.

This public preview intentionally contains no private trading strategy, signal threshold, performance result, live execution configuration, private data, or internal routing material.

## Included

- `src/invariant_testpack.py`: exact byte/SHA256-bound CSV invariant validation.
- `src/differential_validator.py`: exact byte/SHA256-bound JSON differential comparison.
- `src/observed_quote_context.py`: pure recording-order quote-context annotation with explicit unknowns.
- `src/record_reconciliation.py`: explicit field-mapped candidate matching that preserves ambiguity and shared candidates.
- `tests/test_smoke.py`: synthetic smoke tests.
- `tests/test_observed_quote_context.py`: synthetic boundary and preservation tests.
- `tests/test_record_reconciliation.py`: synthetic decimal, time-projection and collision tests.

## Design principles

- File-validator inputs are bound by exact byte length and SHA256.
- Missing or mismatched bindings fail closed.
- Missing comparable rows do not silently pass.
- Numeric tolerances must be explicit.
- Type differences remain visible.
- File-validator output files are create-only.
- The tools do not choose trading thresholds, strategies, or economic values.
- Quote context is limited to one contiguous recording segment in the same source, stream, instrument and batch. It is not proof of exchange order or execution availability.
- Reconciliation retains every matching candidate. A per-row unique candidate is not a proven identity or a global one-to-one match.

## Quote-context example

From the repository root, using Python 3.12 or later:

```python
import json
from pathlib import Path
from src.observed_quote_context import annotate_quote_context

events = json.loads(Path("examples/observed_quote_context.json").read_text())
for row in annotate_quote_context(events):
    if row["event"]["kind"] == "trade":
        print(row["event"]["event_id"], row["context"]["status"], row["context"]["reason"])
```

The invented example produces an observed context, then an unknown after a crossed quote, then an unknown at a new batch. Invalid latest quotes never fall back to older ones. The transform does no file I/O or hashing; it does not replace the file validators.

Read the [input contract and limitations](docs/observed_quote_context.md) before adapting a feed. Caller-supplied positions must retain the original capture sequence; adjacency alone does not establish source completeness, freshness or causality. No fills, PnL or trading signals are inferred.

## Record-reconciliation example

```python
import json
from pathlib import Path
from src.record_reconciliation import match_records

data = json.loads(Path("examples/record_reconciliation.json").read_text())
result = match_records(**data)
for row in result["matches"]:
    print(row["left_id"], row["status"], row["candidate_ids"])
print("Shared candidates:", result["shared_candidates"])
```

This invented example shows an ambiguous match, two individually unique matches that share one candidate, and an unmatched record. Rules explicitly select exact text, exact decimal numeric equality or integer-time floor projection. **Time flooring can discard precision**; it is not timestamp equality. Original rows, literal differences, projection details and collisions remain visible. Nothing silently selects a winner or invents a one-to-one assignment.

Read the [reconciliation contract and limits](docs/record_reconciliation.md), especially the caller's responsibility to map source/stream/instrument fields and declare compatible clocks. Like quote annotation, this is an in-memory transform, not a source-authenticity validator.

## Tests

```sh
python -m pip install pytest
python -m pytest -q
```

All checked-in examples and tests use synthetic inputs. Counterexamples and narrowly scoped boundary tests are welcome; see [Contributing](CONTRIBUTING.md).

## License

Licensed under the Apache License, Version 2.0. See `LICENSE` for the full terms.
