from __future__ import annotations

from app.services.finviz.query import FinvizQuery

STRATEGY_A_BASE = FinvizQuery(
    filters=(
        "cap_midover",
        "earningsdate_thisweek",
        "exch_nasd",
        "exch_nyse",
        "fa_epsqoq_pos",
        "fa_epssurprise_pos",
        "fa_revenuesurprise_pos",
        "fa_salesqoq_pos",
        "geo_usa",
        "sh_avgvol_o1000",
        "sh_opt_option",
        "sh_price_o20",
        "sh_relvol_o1.5",
        "an_recom_buybetter",
        "targetprice_above",
        "ta_sma20_pa",
        "ta_sma50_pa",
        "ta_sma200_pa",
        "ta_perf_qup",
        "ta_rsi_50to70",
    ),
    sort="-relativevolume",
)

STRATEGY_A_EARNINGS_PREFIX = "earningsdate_"
STRATEGY_A_EARNINGS_VALUES: tuple[str, ...] = (
    "earningsdate_thisweek",
    "earningsdate_nextweek",
)

STRATEGY_B_BASE = FinvizQuery(
    filters=(
        "cap_midover",
        "exch_nasd",
        "exch_nyse",
        "geo_usa",
        "sh_avgvol_o2000",
        "sh_opt_option",
        "sh_price_o20",
        "sh_short_u20",
        "sh_insidertrans_pos",
        "ta_sma200_pa",
        "ta_sma50_pa",
        "ta_highlow52w_b10h",
        "ta_perf_yup",
        "ta_perf2_hup",
        "ta_rsi_40to60",
        "ta_volatility_wo4",
        "ta_pattern_channelup2",
        "ta_beta_o1",
        "sh_relvol_o1",
    ),
    sort="-perfhalf",
)

STRATEGY_B_PATTERN_PREFIX = "ta_pattern_"
STRATEGY_B_PATTERN_VALUES: tuple[str, ...] = (
    "ta_pattern_channelup2",
    "ta_pattern_triangleascending",
)
