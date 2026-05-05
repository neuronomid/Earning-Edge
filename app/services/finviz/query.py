from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from urllib.parse import urlencode

FINVIZ_SCREENER_BASE_URL = "https://finviz.com/screener"


class FinvizQueryError(ValueError):
    """Raised when a FinvizQuery cannot be constructed or modified."""


@dataclass(slots=True, frozen=True)
class FinvizQuery:
    filters: tuple[str, ...]
    sort: str
    view: str = "111"

    def with_filter_replaced(self, group_prefix: str, value: str) -> FinvizQuery:
        if not value.startswith(group_prefix):
            raise FinvizQueryError(
                f"Replacement value '{value}' does not start with prefix '{group_prefix}'"
            )
        new_filters = tuple(
            value if existing.startswith(group_prefix) else existing
            for existing in self.filters
        )
        if new_filters == self.filters and not any(
            existing.startswith(group_prefix) for existing in self.filters
        ):
            new_filters = (*self.filters, value)
        return replace(self, filters=new_filters)

    def to_url(self) -> str:
        params = (
            ("v", self.view),
            ("f", ",".join(self.filters)),
            ("o", self.sort),
        )
        return f"{FINVIZ_SCREENER_BASE_URL}?{urlencode(params, safe=',')}"

    def stable_hash(self) -> str:
        canonical = ",".join(sorted(self.filters)) + f"|{self.sort}|{self.view}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
