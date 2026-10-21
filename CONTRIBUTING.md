# Contributing

Contributions are welcome under the Apache License, Version 2.0.

Useful contributions include deterministic invariant types, safer diagnostics, synthetic/property-based tests, performance improvements that preserve results, and additional comparison modes with explicit semantics.

Out of scope: trading strategies, alpha claims, profitability rankings, exchange credentials, live-trading integrations, hidden default thresholds, or changes that weaken exact input binding.

Pull requests should include a reproducible test. Behavioral changes should explain the old behavior, new behavior, and why the new behavior is safer or more correct.

## Quote-context review questions

We welcome small synthetic counterexamples, especially for these questions:

- Can any source, stream, instrument, batch, missing position, reset or unrecognized record accidentally reuse an old quote?
- Can an invalid or crossed latest quote fall back to an older quote, or a future quote change an earlier trade's annotation?
- Are duplicate identities and non-increasing positions handled conservatively without silently sorting or deduplicating input?
- Do literal decimal strings and event payloads survive unchanged, including under a low Decimal precision setting?
- Is any documentation wording easy to mistake for a guarantee of source completeness, freshness, exchange causality, fillability or profitability?

Provide invented identifiers and prices, the smallest failing input, expected output, and the relevant input-contract assumption. Do not submit real feed captures or account details. New event-kind support must specify whether and why it preserves or invalidates context; unknown kinds currently reset it.

## Reconciliation review questions

- Can numeric comparison collapse two distinct high-precision decimals under a small Decimal context?
- Can explicitly chosen time flooring obscure discarded precision, a negative-tick boundary, or an incompatible clock/unit assumption?
- Are all candidates retained when equal values have different row IDs, and are shared candidates visible when several left rows each report `UNIQUE`?
- Does permuting candidate input alter the reported candidate set or silently break a tie?
- Could a caller mistake omitted source/stream/instrument rules, `UNIQUE`, or matching time labels for verified provenance?

Use minimal invented rows, explicit field rules and expected candidate sets. Changes must not introduce implicit rounding, text/ID coercion, hidden field mappings or arbitrary one-to-one assignment.


## Contribution licensing

Unless explicitly stated otherwise, contributions intentionally submitted for inclusion in this repository are provided under the Apache License, Version 2.0, consistent with Section 5 of the license.
