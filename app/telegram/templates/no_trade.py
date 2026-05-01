from __future__ import annotations


def render_no_trade(
    *,
    reason: str,
    watchlist_tickers: list[str] | tuple[str, ...],
    warning_text: str | None = None,
) -> str:
    lines: list[str] = []
    if warning_text:
        lines.extend([warning_text, ""])

    lines.extend(
        [
            "<b>Weekly Earnings Options Scan Complete</b>",
            "",
            "I scanned the top five large-cap companies reporting earnings next week.",
            "",
            "<b>Result:</b> No trade recommended.",
            "",
            "<b>Reason:</b>",
            reason,
            "",
            "<b>Best watchlist names:</b>",
        ]
    )
    if watchlist_tickers:
        lines.extend(
            f"{index}. {ticker}" for index, ticker in enumerate(watchlist_tickers[:3], start=1)
        )
    else:
        lines.append("1. None this week")
    return "\n".join(lines)
