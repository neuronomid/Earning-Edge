from __future__ import annotations

from decimal import Decimal

from app.scoring.types import (
    CandidateContext,
    DirectionClassification,
    DirectionResult,
    ScoreFactor,
    clamp_int,
    round_decimal,
)

ZERO = Decimal("0")
ONE = Decimal("1")
HALF = Decimal("0.5")
MISSING_UNIT = Decimal("0.45")

_DIRECTION_WEIGHTS: dict[str, int] = {
    "trend alignment": 20,
    "relative strength": 15,
    "volume confirmation": 10,
    "news/catalyst quality": 15,
    "earnings expectation context": 15,
    "market/sector environment": 10,
    "price structure": 10,
    "data confidence": 5,
}


def score_direction(
    candidate: CandidateContext, *, data_confidence_score: int
) -> DirectionResult:
    signals = {
        "trend alignment": _trend_signal(candidate),
        "relative strength": _relative_strength_signal(candidate),
        "volume confirmation": _volume_signal(candidate),
        "news/catalyst quality": _news_signal(candidate),
        "earnings expectation context": _earnings_signal(candidate),
        "market/sector environment": _market_signal(candidate),
        "price structure": _price_structure_signal(candidate),
    }

    signed_total = ZERO
    for name, signal in signals.items():
        if signal is None:
            continue
        signed_total += Decimal(_DIRECTION_WEIGHTS[name]) * signal
    total_weight = sum(
        weight for name, weight in _DIRECTION_WEIGHTS.items() if name != "data confidence"
    )
    bias = signed_total / Decimal(total_weight)

    if candidate.market_snapshot.current_price is None or data_confidence_score < 40:
        classification: DirectionClassification = "avoid"
    elif bias >= Decimal("0.12"):
        classification = "bullish"
    elif bias <= Decimal("-0.12"):
        classification = "bearish"
    else:
        classification = "neutral"

    polarity = 1
    if bias < ZERO:
        polarity = -1

    factors = (
        *(
            ScoreFactor(
                name=name,
                score=_factor_points(signal, _DIRECTION_WEIGHTS[name], polarity),
                weight=_DIRECTION_WEIGHTS[name],
                detail=_factor_detail(name, signal),
            )
            for name, signal in signals.items()
        ),
        ScoreFactor(
            name="data confidence",
            score=_confidence_factor_points(data_confidence_score),
            weight=_DIRECTION_WEIGHTS["data confidence"],
            detail=f"data confidence landed at {data_confidence_score}/100",
        ),
    )

    score = sum(factor.score for factor in factors)
    if classification == "neutral":
        score = min(score, 54)
    score = clamp_int(score)

    reasons = tuple(
        factor.detail
        for factor in sorted(factors, key=lambda item: item.score, reverse=True)[:3]
    )

    return DirectionResult(
        classification=classification,
        bias=bias,
        score=score,
        factors=factors,
        reasons=reasons,
    )


def _factor_points(signal: Decimal | None, weight: int, polarity: int) -> int:
    if signal is None:
        return round_decimal(Decimal(weight) * MISSING_UNIT)

    aligned = signal * Decimal(polarity)
    unit = max(ZERO, min(ONE, (aligned + ONE) / Decimal("2")))
    return round_decimal(Decimal(weight) * unit)


def _confidence_factor_points(score: int) -> int:
    if score >= 85:
        return 5
    if score >= 70:
        return 4
    if score >= 55:
        return 3
    if score >= 40:
        return 2
    return 0


def _factor_detail(name: str, signal: Decimal | None) -> str:
    if signal is None:
        return f"{name} was only partially available"
    if signal >= Decimal("0.35"):
        return f"{name} was clearly supportive"
    if signal <= Decimal("-0.35"):
        return f"{name} argued against the trade thesis"
    return f"{name} was mixed rather than decisive"


def _trend_signal(candidate: CandidateContext) -> Decimal | None:
    returns = candidate.market_snapshot.stock_returns
    signals = (
        _signed_strength(returns.one_day, Decimal("0.02")),
        _signed_strength(returns.five_day, Decimal("0.04")),
        _signed_strength(returns.twenty_day, Decimal("0.08")),
        _signed_strength(returns.fifty_day, Decimal("0.15")),
    )
    return _weighted_mean(signals, (1, 3, 3, 2))


def _relative_strength_signal(candidate: CandidateContext) -> Decimal | None:
    snapshot = candidate.market_snapshot
    signals = (
        _signed_strength(snapshot.relative_strength_vs_spy, Decimal("0.03")),
        _signed_strength(snapshot.relative_strength_vs_qqq, Decimal("0.03")),
        _signed_strength(snapshot.relative_strength_vs_sector, Decimal("0.03")),
    )
    return _mean(signals)


def _volume_signal(candidate: CandidateContext) -> Decimal | None:
    ratio = candidate.market_snapshot.volume_vs_average_20d
    if ratio is None:
        return None
    movement = _signed_strength(
        candidate.market_snapshot.stock_returns.one_day
        or candidate.market_snapshot.stock_returns.five_day,
        Decimal("0.02"),
    )
    if movement is None:
        return None
    participation = _signed_strength(ratio - Decimal("1"), Decimal("0.35"))
    if participation is None:
        return None
    if participation < ZERO:
        return participation / Decimal("2")
    return movement * participation


def _news_signal(candidate: CandidateContext) -> Decimal:
    bullish = Decimal(len(candidate.news_brief.bullish_evidence))
    bearish = Decimal(len(candidate.news_brief.bearish_evidence))
    total = bullish + bearish
    if total == 0:
        return ZERO
    balance = (bullish - bearish) / total
    confidence = Decimal(candidate.news_brief.news_confidence) / Decimal("100")
    return max(Decimal("-1"), min(Decimal("1"), balance * confidence))


def _earnings_signal(candidate: CandidateContext) -> Decimal:
    previous_move = candidate.previous_earnings_move_percent
    if previous_move is None:
        return _news_signal(candidate) * Decimal("0.35")

    signal = _signed_strength(previous_move, Decimal("0.05")) or ZERO
    expected_move = candidate.expected_move_percent
    if expected_move is None or expected_move <= ZERO:
        return signal

    if abs(previous_move) >= expected_move:
        return signal
    return signal * Decimal("0.7")


def _market_signal(candidate: CandidateContext) -> Decimal | None:
    returns = [
        _signed_strength(candidate.market_snapshot.spy_returns.five_day, Decimal("0.02")),
        _signed_strength(candidate.market_snapshot.qqq_returns.five_day, Decimal("0.025")),
    ]
    if candidate.market_snapshot.sector_returns is not None:
        returns.append(
            _signed_strength(candidate.market_snapshot.sector_returns.five_day, Decimal("0.025"))
        )
    return _mean(tuple(returns))


def _price_structure_signal(candidate: CandidateContext) -> Decimal | None:
    returns = candidate.market_snapshot.stock_returns
    observed = [
        value
        for value in (returns.one_day, returns.five_day, returns.twenty_day, returns.fifty_day)
        if value is not None
    ]
    if not observed:
        return None

    signs = [1 if value > ZERO else -1 if value < ZERO else 0 for value in observed]
    consistency = Decimal(abs(sum(signs))) / Decimal(len(signs))
    dominant = Decimal(sum(signs))
    if dominant == ZERO:
        return ZERO
    magnitude = min(ONE, sum(abs(value) for value in observed) / Decimal("0.20"))
    direction = ONE if dominant > ZERO else Decimal("-1")
    return direction * consistency * magnitude


def _signed_strength(value: Decimal | None, threshold: Decimal) -> Decimal | None:
    if value is None:
        return None
    normalized = value / threshold
    return max(Decimal("-1"), min(Decimal("1"), normalized))


def _mean(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / Decimal(len(present))


def _weighted_mean(
    values: tuple[Decimal | None, ...], weights: tuple[int, ...]
) -> Decimal | None:
    weighted_total = ZERO
    total_weight = 0
    for value, weight in zip(values, weights, strict=True):
        if value is None:
            continue
        weighted_total += value * Decimal(weight)
        total_weight += weight
    if total_weight == 0:
        return None
    return weighted_total / Decimal(total_weight)
