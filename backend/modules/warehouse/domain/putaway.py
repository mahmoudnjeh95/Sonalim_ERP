from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class PutawayRule:
    id: str
    tenant_id: str
    site_id: str
    product_id: str
    target_location_id: str
    created_by: str
    created_at: datetime.datetime


def rank_candidates(
    *,
    rule_location_id: str | None,
    same_product_location_ids: list[str],
    empty_bin_ids: list[str],
    exclude_location_id: str | None,
) -> list[str]:
    """Merges the three suggestion signals in priority order -- an explicit
    rule, then a bin already holding the same product (consolidate like with
    like), then any empty bin -- de-duplicated, with the location the stock
    is currently sitting in excluded: suggesting "put it back where it
    already is" isn't a suggestion."""
    ordered = [*([rule_location_id] if rule_location_id else []), *same_product_location_ids, *empty_bin_ids]
    seen: set[str] = set()
    result: list[str] = []
    for location_id in ordered:
        if location_id == exclude_location_id or location_id in seen:
            continue
        seen.add(location_id)
        result.append(location_id)
    return result
