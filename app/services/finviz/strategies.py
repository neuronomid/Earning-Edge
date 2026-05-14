from __future__ import annotations

from app.services.finviz.query import FinvizQuery

STRATEGY_A_BASE = FinvizQuery(
    filters=(
        "earningsdate_nextweek",
        "geo_usa",
    ),
    sort="-marketcap",
)

STRATEGY_A_EARNINGS_PREFIX = "earningsdate_"
STRATEGY_A_EARNINGS_VALUES: tuple[str, ...] = ("earningsdate_nextweek",)

STRATEGY_B_BASE = FinvizQuery(
    filters=(
        "cap_midover",
        "geo_usa",
        "sh_avgvol_o1000",
        "sh_opt_option",
        "sh_price_o20",
        "ta_sma50_pa",
        "ta_sma200_pa",
        "ta_highlow52w_b20h",
        "ta_beta_o1",
        "ta_rsi_40to70",
    ),
    sort="-relativevolume",
)

STRATEGY_B_VARIANT_PREFIX = "ta_beta_"
STRATEGY_B_VARIANT_VALUES: tuple[str, ...] = ("ta_beta_o1",)

STRATEGY_C_BASE = FinvizQuery(
    filters=(
        "earningsdate_prevweek",
        "geo_usa",
        "sh_opt_option",
        "sh_price_o10",
        "sh_avgvol_o500",
        "ta_change_u",
    ),
    sort="-change",
)

STRATEGY_C_EARNINGS_PREFIX = "earningsdate_"
STRATEGY_C_EARNINGS_VALUES: tuple[str, ...] = (
    "earningsdate_prevweek",
    "earningsdate_yesterday",
)

_STRATEGY_D_BASE_FILTERS = (
    "geo_usa",
    "sh_opt_option",
    "sh_price_o10",
    "sh_avgvol_o500",
    "ta_sma50_pa",
)
STRATEGY_D_SECTOR_PREFIX = "sec_"


def build_strategy_d_query(sector_filter: str) -> FinvizQuery:
    if (
        not sector_filter.startswith(STRATEGY_D_SECTOR_PREFIX)
        or not sector_filter.replace("_", "").isalnum()
    ):
        raise ValueError(f"Expected sec_* filter, got {sector_filter!r}")
    return FinvizQuery(
        filters=(sector_filter, *_STRATEGY_D_BASE_FILTERS),
        sort="-perf4w",
    )
