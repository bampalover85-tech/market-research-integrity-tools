# Observed quote context

`annotate_quote_context(events)` is a small standard-library-only, in-memory transform. It attaches the latest usable recorded bid/ask snapshot to a later trade record only within the same uninterrupted recording segment. It returns one annotation per input event and does not sort, deduplicate, mutate input, write files or access a network.

This is **observed feed order, not exchange execution order or causality**. A quote attached to a record does not prove that the quote was still live, available to a participant or fillable. The transform computes no execution price, spread-derived signal, aggressor side, trading decision, fill, PnL or performance estimate.

## Input contract

Input is an iterable of dictionaries. Every event requires:

| Field | Contract |
| --- | --- |
| `source` | Nonempty string identifying the recording source/provider. |
| `stream` | Nonempty string identifying the feed/capture stream. |
| `instrument` | Nonempty string identifying the instrument. Synthetic examples use `TEST`. |
| `batch` | Nonempty string identifying one receipt/capture batch; it is not a timestamp. |
| `position` | Nonnegative integer capture position, excluding booleans. Keep its original value. |
| `event_id` | Nonempty opaque string, unique within `(source, stream, instrument, batch)`. |
| `kind` | `quote`, `trade`, `reset`, or another nonempty string. Unrecognized kinds erase context. |

Identity strings are compared exactly, without normalization. Missing/invalid required fields or duplicate event identities raise `ValueError`; no partial result is returned. Empty input returns an empty list. Each call starts without prior context.

A `quote` must be a complete bid/ask snapshot, not a one-sided delta. `bid` and `ask` must be positive, finite **plain decimal strings** matching `[0-9]+(?:\.[0-9]+)?`. Numbers, booleans, signs, exponents, whitespace, underscores, non-ASCII digits, zero and non-finite values are not accepted. `Decimal` compares the parsed strings directly; it never converts via float or subtracts under a rounding context. Original strings, including trailing zeros, are kept. A locked quote (`bid == ask`) is retained with `locked: true`; a crossed quote (`bid > ask`) erases context.

Trade fields, including any `price`, are opaque payload and are **not validated or interpreted**. This utility validates the quote-context relation, not the trade itself. Extra fields are copied to the output event unchanged and never treated as evidence.

### Capture positions are an assumption, not recovered evidence

Callers are responsible for supplying the correct scope and batch labels, the original capture order, and all records that might affect context. Do not filter rows and then assign new contiguous positions. Interleave separate streams only if their positions and identities faithfully represent the supplied capture; scope switches deliberately erase inherited context rather than keeping a per-stream cache.

The function sees only supplied records. A contiguous sequence cannot prove that a source capture is authentic, complete, or free of omitted messages. It does not verify hashes, source documents, timestamps, clock synchronization, exchange sequence numbers, order-book validity beyond bid/ask ordering, or quote age. Use a separate ingestion/source-validation layer for those obligations; the existing file validators are not automatically invoked here.

## State boundaries

| Condition | Effect |
| --- | --- |
| Source, stream or instrument changes | Erase inherited context (`scope_change`). |
| Batch changes | Erase inherited context (`batch_change`). |
| Position jumps forward by more than one | Erase inherited context (`position_gap`). |
| Position is at/below the greatest prior position for that source/stream/instrument/batch, even after leaving and returning | Erase context and refuse to seed a quote from that record (`non_increasing_position`). |
| Invalid/missing bid or ask | Erase context (`invalid_quote`), with no fallback. |
| Crossed latest quote | Erase context (`crossed_quote`), with no fallback. |
| `reset` or an unrecognized event kind | Erase context (`explicit_reset` / `unsupported_event_kind`). |

A valid quote at a new scope, batch or forward-gap boundary can begin a new segment; only later contiguous records can use it. After an invalid or non-increasing record, a subsequent valid quote strictly beyond the scope/batch's prior high-water position is required to restore context. Returning to an earlier scope/batch does not recover its old quote or forget its high-water position. Repeated positions with different event IDs are preserved as unknown, not silently treated as a new capture. This check concerns caller-supplied positions only, not independently verified chronology.

## Output

Each output is `{"event": <independent copy of input>, "context": {...}}`.

- `OBSERVED`: a trade has context in this recording segment. `quote` carries the source/stream/instrument/batch/event ID, original position, literal bid/ask and a `locked` boolean. Reason: `same_batch_contiguous_recording`.
- `UNKNOWN`: no context may be attached; `quote` is `null`. The reason identifies the latest invalidation or `no_prior_quote`. Unknown persists until a valid new quote arrives. It is not a negative price comparison or an implied older quote.
- `NOT_APPLICABLE`: a valid quote record itself is not annotated as a trade. Reason: `quote_record`; `quote` is `null`.

No timestamp matching or future lookup is performed. A quote after a trade cannot revise that earlier trade. The returned objects are independent copies, so editing one annotation does not mutate input or another annotation.

## Review scope

The synthetic tests exercise boundary resets, invalid/crossed/locked snapshots, literal preservation, exact decimal comparisons, duplicate identity rejection and short record-kind combinations. They establish behavior for this input contract, not real-feed completeness or economic usefulness. Useful contributions are minimal counterexamples and clearly scoped tests, not real market captures or performance claims.
