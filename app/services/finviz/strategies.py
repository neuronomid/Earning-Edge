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
STRATEGY_A_EARNINGS_VALUES: tuple[str, ...] = (
    "earningsdate_nextweek",
)

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
STRATEGY_B_VARIANT_VALUES: tuple[str, ...] = (
    "ta_beta_o1",
)
