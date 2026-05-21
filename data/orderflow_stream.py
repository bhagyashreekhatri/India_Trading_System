"""
Order-flow streaming client — the LIVE feed behind the dynamic scalper brain.

Wraps Kite's WebSocket (KiteTicker) in a background thread, subscribes the
trading universe in FULL mode (5-level depth + last price + cumulative volume),
and keeps a short rolling buffer of Snapshots per symbol. Decision code calls
get_flow(symbol) to read MOTION (book trend, lift ratio, wall absorption) via
tools/orderflow_metrics.py — instead of a single frozen REST snapshot.

Design notes / safety:
  • KiteTicker.connect(threaded=True) runs its own reactor in a background
    thread and auto-reconnects. We never block the trading loop.
  • All buffer access is under a lock; ticks arrive on the WS thread, reads
    happen on the engine thread.
  • Lazy import of kiteconnect so this module imports fine in environments
    without the SDK (tests, dashboard) — only start() needs it.
  • Every callback is wrapped; a streaming fault can never crash the engine.
    If the stream is cold/stale, get_flow() returns a non-fresh FlowState and
    the caller falls back to the existing frozen snapshot gate.
"""
from __future__ import annotations

import time
import threading
from collections import deque
from typing import Callable, Optional

from tools.orderflow_metrics import Snapshot, FlowState, compute_flow


class OrderFlowStream:
    def __init__(
        self,
        api_key:      str,
        access_token: str,
        get_token:    Callable[[str], Optional[int]],
        window_sec:   float = 20.0,
        buffer_len:   int = 400,
    ):
        self.api_key      = api_key
        self.access_token = access_token
        self.get_token    = get_token
        self.window_sec   = window_sec
        self.buffer_len   = buffer_len

        self._lock = threading.Lock()
        self._buf: dict[str, deque] = {}        # symbol -> deque[Snapshot]
        self._tok2sym: dict[int, str] = {}
        self._sym2tok: dict[str, int] = {}
        self._subscribed: set[int] = set()

        self._kws = None
        self._connected = False
        self._last_tick_ts = 0.0
        self._started = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self, symbols: list[str]) -> bool:
        """Resolve tokens, open the WebSocket (threaded), subscribe FULL mode.
        Returns True if the socket was launched."""
        if self._started:
            self.update_subscriptions(symbols)
            return True
        try:
            from kiteconnect import KiteTicker
        except Exception as e:
            print(f"[OrderFlow] KiteTicker import failed — stream disabled: {e}")
            return False

        self._register_tokens(symbols)
        tokens = list(self._subscribed)
        try:
            self._kws = KiteTicker(self.api_key, self.access_token)
            self._kws.on_ticks     = self._on_ticks
            self._kws.on_connect   = self._on_connect
            self._kws.on_close     = self._on_close
            self._kws.on_error     = self._on_error
            self._kws.on_reconnect = self._on_reconnect
            self._kws.connect(threaded=True)
            self._started = True
            print(f"[OrderFlow] WebSocket launched — {len(tokens)} instruments queued")
            return True
        except Exception as e:
            print(f"[OrderFlow] start failed (non-fatal): {e}")
            return False

    def _register_tokens(self, symbols: list[str]):
        for sym in symbols:
            if sym in self._sym2tok:
                continue
            tok = None
            try:
                tok = self.get_token(sym)
            except Exception:
                tok = None
            if not tok:
                continue
            self._sym2tok[sym] = tok
            self._tok2sym[tok] = sym
            self._subscribed.add(tok)
            with self._lock:
                self._buf.setdefault(sym, deque(maxlen=self.buffer_len))

    def update_subscriptions(self, symbols: list[str]):
        """Add any newly-active symbols (e.g. fresh discovery admits) to the
        live feed. We only add — leaving extra subscriptions costs little."""
        before = set(self._subscribed)
        self._register_tokens(symbols)
        new = list(self._subscribed - before)
        if new and self._kws is not None and self._connected:
            try:
                self._kws.subscribe(new)
                self._kws.set_mode(self._kws.MODE_FULL, new)
                print(f"[OrderFlow] subscribed {len(new)} new instruments")
            except Exception as e:
                print(f"[OrderFlow] subscribe-update failed (non-fatal): {e}")

    def stop(self):
        try:
            if self._kws is not None:
                self._kws.close()
        except Exception:
            pass

    # ── callbacks (run on the WS thread) ─────────────────────────────────────
    def _on_connect(self, ws, response):
        try:
            tokens = list(self._subscribed)
            if tokens:
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_FULL, tokens)
            self._connected = True
            print(f"[OrderFlow] connected — FULL mode on {len(tokens)} instruments")
        except Exception as e:
            print(f"[OrderFlow] on_connect error (non-fatal): {e}")

    def _on_ticks(self, ws, ticks):
        now = time.time()
        try:
            for t in ticks:
                tok = t.get("instrument_token")
                sym = self._tok2sym.get(tok)
                if not sym:
                    continue
                depth = t.get("depth") or {}
                buy = depth.get("buy", []) or []
                sell = depth.get("sell", []) or []
                bid5 = sum(float(l.get("quantity", 0)) for l in buy[:5])
                ask5 = sum(float(l.get("quantity", 0)) for l in sell[:5])
                snap = Snapshot(
                    ts=now,
                    ltp=float(t.get("last_price", 0.0) or 0.0),
                    cum_vol=float(t.get("volume_traded", t.get("volume", 0)) or 0.0),
                    bid5=bid5,
                    ask5=ask5,
                    best_bid_qty=float(buy[0].get("quantity", 0)) if buy else 0.0,
                    best_ask_qty=float(sell[0].get("quantity", 0)) if sell else 0.0,
                )
                with self._lock:
                    dq = self._buf.get(sym)
                    if dq is None:
                        dq = deque(maxlen=self.buffer_len)
                        self._buf[sym] = dq
                    dq.append(snap)
            self._last_tick_ts = now
        except Exception as e:
            print(f"[OrderFlow] on_ticks error (non-fatal): {e}")

    def _on_close(self, ws, code, reason):
        self._connected = False
        print(f"[OrderFlow] socket closed ({code}): {reason}")

    def _on_error(self, ws, code, reason):
        print(f"[OrderFlow] socket error ({code}): {reason}")

    def _on_reconnect(self, ws, attempts):
        print(f"[OrderFlow] reconnecting… attempt {attempts}")

    # ── read API (engine thread) ─────────────────────────────────────────────
    def get_flow(self, symbol: str) -> FlowState:
        with self._lock:
            dq = self._buf.get(symbol)
            samples = list(dq) if dq else []
        return compute_flow(samples, self.window_sec)

    def is_healthy(self) -> bool:
        """True if connected and a tick arrived in the last 30s."""
        return self._connected and (time.time() - self._last_tick_ts) < 30.0

    def status(self) -> dict:
        return {
            "started": self._started,
            "connected": self._connected,
            "instruments": len(self._subscribed),
            "secs_since_tick": round(time.time() - self._last_tick_ts, 1)
                               if self._last_tick_ts else None,
        }
