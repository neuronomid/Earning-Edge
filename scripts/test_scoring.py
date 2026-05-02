"""
End-to-end scoring test: Finviz top-5 → yfinance → score_candidate → decision.
Run from project root:  python scripts/test_scoring.py
"""
from __future__ import annotations

import sys
import types as _pytypes
from pathlib import Path

# ── stub heavy modules BEFORE any app imports ─────────────────────────────────
# Prevents redis / structlog / datetime.UTC incompatibilities in Anaconda py310
_ROOT = Path(__file__).parent.parent

def _stub_package(name: str) -> _pytypes.ModuleType:
    """Stub a package but keep __path__ pointing at its real directory
    so sub-module imports (e.g. .types) still resolve."""
    m = _pytypes.ModuleType(name)
    real_dir = _ROOT / name.replace(".", "/")
    m.__path__ = [str(real_dir)]
    m.__package__ = name
    return m

def _stub_module(name: str) -> _pytypes.ModuleType:
    return _pytypes.ModuleType(name)

# Stub packages whose __init__.py pulls in heavy deps
for _name in ["app.services.market_data", "app.services.news"]:
    sys.modules.setdefault(_name, _stub_package(_name))

# Stub specific heavy leaf modules
for _name in [
    "app.services.market_data.service",
    "app.services.news.search",
    "app.services.news.fetcher",
    "app.services.run_lock",
    "app.core.logging",
]:
    sys.modules.setdefault(_name, _stub_module(_name))

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── real imports (types-only, no heavy deps) ──────────────────────────────────
import asyncio
from datetime import date
from decimal import Decimal

import yfinance as yf

from app.services.finviz.browser import FinvizBrowserClient
from app.services.finviz.extractor import FinvizExtractor
from app.services.market_data.types import (
    ConfidenceNote,
    MarketSnapshot,
    ReturnMetrics,
)
from app.services.news.types import NewsBrief
from app.scoring.final import score_candidate
from app.scoring.types import (
    CandidateContext,
    OptionContractInput,
    UserContext,
)

# ── user settings ─────────────────────────────────────────────────────────────
USER = UserContext(
    account_size=Decimal("50000"),
    risk_profile="Balanced",
    strategy_permission="long_and_short",
    max_contracts=3,
    has_valid_openrouter_api_key=True,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _dec(v: float | None) -> Decimal | None:
    return None if v is None else Decimal(str(round(v, 6)))


def _returns(closes: list[float], days: int) -> Decimal | None:
    if len(closes) < days + 1:
        return None
    ret = (closes[-1] - closes[-(days + 1)]) / closes[-(days + 1)]
    return _dec(ret)


def _build_return_metrics(closes: list[float]) -> ReturnMetrics:
    return ReturnMetrics(
        one_day=_returns(closes, 1),
        five_day=_returns(closes, 5),
        twenty_day=_returns(closes, 20),
        fifty_day=_returns(closes, 50),
    )


def _fetch_closes(ticker_sym: str, period: str = "3mo") -> list[float]:
    try:
        hist = yf.Ticker(ticker_sym).history(period=period)
        return [float(c) for c in hist["Close"].tolist()] if not hist.empty else []
    except Exception:
        return []


def _earnings_date(ticker_sym: str) -> date | None:
    try:
        cal = yf.Ticker(ticker_sym).calendar
        if cal is None:
            return None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed is None:
                return None
            if isinstance(ed, list) and ed:
                ed = ed[0]
            if isinstance(ed, date):
                return ed
            return ed.date() if hasattr(ed, "date") else None
        if hasattr(cal, "loc"):
            ed = cal.loc["Earnings Date"].iloc[0]
            return ed.date() if hasattr(ed, "date") else None
    except Exception:
        return None


SECTOR_ETF = {
    "Technology": "XLK", "Financial": "XLF", "Healthcare": "XLV",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
    "Industrials": "XLI", "Energy": "XLE", "Utilities": "XLU",
    "Real Estate": "XLRE", "Basic Materials": "XLB",
    "Communication Services": "XLC",
}


def _build_market_snapshot(ticker_sym: str) -> MarketSnapshot:
    tk = yf.Ticker(ticker_sym)
    info = tk.info or {}

    stock_closes = _fetch_closes(ticker_sym)
    spy_closes   = _fetch_closes("SPY")
    qqq_closes   = _fetch_closes("QQQ")

    sector      = info.get("sector")
    sector_etf  = SECTOR_ETF.get(sector or "")
    sector_closes = _fetch_closes(sector_etf) if sector_etf else []

    stock_ret  = _build_return_metrics(stock_closes)
    spy_ret    = _build_return_metrics(spy_closes)
    qqq_ret    = _build_return_metrics(qqq_closes)
    sector_ret = _build_return_metrics(sector_closes) if sector_closes else None

    current_price = _dec(info.get("currentPrice") or info.get("regularMarketPrice"))
    latest_vol    = info.get("regularMarketVolume") or info.get("volume")
    avg_vol       = _dec(info.get("averageVolume"))
    vol_ratio = (
        _dec(int(latest_vol) / float(avg_vol))
        if latest_vol and avg_vol and float(avg_vol) > 0
        else None
    )

    def _rs(a: Decimal | None, b: Decimal | None) -> Decimal | None:
        return a - b if a is not None and b is not None else None

    return MarketSnapshot(
        ticker=ticker_sym,
        as_of_date=date.today(),
        company_name=info.get("longName") or info.get("shortName"),
        sector=sector,
        sector_etf=sector_etf,
        market_cap=_dec(info.get("marketCap")),
        current_price=current_price,
        latest_volume=int(latest_vol) if latest_vol else None,
        average_volume_20d=avg_vol,
        volume_vs_average_20d=vol_ratio,
        stock_returns=stock_ret,
        spy_returns=spy_ret,
        qqq_returns=qqq_ret,
        sector_returns=sector_ret,
        relative_strength_vs_spy=_rs(stock_ret.five_day, spy_ret.five_day),
        relative_strength_vs_qqq=_rs(stock_ret.five_day, qqq_ret.five_day),
        relative_strength_vs_sector=_rs(
            stock_ret.five_day,
            sector_ret.five_day if sector_ret else None,
        ),
        av_news_sentiment=None,
        price_source="yfinance",
        overview_source="yfinance",
        sources=("yfinance",),
    )


def _build_option_chain(
    ticker_sym: str,
    earnings_dt: date,
) -> tuple[OptionContractInput, ...]:
    tk = yf.Ticker(ticker_sym)
    try:
        expiry_strs = tk.options
    except Exception:
        return ()

    valid = [
        e for e in expiry_strs
        if 0 <= (date.fromisoformat(e) - earnings_dt).days <= 30
    ]

    today = date.today()
    contracts: list[OptionContractInput] = []
    for expiry_str in valid[:3]:
        try:
            chain = tk.option_chain(expiry_str)
        except Exception:
            continue
        exp_date = date.fromisoformat(expiry_str)

        for pos_side, df, opt_type in [
            ("long",  chain.calls, "call"),
            ("long",  chain.puts,  "put"),
            ("short", chain.puts,  "put"),
            ("short", chain.calls, "call"),
        ]:
            for _, row in df.iterrows():
                strike = _dec(float(row.get("strike", 0) or 0))
                if not strike:
                    continue
                vol = row.get("volume")
                oi  = row.get("openInterest")
                contracts.append(OptionContractInput(
                    ticker=ticker_sym,
                    option_type=opt_type,       # type: ignore[arg-type]
                    position_side=pos_side,     # type: ignore[arg-type]
                    strike=strike,
                    expiry=exp_date,
                    bid=_dec(row.get("bid")),
                    ask=_dec(row.get("ask")),
                    implied_volatility=_dec(row.get("impliedVolatility")),
                    volume=int(vol) if vol and vol == vol else None,
                    open_interest=int(oi) if oi and oi == oi else None,
                    source="yfinance",
                    quote_timestamp=today,
                    is_tradable=True,
                    is_stale=False,
                ))
    return tuple(contracts)


def _stub_news() -> NewsBrief:
    return NewsBrief(
        bullish_evidence=["Earnings approaching — screening stub"],
        bearish_evidence=[],
        neutral_contextual_evidence=["No live LLM analysis in test mode"],
        key_uncertainty="No live news analysis — stub used for test",
        news_confidence=50,
    )


def _bar(label: str, score: int, width: int = 28) -> str:
    filled = int(score / 100 * width)
    bar = ("#" * filled).ljust(width)
    return f"  {label:<18} [{bar}] {score:3d}/100"


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("Fetching Finviz top-5 candidates...")
    extractor = FinvizExtractor(FinvizBrowserClient(headless=True, timeout_ms=30000))
    candidates = await extractor.get_top_five()
    print(f"Got: {[c.ticker for c in candidates]}\n")

    for rec in candidates:
        ticker = rec.ticker
        print(f"{'='*62}")
        print(f"  {ticker}  —  {rec.company_name}")
        print(f"{'='*62}")

        snap         = _build_market_snapshot(ticker)
        earnings_dt  = _earnings_date(ticker)

        if earnings_dt is None:
            print("  [SKIP] earnings date unavailable\n")
            continue

        chain = _build_option_chain(ticker, earnings_dt)

        context = CandidateContext(
            ticker=ticker,
            company_name=rec.company_name or ticker,
            earnings_date=earnings_dt,
            earnings_timing="unknown",
            market_snapshot=snap,
            news_brief=_stub_news(),
            option_chain=chain,
            verified_earnings_date=True,
            identity_verified=True,
        )

        ev = score_candidate(context, USER)
        d  = ev.direction
        c  = ev.confidence
        ch = ev.chosen_contract

        print(f"  Earnings : {earnings_dt}   Price : {snap.current_price}   "
              f"Sector : {snap.sector}")
        print(f"  Options  : {len(chain)} contracts loaded")
        print()
        print(_bar("Confidence",   c.score))
        print(_bar("Direction",    d.score) + f"   [{d.classification}  bias={float(d.bias):.3f}]")
        if ch:
            print(_bar("Contract",     ch.score))
        print(_bar("FINAL SCORE",  ev.final_score))
        print()
        print(f"  ACTION  >>>  {ev.action.upper()}")

        if ch:
            ct = ch.contract
            premium_str = f"${ct.ask}" if ct.ask else "n/a"
            be_str = (
                f"${ch.breakeven}  ({float(ch.breakeven_move_percent)*100:.1f}% move needed)"
                if ch.breakeven and ch.breakeven_move_percent else "n/a"
            )
            print(f"\n  Best contract : {ct.strategy}")
            print(f"  Strike / Exp  : {ct.strike}  /  {ct.expiry}")
            print(f"  Ask           : {premium_str}  per contract = "
                  f"${float(ct.ask)*100:.0f}" if ct.ask else f"  Ask           : {premium_str}")
            print(f"  Breakeven     : {be_str}")
        else:
            print("\n  No viable contract found.")

        if c.blockers:
            print(f"\n  Blockers : {'; '.join(c.blockers)}")
        if c.notes:
            print(f"  Notes    : {'; '.join(list(c.notes)[:3])}")

        if ev.reasons:
            print("\n  Key reasons:")
            for r in list(ev.reasons)[:4]:
                print(f"    * {r}")
        print()

    print("Done.")


asyncio.run(main())
