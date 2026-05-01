from __future__ import annotations


def render_scan_started() -> str:
    return "🧠 Starting a fresh earnings-options scan now."


def render_scan_complete_recommendation() -> str:
    return "✅ Scan complete. Here is the strongest setup I found."


def render_scan_complete_watchlist() -> str:
    return "✅ Scan complete. I found one name worth watching, but not sizing yet."


def render_weekly_scan_ready(*, trigger_type: str, action: str) -> str:
    if trigger_type == "cron":
        if action == "no_trade":
            return (
                "📊 Weekly scan is ready.\n\n"
                "I checked the top 5 large-cap companies reporting earnings next week, "
                "but none of the setups cleared the bar for a trade."
            )
        return (
            "📊 Weekly scan is ready.\n\n"
            "I checked the top 5 large-cap companies reporting earnings next week and "
            "found one setup that looks stronger than the rest."
        )
    if action == "watchlist":
        return render_scan_complete_watchlist()
    if action == "no_trade":
        return (
            "📊 Scan complete.\n\n"
            "No trade looks strong enough this time. The best setups had either weak "
            "direction, poor option pricing, or not enough data confidence."
        )
    return render_scan_complete_recommendation()
