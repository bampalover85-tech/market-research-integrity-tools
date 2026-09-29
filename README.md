# Market Research Integrity Tools

Small, fail-closed utilities for reproducible quantitative research.

This public preview intentionally contains no private trading strategy, signal threshold, performance result, live execution configuration, private data, or internal routing material.

## Included

- `src/invariant_testpack.py`: exact byte/SHA256-bound CSV invariant validation.
- `src/differential_validator.py`: exact byte/SHA256-bound JSON differential comparison.
- `tests/test_smoke.py`: synthetic smoke tests.

## Design principles

- Inputs are bound by exact byte length and SHA256.
- Missing or mismatched bindings fail closed.
- Missing comparable rows do not silently pass.
- Numeric tolerances must be explicit.
- Type differences remain visible.
- Output files are create-only.
- The tools do not choose trading thresholds, strategies, or economic values.

## License

Licensed under the Apache License, Version 2.0. See `LICENSE` for the full terms.
