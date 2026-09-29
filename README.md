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

## License status

This repository is currently a **public preview with no open-source license selected yet**.

Until an explicit license is added, treat the code as viewable source rather than a completed open-source release.
