from __future__ import annotations

import pytest

from app.services.finviz.query import FinvizQuery, FinvizQueryError
from app.services.finviz.strategies import (
    STRATEGY_A_BASE,
    STRATEGY_A_EARNINGS_PREFIX,
    STRATEGY_A_EARNINGS_VALUES,
    STRATEGY_B_BASE,
    STRATEGY_B_PATTERN_PREFIX,
    STRATEGY_B_PATTERN_VALUES,
)


def test_to_url_includes_canonical_finviz_path() -> None:
    query = FinvizQuery(filters=("a", "b"), sort="-x")
    url = query.to_url()
    assert url.startswith("https://finviz.com/screener.ashx?")
    assert "v=111" in url
    assert "ft=4" in url
    assert "o=-x" in url
    # f= param contains the comma-joined filters; encoded with urlencode.
    assert "f=a%2Cb" in url


def test_with_filter_replaced_swaps_existing_value() -> None:
    base = STRATEGY_A_BASE
    swapped = base.with_filter_replaced(
        STRATEGY_A_EARNINGS_PREFIX, "earningsdate_nextweek"
    )
    assert "earningsdate_nextweek" in swapped.filters
    assert "earningsdate_thisweek" not in swapped.filters
    assert len(swapped.filters) == len(base.filters)


def test_with_filter_replaced_appends_when_no_existing_filter() -> None:
    query = FinvizQuery(filters=("cap_midover",), sort="-relativevolume")
    swapped = query.with_filter_replaced("earningsdate_", "earningsdate_thisweek")
    assert swapped.filters == ("cap_midover", "earningsdate_thisweek")


def test_with_filter_replaced_rejects_mismatched_prefix() -> None:
    with pytest.raises(FinvizQueryError):
        STRATEGY_A_BASE.with_filter_replaced("earningsdate_", "ta_pattern_channelup2")


def test_stable_hash_is_deterministic_and_order_independent() -> None:
    query_a = FinvizQuery(filters=("a", "b", "c"), sort="-x")
    query_b = FinvizQuery(filters=("c", "b", "a"), sort="-x")
    assert query_a.stable_hash() == query_b.stable_hash()


def test_stable_hash_differs_when_sort_changes() -> None:
    base = FinvizQuery(filters=("a",), sort="-x")
    other = FinvizQuery(filters=("a",), sort="-y")
    assert base.stable_hash() != other.stable_hash()


def test_strategy_a_url_contains_doc_filters() -> None:
    url = STRATEGY_A_BASE.to_url()
    for required in (
        "cap_midover",
        "earningsdate_thisweek",
        "fa_epssurprise_pos",
        "fa_revenuesurprise_pos",
        "sh_relvol_o1.5",
        "ta_rsi_50to70",
    ):
        assert required in url, f"Strategy A URL missing {required}"
    assert "o=-relativevolume" in url


def test_strategy_b_url_contains_doc_filters() -> None:
    url = STRATEGY_B_BASE.to_url()
    for required in (
        "cap_midover",
        "sh_short_u20",
        "sh_insidertrans_pos",
        "ta_volatility_wo4",
        "ta_pattern_channelup2",
        "ta_highlow52w_b10h",
    ):
        assert required in url, f"Strategy B URL missing {required}"
    assert "o=-perfhalf" in url


def test_strategy_a_swap_values_match_prefix() -> None:
    for value in STRATEGY_A_EARNINGS_VALUES:
        assert value.startswith(STRATEGY_A_EARNINGS_PREFIX)


def test_strategy_b_swap_values_match_prefix() -> None:
    for value in STRATEGY_B_PATTERN_VALUES:
        assert value.startswith(STRATEGY_B_PATTERN_PREFIX)
