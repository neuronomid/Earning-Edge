from __future__ import annotations

from decimal import Decimal

from app.services.market_data.types import PriceBar, ReturnMetrics

_ZERO = Decimal("0")


def compute_returns(history: tuple[PriceBar, ...]) -> ReturnMetrics:
    return ReturnMetrics(
        one_day=compute_return(history, periods=1),
        five_day=compute_return(history, periods=5),
        twenty_day=compute_return(history, periods=20),
        fifty_day=compute_return(history, periods=50),
    )


def compute_return(history: tuple[PriceBar, ...], *, periods: int) -> Decimal | None:
    if len(history) <= periods:
        return None

    current = history[-1].close
    previous = history[-(periods + 1)].close
    if previous == _ZERO:
        return None
    return (current / previous) - Decimal("1")


def average_volume(history: tuple[PriceBar, ...], *, window: int = 20) -> Decimal | None:
    if len(history) <= window:
        return None

    sample = history[-(window + 1) : -1]
    volumes = [Decimal(item.volume) for item in sample if item.volume is not None]
    if len(volumes) != window:
        return None
    return sum(volumes) / Decimal(window)


def volume_vs_average(history: tuple[PriceBar, ...], *, window: int = 20) -> Decimal | None:
    if not history or history[-1].volume is None:
        return None

    avg = average_volume(history, window=window)
    if avg in {None, _ZERO}:
        return None
    return Decimal(history[-1].volume) / avg


def relative_strength(
    stock_returns: ReturnMetrics,
    benchmark_returns: ReturnMetrics,
    *,
    window: str = "twenty_day",
) -> Decimal | None:
    stock = getattr(stock_returns, window)
    benchmark = getattr(benchmark_returns, window)
    if stock is None or benchmark is None:
        return None
    return stock - benchmark
