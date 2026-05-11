from __future__ import annotations

from decimal import Decimal

from app.services.market_data.alpaca_stream_manager import (
    AlpacaStreamCredentials,
    AlpacaUserStream,
    OptionStreamQuote,
    StockStreamQuote,
    StreamPosition,
    build_market_update_event,
    parse_stream_positions,
)


def test_build_market_update_event_calculates_long_option_pnl() -> None:
    stream = AlpacaUserStream(
        AlpacaStreamCredentials(user_id="user-1", api_key="key", api_secret="secret")
    )
    stream.stock_quotes["AMD"] = StockStreamQuote(
        symbol="AMD",
        price=Decimal("101.25"),
        bid=Decimal("101.20"),
        ask=Decimal("101.30"),
        last=None,
        timestamp="2026-05-10T14:30:00Z",
        source="alpaca_iex_stream",
    )
    stream.option_quotes["AMD260619C00200000"] = OptionStreamQuote(
        symbol="AMD260619C00200000",
        bid=Decimal("1.20"),
        ask=Decimal("1.30"),
        mid=Decimal("1.25"),
        last=Decimal("1.24"),
        timestamp="2026-05-10T14:30:01Z",
        source="alpaca_option_stream",
    )

    event = build_market_update_event(
        stream,
        StreamPosition(
            position_id="pos-1",
            underlying_symbol="AMD",
            contract_id="AMD260619C00200000",
            option_symbol="AMD260619C00200000",
            option_type="CALL",
            position_side="LONG",
            quantity=2,
            entry_option_price=Decimal("1.00"),
            stop_loss=Decimal("0.50"),
            take_profit=Decimal("2.00"),
        ),
    )

    assert event["type"] == "market_update"
    assert event["stockSource"] == "alpaca_iex_stream"
    assert event["optionSource"] == "alpaca_option_stream"
    assert event["dataMode"] == "STREAMING"
    assert event["estimatedOptionPrice"] == 1.25
    assert event["unrealizedPnl"] == 50.0
    assert event["unrealizedPnlPercent"] == 25.0


def test_build_market_update_event_flags_short_stop_loss() -> None:
    stream = AlpacaUserStream(
        AlpacaStreamCredentials(user_id="user-1", api_key="key", api_secret="secret")
    )
    stream.option_quotes["AMD260619C00200000"] = OptionStreamQuote(
        symbol="AMD260619C00200000",
        bid=Decimal("1.80"),
        ask=Decimal("2.00"),
        mid=Decimal("1.90"),
        last=None,
        timestamp="2026-05-10T14:30:01Z",
        source="fallback_rest",
    )

    event = build_market_update_event(
        stream,
        StreamPosition(
            position_id="pos-1",
            underlying_symbol="AMD",
            contract_id="AMD260619C00200000",
            option_symbol="AMD260619C00200000",
            option_type="CALL",
            position_side="SHORT",
            quantity=1,
            entry_option_price=Decimal("1.00"),
            stop_loss=Decimal("1.50"),
        ),
    )

    assert event["dataMode"] == "FALLBACK_REST"
    assert event["triggerReason"] == "STOP_LOSS"
    assert event["positionStatus"] == "STOP_LOSS_TRIGGERED"
    assert event["unrealizedPnl"] == -90.0


def test_parse_stream_positions_builds_occ_symbol_from_position_details() -> None:
    positions = parse_stream_positions(
        {
            "positions": [
                {
                    "positionId": "pos-1",
                    "contractId": "manual:AMD:2026-06-19:CALL:200.00",
                    "underlyingSymbol": "AMD",
                    "optionType": "CALL",
                    "positionSide": "LONG",
                    "quantity": 1,
                    "entryOptionPrice": 1.25,
                    "strike": 200,
                    "expiration": "2026-06-19",
                }
            ]
        }
    )

    assert len(positions) == 1
    assert positions[0].option_symbol == "AMD260619C00200000"
