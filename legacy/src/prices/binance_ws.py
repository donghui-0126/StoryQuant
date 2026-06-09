"""
Real-time price streaming from Binance WebSocket (no API key required).
"""

import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

import requests
import websockets

logger = logging.getLogger(__name__)


def _binance_symbol_to_ticker(symbol: str) -> str:
    """Convert Binance symbol to ticker format: btcusdt -> BTC-USDT."""
    symbol = symbol.upper()
    # Common quote currencies, longest first to avoid partial matches
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB", "USDC"):
        if symbol.endswith(quote):
            base = symbol[: -len(quote)]
            return f"{base}-{quote}"
    # Fallback: return as-is uppercased
    return symbol


class BinanceWebSocket:
    """
    Subscribes to Binance kline (candlestick) streams via WebSocket.

    Parameters
    ----------
    symbols : list[str]
        Binance trading pairs in lowercase, e.g. ["btcusdt", "ethusdt"].
    on_kline : callable, optional
        Callback invoked for every *closed* candle with a dict:
        {ticker, timestamp, open, high, low, close, volume, is_closed}
    """

    WS_BASE = "wss://stream.binance.com:9443/stream"

    def __init__(
        self,
        symbols: List[str] = None,
        on_kline: Optional[Callable[[Dict], None]] = None,
    ):
        if symbols is None:
            symbols = ["btcusdt", "ethusdt", "solusdt", "bnbusdt", "xrpusdt", "adausdt", "dogeusdt"]
        self.symbols = [s.lower() for s in symbols]
        self.on_kline = on_kline
        self.latest_prices: Dict[str, float] = {}
        self._ws = None
        self._running = False
        self._last_kline_time: Dict[str, int] = {}  # symbol -> last closed kline open time ms

    def _build_url(self) -> str:
        streams = "/".join(f"{s}@kline_1m" for s in self.symbols)
        return f"{self.WS_BASE}?streams={streams}"

    def _parse_kline(self, msg: dict) -> Optional[Dict]:
        try:
            k = msg["data"]["k"]
            ticker = _binance_symbol_to_ticker(k["s"])
            return {
                "ticker": ticker,
                "timestamp": datetime.utcfromtimestamp(k["t"] / 1000).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "is_closed": bool(k["x"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to parse kline message: %s | %s", exc, msg)
            return None

    async def start(self):
        """Connect to Binance WebSocket and stream kline data."""
        self._running = True
        backoff = 1
        url = self._build_url()

        while self._running:
            try:
                logger.info("Connecting to %s", url)
                async with websockets.connect(url, ping_interval=20) as ws:
                    self._ws = ws
                    backoff = 1  # reset on successful connection
                    logger.info("Connected. Listening for klines...")

                    # Backfill any gaps that occurred during the disconnection
                    for symbol in self.symbols:
                        if symbol in self._last_kline_time:
                            count = backfill_klines(
                                symbol,
                                self._last_kline_time[symbol],
                                on_kline=self.on_kline,
                            )
                            if count:
                                logger.info("Gap backfill: %d klines for %s", count, symbol)

                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning("Non-JSON message: %s", raw)
                            continue

                        kline = self._parse_kline(msg)
                        if kline is None:
                            continue

                        # Always update latest prices for real-time display
                        self.latest_prices[kline["ticker"]] = kline["close"]

                        # Only call callback for closed candles
                        if kline["is_closed"] and self.on_kline is not None:
                            # Track last closed kline open time (ms) for gap detection
                            try:
                                raw_k = json.loads(raw)["data"]["k"]
                                self._last_kline_time[raw_k["s"].lower()] = int(raw_k["t"])
                            except Exception:
                                pass
                            try:
                                self.on_kline(kline)
                            except Exception as exc:
                                logger.error("on_kline callback error: %s", exc)

            except websockets.ConnectionClosed as exc:
                if not self._running:
                    break
                logger.warning("Connection closed (%s). Reconnecting in %ds...", exc, backoff)
            except OSError as exc:
                if not self._running:
                    break
                logger.warning("Network error (%s). Reconnecting in %ds...", exc, backoff)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

        logger.info("BinanceWebSocket stopped.")

    async def stop(self):
        """Signal the stream to stop and close the WebSocket connection."""
        self._running = False
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


def backfill_klines(symbol: str, start_time_ms: int, on_kline=None) -> int:
    """Backfill missing klines via Binance REST API. Returns count of backfilled candles."""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": "1m", "startTime": start_time_ms, "limit": 100}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        klines = resp.json()
        count = 0
        for k in klines:
            data = {
                "ticker": _binance_symbol_to_ticker(symbol),
                "timestamp": datetime.utcfromtimestamp(k[0] / 1000).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]),
                "volume": float(k[5]), "is_closed": True,
            }
            if on_kline:
                on_kline(data)
            count += 1
        return count
    except Exception as e:
        logger.warning("Backfill failed for %s: %s", symbol, e)
        return 0


def run_binance_ws(on_kline_callback: Callable[[Dict], None], symbols: List[str] = None):
    """
    Run the Binance WebSocket in a background thread using asyncio.run().

    Parameters
    ----------
    on_kline_callback : callable
        Called with a kline dict for each closed candle.
    symbols : list[str], optional
        Binance trading pairs to subscribe to.
    """
    bws = BinanceWebSocket(symbols=symbols, on_kline=on_kline_callback)

    def _thread_target():
        asyncio.run(bws.start())

    t = threading.Thread(target=_thread_target, daemon=True)
    t.start()
    return bws, t


# ---------------------------------------------------------------------------
# Quick smoke-test: print klines for 30 seconds then stop
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    received: list = []

    def print_kline(kline: dict):
        received.append(kline)
        print(
            f"[CLOSED] {kline['ticker']} | "
            f"O={kline['open']:.4f} H={kline['high']:.4f} "
            f"L={kline['low']:.4f} C={kline['close']:.4f} "
            f"V={kline['volume']:.2f}"
        )

    bws, thread = run_binance_ws(print_kline)

    print("Streaming for 30 seconds... (Ctrl-C to quit early)")
    try:
        for _ in range(30):
            time.sleep(1)
            # Show real-time prices even before a candle closes
            if bws.latest_prices:
                prices = "  ".join(
                    f"{t}={p:.4f}" for t, p in sorted(bws.latest_prices.items())
                )
                sys.stdout.write(f"\r[live] {prices}   ")
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(bws.stop())
        print(f"\nDone. Received {len(received)} closed candle(s).")
