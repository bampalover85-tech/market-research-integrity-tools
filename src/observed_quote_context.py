# SPDX-License-Identifier: Apache-2.0
"""Attach recorded quote context without inferring exchange order or execution.

This is an in-memory transform, not a data-source verifier. Callers must retain
original capture positions and provide all records that could affect context.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re


_IDENTITY = ("source", "stream", "instrument", "batch", "event_id")
_QUOTE_FIELDS = _IDENTITY + ("position", "bid", "ask")
_PRICE = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")


def _positive_decimal(value):
    """Parse only positive plain decimal strings; never round-trip via float."""
    if not isinstance(value, str) or _PRICE.fullmatch(value) is None:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def annotate_quote_context(events):
    """Return one independent annotation per input event, in supplied order.

    Required fields: source, stream, instrument, batch, event_id, kind (nonempty
    strings) and position (nonnegative int, not bool). Event identity must be
    unique within source/stream/instrument/batch. Invalid identity raises
    ValueError rather than returning partial results.

    A quote supplies a complete bid/ask snapshot as positive decimal strings.
    A trade receives only the latest valid quote in its uninterrupted scope,
    batch and position run. Unknown kinds and reset records erase context.
    Invalid/crossed quotes erase context; there is no fallback to an older one.
    Locked quotes (bid == ask) are retained without an execution interpretation.

    Scope/batch changes and position gaps erase inherited context. A valid quote
    at such a boundary may seed a new run. A position at/below its scope/batch
    high-water mark erases context and cannot seed a quote. Nothing is sorted,
    deduplicated, interpolated, or carried across separate function calls.

    Output event payloads and quote price strings are preserved. OBSERVED means
    recorded context only, not fresh, causally prior, executable or fillable.
    """
    results = []
    seen = set()
    high_water = {}
    previous = None
    quote = None
    unknown_reason = "no_prior_quote"

    for index, item in enumerate(events):
        if not isinstance(item, dict):
            raise ValueError(f"event {index}: expected a dict")
        for field in _IDENTITY + ("kind",):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"event {index}: invalid {field}")
        position = item.get("position")
        if type(position) is not int or position < 0:
            raise ValueError(f"event {index}: invalid position")
        identity = tuple(item[field] for field in _IDENTITY)
        if identity in seen:
            raise ValueError(f"event {index}: duplicate event identity")
        seen.add(identity)

        scope = tuple(item[field] for field in ("source", "stream", "instrument"))
        batch = item["batch"]
        order_invalid = False
        boundary = None
        if previous is not None:
            old_scope, old_batch, old_position = previous
            if scope != old_scope:
                boundary = "scope_change"
            elif batch != old_batch:
                boundary = "batch_change"
            elif position != old_position + 1:
                boundary = "position_gap"
        partition = scope + (batch,)
        maximum = high_water.get(partition, -1)
        if position <= maximum:
            boundary = "non_increasing_position"
            order_invalid = True
        high_water[partition] = max(position, maximum)
        if boundary is not None:
            quote = None
            unknown_reason = boundary

        kind = item["kind"]
        status, reason = "UNKNOWN", unknown_reason
        attached_quote = None
        if order_invalid:
            # Do not accept a quote carried by a duplicate/reversed position.
            pass
        elif kind == "quote":
            quote = None
            bid = _positive_decimal(item.get("bid"))
            ask = _positive_decimal(item.get("ask"))
            if bid is None or ask is None:
                unknown_reason = "invalid_quote"
                reason = unknown_reason
            elif bid > ask:
                unknown_reason = "crossed_quote"
                reason = unknown_reason
            else:
                quote = {field: item[field] for field in _QUOTE_FIELDS}
                quote["locked"] = bid == ask
                status, reason = "NOT_APPLICABLE", "quote_record"
        elif kind == "trade":
            if quote is not None:
                status, reason = "OBSERVED", "same_batch_contiguous_recording"
                attached_quote = deepcopy(quote)
        else:
            quote = None
            unknown_reason = (
                "explicit_reset" if kind == "reset" else "unsupported_event_kind"
            )
            reason = unknown_reason

        results.append({
            "event": deepcopy(item),
            "context": {
                "status": status,
                "reason": reason,
                "quote": attached_quote,
            },
        })
        previous = (scope, batch, position)

    return results
