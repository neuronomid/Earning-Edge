from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from app.core.logging import get_logger
from app.services.market_data.alpaca_stock_client import AlpacaStockClient
from app.services.options.alpaca_client import (
    AlpacaAuthenticationError,
    AlpacaOptionsClient,
    AlpacaUnavailableError,
    build_occ_symbol,
)

try:
    import msgpack
except ImportError:  # pragma: no cover - covered by fallback behavior in runtime
    msgpack = None  # type: ignore[assignment]


log = get_logger("alpaca_stream")

STOCK_STREAM_URL = "wss://stream.data.alpaca.markets/v2/{feed}"
OPTION_STREAM_URL = "wss://stream.data.alpaca.markets/v1beta1/{feed}"
STREAM_QUEUE_LIMIT = 200
FALLBACK_INTERVAL_SECONDS = 5


@dataclass(frozen=True, slots=True)
class AlpacaStreamCredentials:
    user_id: str
    api_key: str
    api_secret: str
    stock_feed: str = "iex"
    option_feed: str = "indicative"


@dataclass(slots=True)
class StreamPosition:
    position_id: str
    underlying_symbol: str
    contract_id: str
    option_symbol: str
    option_type: str
    position_side: str
    quantity: int
    entry_option_price: Decimal
    entry_underlying_price: Decimal | None = None
    strike: Decimal | None = None
    expiration: date | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    fallback_bid: Decimal | None = None
    fallback_ask: Decimal | None = None
    fallback_mid: Decimal | None = None
    fallback_last: Decimal | None = None


@dataclass(frozen=True, slots=True)
class StockStreamQuote:
    symbol: str
    price: Decimal
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    timestamp: str
    source: str


@dataclass(frozen=True, slots=True)
class OptionStreamQuote:
    symbol: str
    bid: Decimal | None
    ask: Decimal | None
    mid: Decimal | None
    last: Decimal | None
    timestamp: str
    source: str


class AlpacaStreamManager:
    """Shares server-side Alpaca market-data streams across dashboard clients."""

    def __init__(self) -> None:
        self._streams: dict[str, AlpacaUserStream] = {}
        self._client_to_stream: dict[str, str] = {}
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def connect_client(self) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        client_id = f"client-{id(asyncio.current_task())}-{datetime.now(UTC).timestamp()}"
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=STREAM_QUEUE_LIMIT)
        async with self._lock:
            self._queues[client_id] = queue
        log.info("dashboard_stream.frontend_connected", client_id=client_id)
        return client_id, queue

    async def disconnect_client(self, client_id: str) -> None:
        async with self._lock:
            self._queues.pop(client_id, None)
            stream_key = self._client_to_stream.pop(client_id, None)
            stream = self._streams.get(stream_key) if stream_key else None
        if stream is not None:
            await stream.remove_client(client_id)
            if stream.is_empty:
                await stream.stop()
                async with self._lock:
                    self._streams.pop(stream_key or "", None)
        log.info("dashboard_stream.frontend_disconnected", client_id=client_id)

    async def subscribe(
        self,
        client_id: str,
        credentials: AlpacaStreamCredentials,
        positions: Iterable[StreamPosition],
    ) -> None:
        queue = self._queues.get(client_id)
        if queue is None:
            raise RuntimeError("frontend stream client was not registered")

        async with self._lock:
            stream = self._streams.get(credentials.user_id)
            if stream is None:
                stream = AlpacaUserStream(credentials)
                self._streams[credentials.user_id] = stream
            self._client_to_stream[client_id] = credentials.user_id

        await stream.add_client(client_id, queue)
        await stream.subscribe(client_id, tuple(positions))

    async def unsubscribe_positions(self, client_id: str, position_ids: Iterable[str]) -> None:
        stream_key = self._client_to_stream.get(client_id)
        if not stream_key:
            return
        stream = self._streams.get(stream_key)
        if stream is None:
            return
        await stream.unsubscribe_positions(client_id, set(position_ids))


class AlpacaUserStream:
    def __init__(self, credentials: AlpacaStreamCredentials) -> None:
        self.credentials = credentials
        self.clients: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self.client_positions: dict[str, dict[str, StreamPosition]] = defaultdict(dict)
        self.stock_quotes: dict[str, StockStreamQuote] = {}
        self.option_quotes: dict[str, OptionStreamQuote] = {}
        self._stock_task: asyncio.Task[None] | None = None
        self._option_task: asyncio.Task[None] | None = None
        self._fallback_task: asyncio.Task[None] | None = None
        self._desired_changed = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._stock_stream_ok = False
        self._option_stream_ok = False
        self._stock_fallback_reason: str | None = None
        self._option_fallback_reason: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.clients

    async def add_client(
        self,
        client_id: str,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        async with self._lock:
            self.clients[client_id] = queue
        await self._ensure_tasks()

    async def remove_client(self, client_id: str) -> None:
        async with self._lock:
            self.clients.pop(client_id, None)
            self.client_positions.pop(client_id, None)
            self._desired_changed.set()

    async def subscribe(self, client_id: str, positions: tuple[StreamPosition, ...]) -> None:
        async with self._lock:
            self.client_positions[client_id] = {
                position.position_id: position for position in positions
            }
            self._desired_changed.set()
        log.info(
            "dashboard_stream.subscribed",
            user_id=self.credentials.user_id,
            client_id=client_id,
            stocks=sorted(self.stock_symbols),
            options=sorted(self.option_symbols),
        )
        await self._ensure_tasks()
        await self._broadcast_all()

    async def unsubscribe_positions(self, client_id: str, position_ids: set[str]) -> None:
        async with self._lock:
            positions = self.client_positions.get(client_id, {})
            for position_id in position_ids:
                positions.pop(position_id, None)
            self._desired_changed.set()

    async def stop(self) -> None:
        self._stop_event.set()
        tasks = [self._stock_task, self._option_task, self._fallback_task]
        for task in tasks:
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True)

    @property
    def positions(self) -> list[tuple[str, StreamPosition]]:
        return [
            (client_id, position)
            for client_id, positions in self.client_positions.items()
            for position in positions.values()
        ]

    @property
    def stock_symbols(self) -> set[str]:
        return {position.underlying_symbol for _, position in self.positions}

    @property
    def option_symbols(self) -> set[str]:
        return {position.option_symbol for _, position in self.positions if position.option_symbol}

    async def _ensure_tasks(self) -> None:
        if self._stock_task is None or self._stock_task.done():
            self._stock_task = asyncio.create_task(self._stock_loop())
        if self._option_task is None or self._option_task.done():
            self._option_task = asyncio.create_task(self._option_loop())
        if self._fallback_task is None or self._fallback_task.done():
            self._fallback_task = asyncio.create_task(self._fallback_loop())

    async def _stock_loop(self) -> None:
        sent_symbols: set[str] = set()
        while not self._stop_event.is_set():
            if not self.stock_symbols:
                sent_symbols.clear()
                await self._wait_for_desired_change()
                continue

            url = STOCK_STREAM_URL.format(feed=self.credentials.stock_feed)
            try:
                async with websockets.connect(url) as websocket:
                    log.info(
                        "alpaca_stock_stream.connected",
                        user_id=self.credentials.user_id,
                        feed=self.credentials.stock_feed,
                    )
                    await websocket.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": self.credentials.api_key,
                                "secret": self.credentials.api_secret,
                            }
                        )
                    )
                    self._stock_stream_ok = True
                    self._stock_fallback_reason = None
                    log.info("alpaca_stock_stream.authenticated", user_id=self.credentials.user_id)

                    while not self._stop_event.is_set() and self.stock_symbols:
                        sent_symbols = await self._sync_stock_subscriptions(
                            websocket,
                            sent_symbols,
                        )
                        try:
                            raw = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        except TimeoutError:
                            continue
                        await self._handle_stock_payload(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._stock_stream_ok = False
                self._stock_fallback_reason = _safe_error(exc)
                log.warning(
                    "alpaca_stock_stream.fallback_polling_started",
                    user_id=self.credentials.user_id,
                    reason=self._stock_fallback_reason,
                )
                await self._broadcast_all()
                await asyncio.sleep(2)

    async def _sync_stock_subscriptions(
        self,
        websocket: Any,
        sent_symbols: set[str],
    ) -> set[str]:
        desired = self.stock_symbols
        add = sorted(desired - sent_symbols)
        remove = sorted(sent_symbols - desired)
        if add:
            await websocket.send(json.dumps({"action": "subscribe", "quotes": add, "trades": add}))
            log.info(
                "alpaca_stock_stream.subscribed",
                user_id=self.credentials.user_id,
                symbols=add,
            )
        if remove:
            await websocket.send(
                json.dumps({"action": "unsubscribe", "quotes": remove, "trades": remove})
            )
        return set(desired)

    async def _option_loop(self) -> None:
        if msgpack is None:
            self._option_stream_ok = False
            self._option_fallback_reason = "msgpack is not installed for Alpaca option streaming"
            log.warning(
                "alpaca_option_stream.fallback_polling_started",
                user_id=self.credentials.user_id,
                reason=self._option_fallback_reason,
            )
            await self._stop_event.wait()
            return

        sent_symbols: set[str] = set()
        while not self._stop_event.is_set():
            if not self.option_symbols:
                sent_symbols.clear()
                await self._wait_for_desired_change()
                continue

            url = OPTION_STREAM_URL.format(feed=self.credentials.option_feed)
            try:
                async with websockets.connect(
                    url,
                    additional_headers={"Content-Type": "application/msgpack"},
                ) as websocket:
                    log.info(
                        "alpaca_option_stream.connected",
                        user_id=self.credentials.user_id,
                        feed=self.credentials.option_feed,
                    )
                    await websocket.send(
                        msgpack.packb(
                            {
                                "action": "auth",
                                "key": self.credentials.api_key,
                                "secret": self.credentials.api_secret,
                            },
                            use_bin_type=True,
                        )
                    )
                    self._option_stream_ok = True
                    self._option_fallback_reason = None
                    log.info("alpaca_option_stream.authenticated", user_id=self.credentials.user_id)

                    while not self._stop_event.is_set() and self.option_symbols:
                        sent_symbols = await self._sync_option_subscriptions(
                            websocket,
                            sent_symbols,
                        )
                        try:
                            raw = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        except TimeoutError:
                            continue
                        await self._handle_option_payload(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._option_stream_ok = False
                self._option_fallback_reason = _safe_error(exc)
                log.warning(
                    "alpaca_option_stream.fallback_polling_started",
                    user_id=self.credentials.user_id,
                    reason=self._option_fallback_reason,
                )
                await self._broadcast_all()
                await asyncio.sleep(2)

    async def _sync_option_subscriptions(
        self,
        websocket: Any,
        sent_symbols: set[str],
    ) -> set[str]:
        desired = self.option_symbols
        add = sorted(desired - sent_symbols)
        remove = sorted(sent_symbols - desired)
        if msgpack is None:
            return sent_symbols
        if add:
            await websocket.send(
                msgpack.packb(
                    {"action": "subscribe", "quotes": add, "trades": add},
                    use_bin_type=True,
                )
            )
            log.info(
                "alpaca_option_stream.subscribed",
                user_id=self.credentials.user_id,
                contracts=add,
            )
        if remove:
            await websocket.send(
                msgpack.packb(
                    {"action": "unsubscribe", "quotes": remove, "trades": remove},
                    use_bin_type=True,
                )
            )
        return set(desired)

    async def _fallback_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._poll_fallback_quotes()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(
                    "alpaca_stream.fallback_poll_failed",
                    user_id=self.credentials.user_id,
                    reason=_safe_error(exc),
                )
            await asyncio.sleep(FALLBACK_INTERVAL_SECONDS)

    async def _poll_fallback_quotes(self) -> None:
        if not self.positions:
            return
        stock_symbols = sorted(self.stock_symbols)
        missing_stock_symbols = [
            symbol for symbol in stock_symbols if symbol not in self.stock_quotes
        ]
        if not self._stock_stream_ok or missing_stock_symbols:
            stock_client = AlpacaStockClient(feed=self.credentials.stock_feed)
            for symbol in stock_symbols if not self._stock_stream_ok else missing_stock_symbols:
                try:
                    quote = await stock_client.fetch_quote(
                        symbol,
                        api_key=self.credentials.api_key,
                        api_secret=self.credentials.api_secret,
                        feed=self.credentials.stock_feed,
                    )
                except Exception as exc:
                    self._stock_fallback_reason = _safe_error(exc)
                    continue
                self.stock_quotes[symbol] = StockStreamQuote(
                    symbol=quote.symbol,
                    price=quote.price,
                    bid=quote.bid,
                    ask=quote.ask,
                    last=None,
                    timestamp=quote.timestamp or _now_iso(),
                    source=f"alpaca_{quote.feed}_rest",
                )

        option_symbols = sorted(self.option_symbols)
        missing_option_symbols = [
            symbol for symbol in option_symbols if symbol not in self.option_quotes
        ]
        if not self._option_stream_ok or missing_option_symbols:
            await self._poll_option_fallback_quotes(
                None if not self._option_stream_ok else set(missing_option_symbols)
            )

        await self._broadcast_all()

    async def _poll_option_fallback_quotes(self, required_symbols: set[str] | None = None) -> None:
        grouped: dict[str, set[str]] = defaultdict(set)
        for _, position in self.positions:
            if position.option_symbol and (
                required_symbols is None or position.option_symbol in required_symbols
            ):
                grouped[position.underlying_symbol].add(position.option_symbol)

        client = AlpacaOptionsClient(feed=self.credentials.option_feed)
        for underlying, symbols in grouped.items():
            try:
                contracts = await client.fetch_chain(
                    underlying,
                    api_key=self.credentials.api_key,
                    api_secret=self.credentials.api_secret,
                    expiry_window_days=60,
                    today=date.today(),
                    symbols=sorted(symbols),
                )
            except (AlpacaAuthenticationError, AlpacaUnavailableError, RuntimeError) as exc:
                self._option_fallback_reason = _safe_error(exc)
                continue

            for contract in contracts:
                if not contract.symbol:
                    continue
                self.option_quotes[contract.symbol] = OptionStreamQuote(
                    symbol=contract.symbol,
                    bid=contract.bid,
                    ask=contract.ask,
                    mid=contract.mid,
                    last=contract.last_trade_price,
                    timestamp=_now_iso(),
                    source="fallback_rest",
                )

    async def _handle_stock_payload(self, raw: str | bytes) -> None:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        for message in _message_list(payload):
            message_type = message.get("T")
            if message_type == "error":
                self._stock_stream_ok = False
                self._stock_fallback_reason = str(message.get("msg") or "Alpaca stock stream error")
                log.warning(
                    "alpaca_stock_stream.error",
                    user_id=self.credentials.user_id,
                    code=message.get("code"),
                    reason=self._stock_fallback_reason,
                )
                continue
            if message_type not in {"q", "t"}:
                continue
            symbol = str(message.get("S") or "").upper()
            if not symbol:
                continue
            previous = self.stock_quotes.get(symbol)
            if message_type == "q":
                bid = _positive_decimal(message.get("bp"))
                ask = _positive_decimal(message.get("ap"))
                price = _midpoint(bid, ask) or ask or bid
                if price is None:
                    continue
                quote = StockStreamQuote(
                    symbol=symbol,
                    price=price,
                    bid=bid,
                    ask=ask,
                    last=previous.last if previous else None,
                    timestamp=_to_text(message.get("t")) or _now_iso(),
                    source=f"alpaca_{self.credentials.stock_feed}_stream",
                )
            else:
                last = _positive_decimal(message.get("p"))
                if last is None:
                    continue
                quote = StockStreamQuote(
                    symbol=symbol,
                    price=last,
                    bid=previous.bid if previous else None,
                    ask=previous.ask if previous else None,
                    last=last,
                    timestamp=_to_text(message.get("t")) or _now_iso(),
                    source=f"alpaca_{self.credentials.stock_feed}_stream",
                )
            self.stock_quotes[symbol] = quote
            await self._broadcast_for_stock(symbol)

    async def _handle_option_payload(self, raw: str | bytes) -> None:
        if msgpack is None:
            return
        payload = msgpack.unpackb(raw, raw=False) if isinstance(raw, bytes) else json.loads(raw)
        for message in _message_list(payload):
            message_type = message.get("T")
            if message_type == "error":
                self._option_stream_ok = False
                self._option_fallback_reason = str(
                    message.get("msg") or "Alpaca option stream error"
                )
                log.warning(
                    "alpaca_option_stream.error",
                    user_id=self.credentials.user_id,
                    code=message.get("code"),
                    reason=self._option_fallback_reason,
                )
                continue
            if message_type not in {"q", "t"}:
                continue
            symbol = str(message.get("S") or "").upper()
            if not symbol:
                continue
            previous = self.option_quotes.get(symbol)
            if message_type == "q":
                bid = _positive_decimal(message.get("bp"))
                ask = _positive_decimal(message.get("ap"))
                quote = OptionStreamQuote(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    mid=_midpoint(bid, ask),
                    last=previous.last if previous else None,
                    timestamp=_to_text(message.get("t")) or _now_iso(),
                    source="alpaca_option_stream",
                )
            else:
                last = _positive_decimal(message.get("p"))
                quote = OptionStreamQuote(
                    symbol=symbol,
                    bid=previous.bid if previous else None,
                    ask=previous.ask if previous else None,
                    mid=previous.mid if previous else None,
                    last=last,
                    timestamp=_to_text(message.get("t")) or _now_iso(),
                    source="alpaca_option_stream",
                )
            self.option_quotes[symbol] = quote
            await self._broadcast_for_option(symbol)

    async def _broadcast_for_stock(self, symbol: str) -> None:
        for client_id, position in self.positions:
            if position.underlying_symbol == symbol:
                await self._send_event(client_id, build_market_update_event(self, position))

    async def _broadcast_for_option(self, option_symbol: str) -> None:
        for client_id, position in self.positions:
            if position.option_symbol == option_symbol:
                await self._send_event(client_id, build_market_update_event(self, position))

    async def _broadcast_all(self) -> None:
        for client_id, position in self.positions:
            await self._send_event(client_id, build_market_update_event(self, position))

    async def _send_event(self, client_id: str, event: dict[str, Any]) -> None:
        queue = self.clients.get(client_id)
        if queue is None:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            _ = queue.get_nowait()
            queue.put_nowait(event)

    async def _wait_for_desired_change(self) -> None:
        self._desired_changed.clear()
        wait_stop = asyncio.create_task(self._stop_event.wait())
        wait_change = asyncio.create_task(self._desired_changed.wait())
        done, pending = await asyncio.wait(
            {wait_stop, wait_change},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()


def build_market_update_event(
    stream: AlpacaUserStream,
    position: StreamPosition,
) -> dict[str, Any]:
    stock = stream.stock_quotes.get(position.underlying_symbol)
    option = stream.option_quotes.get(position.option_symbol)
    option_bid = option.bid if option else position.fallback_bid
    option_ask = option.ask if option else position.fallback_ask
    option_mid = option.mid if option else position.fallback_mid
    option_last = option.last if option else position.fallback_last
    estimated = _option_price(
        option_bid,
        option_ask,
        option_mid,
        option_last,
        position.position_side,
    )
    basis = position.entry_option_price * Decimal(max(position.quantity, 1)) * Decimal("100")
    pnl: Decimal | None = None
    pnl_percent: Decimal | None = None
    if estimated is not None:
        current = estimated * Decimal(max(position.quantity, 1)) * Decimal("100")
        pnl = current - basis if position.position_side == "LONG" else basis - current
        pnl_percent = Decimal("0") if basis == 0 else (pnl / basis) * Decimal("100")

    trigger_reason = _trigger_reason(position, estimated)
    if trigger_reason:
        log.info(
            "dashboard_stream.position_triggered",
            user_id=stream.credentials.user_id,
            position_id=position.position_id,
            trigger_reason=trigger_reason,
        )

    option_source = option.source if option else "fallback_rest"
    if stream._option_fallback_reason and option is None:
        option_source = "fallback_rest"
    stock_source = stock.source if stock else "fallback_rest"
    data_mode = (
        "STREAMING"
        if stock_source.endswith("_stream") and option_source == "alpaca_option_stream"
        else "FALLBACK_REST"
    )
    fallback_reason = stream._option_fallback_reason or stream._stock_fallback_reason
    last_updated = (
        option.timestamp
        if option is not None
        else stock.timestamp
        if stock is not None
        else _now_iso()
    )

    return {
        "type": "market_update",
        "positionId": position.position_id,
        "contractId": position.contract_id,
        "underlyingSymbol": position.underlying_symbol,
        "underlyingPrice": _float_or_none(stock.price if stock else None),
        "underlyingBid": _float_or_none(stock.bid if stock else None),
        "underlyingAsk": _float_or_none(stock.ask if stock else None),
        "optionSymbol": position.option_symbol,
        "optionBid": _float_or_none(option_bid),
        "optionAsk": _float_or_none(option_ask),
        "optionMid": _float_or_none(option_mid),
        "optionLast": _float_or_none(option_last),
        "estimatedOptionPrice": _float_or_none(estimated),
        "unrealizedPnl": _float_or_none(pnl),
        "unrealizedPnlPercent": _float_or_none(
            None if pnl_percent is None else pnl_percent.quantize(Decimal("0.01"))
        ),
        "dataMode": data_mode,
        "stockSource": stock_source,
        "optionSource": option_source,
        "lastUpdated": last_updated,
        "fallbackReason": fallback_reason,
        "positionStatus": f"{trigger_reason}_TRIGGERED" if trigger_reason else "OPEN",
        "triggerReason": trigger_reason,
    }


def parse_stream_positions(payload: Mapping[str, Any]) -> tuple[StreamPosition, ...]:
    raw_positions = payload.get("positions")
    if isinstance(raw_positions, list) and raw_positions:
        return tuple(
            position
            for item in raw_positions
            if isinstance(item, Mapping)
            for position in [_parse_position_item(item)]
            if position is not None
        )

    symbols = _string_list(payload.get("symbols"))
    option_contracts = _string_list(payload.get("optionContracts"))
    position_ids = _string_list(payload.get("positionIds"))
    positions: list[StreamPosition] = []
    for index, symbol in enumerate(symbols):
        option_symbol = option_contracts[index] if index < len(option_contracts) else ""
        position_id = position_ids[index] if index < len(position_ids) else f"{symbol}-{index}"
        positions.append(
            StreamPosition(
                position_id=position_id,
                underlying_symbol=symbol.upper(),
                contract_id=option_symbol or position_id,
                option_symbol=option_symbol.upper(),
                option_type="CALL",
                position_side="LONG",
                quantity=1,
                entry_option_price=Decimal("0"),
            )
        )
    return tuple(positions)


def _parse_position_item(item: Mapping[str, Any]) -> StreamPosition | None:
    position_id = _to_text(item.get("positionId") or item.get("id"))
    underlying = _to_text(item.get("underlyingSymbol") or item.get("symbol"))
    if not position_id or not underlying:
        return None
    option_type = (_to_text(item.get("optionType")) or "CALL").upper()
    position_side = (_to_text(item.get("positionSide")) or "LONG").upper()
    strike = _to_decimal(item.get("strike"))
    expiration = _to_date(item.get("expiration"))
    contract_id = _to_text(item.get("contractId") or item.get("optionSymbol")) or position_id
    option_symbol = _to_text(item.get("optionSymbol")) or ""
    if not _looks_like_occ_symbol(option_symbol) and strike is not None and expiration is not None:
        option_symbol = build_occ_symbol(
            underlying,
            expiry=expiration,
            option_type=option_type.lower(),
            strike=strike,
        )
    return StreamPosition(
        position_id=position_id,
        underlying_symbol=underlying.upper(),
        contract_id=contract_id,
        option_symbol=option_symbol.upper(),
        option_type=option_type,
        position_side="SHORT" if position_side == "SHORT" else "LONG",
        quantity=max(int(_to_decimal(item.get("quantity")) or Decimal("1")), 1),
        entry_option_price=_to_decimal(item.get("entryOptionPrice")) or Decimal("0"),
        entry_underlying_price=_to_decimal(item.get("entryUnderlyingPrice")),
        strike=strike,
        expiration=expiration,
        stop_loss=_to_decimal(item.get("stopLoss")),
        take_profit=_to_decimal(item.get("takeProfit")),
        fallback_bid=_to_decimal(item.get("currentBid")),
        fallback_ask=_to_decimal(item.get("currentAsk")),
        fallback_mid=_to_decimal(item.get("currentMid") or item.get("currentMarkPrice")),
        fallback_last=_to_decimal(item.get("lastPrice")),
    )


def get_alpaca_stream_manager() -> AlpacaStreamManager:
    global _STREAM_MANAGER
    try:
        return _STREAM_MANAGER
    except NameError:
        _STREAM_MANAGER = AlpacaStreamManager()
        return _STREAM_MANAGER


def _message_list(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    return []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().upper() for item in value if str(item).strip()]


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _positive_decimal(value: Any) -> Decimal | None:
    converted = _to_decimal(value)
    if converted is None or converted <= 0:
        return None
    return converted


def _to_date(value: Any) -> date | None:
    text = _to_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _midpoint(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / Decimal("2")
    return None


def _option_price(
    bid: Decimal | None,
    ask: Decimal | None,
    mid: Decimal | None,
    last: Decimal | None,
    position_side: str,
) -> Decimal | None:
    if mid is not None and mid > 0:
        return mid
    computed_mid = _midpoint(bid, ask)
    if computed_mid is not None:
        return computed_mid
    if last is not None and last > 0:
        return last
    if position_side == "LONG":
        return bid or ask
    return ask or bid


def _trigger_reason(position: StreamPosition, estimated: Decimal | None) -> str | None:
    if estimated is None:
        return None
    if position.position_side == "LONG":
        if position.stop_loss is not None and estimated <= position.stop_loss:
            return "STOP_LOSS"
        if position.take_profit is not None and estimated >= position.take_profit:
            return "TAKE_PROFIT"
    else:
        if position.stop_loss is not None and estimated >= position.stop_loss:
            return "STOP_LOSS"
        if position.take_profit is not None and estimated <= position.take_profit:
            return "TAKE_PROFIT"
    return None


def _float_or_none(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _looks_like_occ_symbol(value: str | None) -> bool:
    if not value:
        return False
    compact = value.strip().upper()
    return len(compact) >= 15 and compact[-15:-9].isdigit() and compact[-9] in {"C", "P"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, ConnectionClosed):
        return f"Alpaca stream disconnected: {exc.code}"
    return str(exc) or exc.__class__.__name__
