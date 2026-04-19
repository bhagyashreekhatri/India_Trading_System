"""
Trade state manager using SQLite.
Tracks open positions, capital deployment, cooldowns, trade history.
No API calls — pure local state.
"""
import sqlite3
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from config.settings import CAPITAL, MAX_POSITIONS, MAX_SECTOR_EXPOSURE, TIMEZONE
from scoring.engine import Grade

DB_PATH = Path("./trade_state.db")


@dataclass
class Position:
    id:             int
    symbol:         str
    setup_type:     str
    direction:      str
    grade:          str
    score:          float
    confidence:     float
    entry_price:    float
    stop_loss:      float
    target_price:   float
    quantity:       int
    entry_time:     str
    sector:         str
    reason:         str
    status:         str        # "open" | "closed_win" | "closed_loss" | "closed_expired"
    exit_price:     Optional[float] = None
    exit_time:      Optional[str]   = None
    pnl:            Optional[float] = None
    pnl_r:          Optional[float] = None
    exit_reason:    Optional[str]   = None


@dataclass
class WatchlistItem:
    symbol:       str
    setup_type:   str
    score:        float
    grade:        str
    entry_zone:   float
    stop_loss:    float
    target:       float
    added_at:     str
    reason:       str


class TradeStateManager:
    """Single source of truth for all trade state."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol        TEXT NOT NULL,
                    setup_type    TEXT NOT NULL,
                    direction     TEXT NOT NULL,
                    grade         TEXT NOT NULL,
                    score         REAL NOT NULL,
                    confidence    REAL NOT NULL,
                    entry_price   REAL NOT NULL,
                    stop_loss     REAL NOT NULL,
                    target_price  REAL NOT NULL,
                    quantity      INTEGER NOT NULL,
                    entry_time    TEXT NOT NULL,
                    sector        TEXT NOT NULL,
                    reason        TEXT NOT NULL,
                    status        TEXT NOT NULL DEFAULT 'open',
                    exit_price    REAL,
                    exit_time     TEXT,
                    pnl           REAL,
                    pnl_r         REAL,
                    exit_reason   TEXT
                );

                CREATE TABLE IF NOT EXISTS watchlist (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT NOT NULL,
                    setup_type  TEXT NOT NULL,
                    score       REAL NOT NULL,
                    grade       TEXT NOT NULL,
                    entry_zone  REAL NOT NULL,
                    stop_loss   REAL NOT NULL,
                    target      REAL NOT NULL,
                    added_at    TEXT NOT NULL,
                    reason      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cooldowns (
                    symbol      TEXT PRIMARY KEY,
                    until       TEXT NOT NULL,
                    reason      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    date            TEXT PRIMARY KEY,
                    total_trades    INTEGER DEFAULT 0,
                    wins            INTEGER DEFAULT 0,
                    losses          INTEGER DEFAULT 0,
                    total_pnl       REAL DEFAULT 0.0,
                    total_r         REAL DEFAULT 0.0,
                    capital_start   REAL NOT NULL,
                    capital_end     REAL
                );
            """)

    # ── Capital management ────────────────────────────────────────────────────

    def get_deployed_capital(self) -> float:
        """Sum of capital in all open positions."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT SUM(entry_price * quantity) FROM positions WHERE status='open'"
            ).fetchone()
            return row[0] or 0.0

    def get_available_capital(self) -> float:
        return CAPITAL - self.get_deployed_capital()

    def get_deployment_pct(self) -> float:
        return (self.get_deployed_capital() / CAPITAL) * 100

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss:   float,
        risk_pct:    float = 0.01,
    ) -> int:
        """
        Risk-based position sizing.
        risk_pct of capital = max loss on this trade.
        quantity = (capital × risk_pct) / SL_distance_per_share
        """
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            return 0
        risk_amount = CAPITAL * risk_pct
        quantity    = int(risk_amount / sl_distance)
        cost        = quantity * entry_price

        # Never use more than 25% of capital on one trade
        if cost > CAPITAL * 0.25:
            quantity = int((CAPITAL * 0.25) / entry_price)

        # Must fit in available capital
        available = self.get_available_capital()
        if cost > available:
            quantity = int(available / entry_price)

        return max(0, quantity)

    # ── Open position checks ──────────────────────────────────────────────────

    def get_open_positions(self) -> list[Position]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY entry_time DESC"
            ).fetchall()
            return [Position(**dict(row)) for row in rows]

    def get_open_count(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM positions WHERE status='open'"
            ).fetchone()[0]

    def get_sector_exposure(self, sector: str) -> float:
        """Fraction of capital deployed in a sector."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT SUM(entry_price * quantity) FROM positions WHERE status='open' AND sector=?",
                (sector,)
            ).fetchone()
            deployed_sector = row[0] or 0.0
        return deployed_sector / CAPITAL

    def is_already_holding(self, symbol: str) -> bool:
        with self._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM positions WHERE symbol=? AND status='open'",
                (symbol,)
            ).fetchone()[0]
            return count > 0

    # ── Allocation checks ─────────────────────────────────────────────────────

    def can_enter(self, symbol: str, sector: str, entry_price: float, stop_loss: float) -> tuple[bool, str]:
        """Full pre-entry check. Returns (can_enter, reason)."""

        if self.is_already_holding(symbol):
            return False, f"Already holding {symbol}"

        if self.get_open_count() >= MAX_POSITIONS:
            return False, f"Max positions ({MAX_POSITIONS}) reached"

        sector_exp = self.get_sector_exposure(sector)
        if sector_exp >= MAX_SECTOR_EXPOSURE:
            return False, f"Sector cap hit: {sector} at {sector_exp*100:.0f}%"

        qty = self.calculate_position_size(entry_price, stop_loss)
        if qty == 0:
            return False, "Position size = 0 (insufficient capital or SL too tight)"

        if self.is_in_cooldown(symbol):
            return False, f"{symbol} is in cooldown"

        return True, "OK"

    # ── Position CRUD ─────────────────────────────────────────────────────────

    def open_position(
        self,
        symbol:      str,
        setup_type:  str,
        direction:   str,
        grade:       str,
        score:       float,
        confidence:  float,
        entry_price: float,
        stop_loss:   float,
        target_price: float,
        sector:      str,
        reason:      str,
        risk_pct:    float = 0.01,
    ) -> Optional[Position]:
        qty = self.calculate_position_size(entry_price, stop_loss, risk_pct)
        if qty == 0:
            return None

        now = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO positions
                (symbol, setup_type, direction, grade, score, confidence,
                 entry_price, stop_loss, target_price, quantity, entry_time,
                 sector, reason, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (symbol, setup_type, direction, grade, score, confidence,
                  entry_price, stop_loss, target_price, qty, now,
                  sector, reason, "open"))
            pos_id = cursor.lastrowid

        print(f"[TradeState] OPENED #{pos_id} {symbol} {direction} "
              f"qty={qty} entry={entry_price} sl={stop_loss} target={target_price} "
              f"grade={grade} score={score}")
        return self.get_position_by_id(pos_id)

    def close_position(
        self,
        position_id: int,
        exit_price:  float,
        exit_reason: str,
    ) -> Optional[Position]:
        pos = self.get_position_by_id(position_id)
        if not pos or pos.status != "open":
            return None

        sl_dist = abs(pos.entry_price - pos.stop_loss)
        pnl     = (exit_price - pos.entry_price) * pos.quantity
        if pos.direction == "short":
            pnl = (pos.entry_price - exit_price) * pos.quantity
        pnl_r   = pnl / (sl_dist * pos.quantity) if sl_dist > 0 else 0.0

        if pnl > 0:
            status = "closed_win"
        elif pnl < 0:
            status = "closed_loss"
        else:
            status = "closed_expired"

        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute("""
                UPDATE positions
                SET status=?, exit_price=?, exit_time=?, pnl=?, pnl_r=?, exit_reason=?
                WHERE id=?
            """, (status, exit_price, now, round(pnl, 2), round(pnl_r, 2),
                  exit_reason, position_id))

        print(f"[TradeState] CLOSED #{position_id} {pos.symbol} "
              f"exit={exit_price} pnl=₹{pnl:.0f} ({pnl_r:.1f}R) reason={exit_reason}")

        self._add_cooldown(pos.symbol, minutes=30, reason=f"Cooldown after {exit_reason}")
        return self.get_position_by_id(position_id)

    def get_position_by_id(self, pos_id: int) -> Optional[Position]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM positions WHERE id=?", (pos_id,)).fetchone()
            return Position(**dict(row)) if row else None

    # ── Watchlist ─────────────────────────────────────────────────────────────

    def add_to_watchlist(
        self,
        symbol: str, setup_type: str, score: float, grade: str,
        entry_zone: float, stop_loss: float, target: float, reason: str,
    ):
        self.remove_from_watchlist(symbol)   # avoid duplicates
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO watchlist (symbol, setup_type, score, grade, entry_zone, stop_loss, target, added_at, reason)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (symbol, setup_type, score, grade, entry_zone, stop_loss, target,
                  datetime.now().isoformat(), reason))

    def get_watchlist(self) -> list[WatchlistItem]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM watchlist ORDER BY score DESC").fetchall()
            return [WatchlistItem(**{k: row[k] for k in WatchlistItem.__dataclass_fields__})
                    for row in rows]

    def remove_from_watchlist(self, symbol: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))

    # ── Cooldowns ─────────────────────────────────────────────────────────────

    def _add_cooldown(self, symbol: str, minutes: int = 30, reason: str = ""):
        until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cooldowns (symbol, until, reason) VALUES (?,?,?)",
                (symbol, until, reason)
            )

    def is_in_cooldown(self, symbol: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT until FROM cooldowns WHERE symbol=?", (symbol,)
            ).fetchone()
            if not row:
                return False
            until = datetime.fromisoformat(row["until"])
            if datetime.now() >= until:
                conn.execute("DELETE FROM cooldowns WHERE symbol=?", (symbol,))
                return False
            return True

    # ── Daily stats & P&L ─────────────────────────────────────────────────────

    def get_today_pnl(self) -> float:
        today = datetime.now().date().isoformat()
        with self._connect() as conn:
            row = conn.execute("""
                SELECT COALESCE(SUM(pnl), 0) FROM positions
                WHERE DATE(exit_time) = ? AND status != 'open'
            """, (today,)).fetchone()
            return row[0] or 0.0

    def get_today_trades(self) -> list[Position]:
        today = datetime.now().date().isoformat()
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM positions
                WHERE DATE(entry_time) = ? ORDER BY entry_time DESC
            """, (today,)).fetchall()
            return [Position(**dict(row)) for row in rows]

    def get_all_closed_trades(self) -> list[Position]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM positions WHERE status != 'open'
                ORDER BY exit_time DESC
            """).fetchall()
            return [Position(**dict(row)) for row in rows]

    def get_win_rate_by_setup(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT setup_type,
                       COUNT(*) as total,
                       SUM(CASE WHEN status='closed_win' THEN 1 ELSE 0 END) as wins,
                       AVG(pnl_r) as avg_r
                FROM positions WHERE status != 'open'
                GROUP BY setup_type
            """).fetchall()
            return {row["setup_type"]: {
                "total": row["total"],
                "wins":  row["wins"],
                "win_rate": round(row["wins"] / row["total"] * 100, 1),
                "avg_r":    round(row["avg_r"] or 0, 2),
            } for row in rows}

    def get_win_rate_by_grade(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT grade,
                       COUNT(*) as total,
                       SUM(CASE WHEN status='closed_win' THEN 1 ELSE 0 END) as wins,
                       AVG(pnl_r) as avg_r
                FROM positions WHERE status != 'open'
                GROUP BY grade
            """).fetchall()
            return {row["grade"]: {
                "total":    row["total"],
                "wins":     row["wins"],
                "win_rate": round(row["wins"] / row["total"] * 100, 1),
                "avg_r":    round(row["avg_r"] or 0, 2),
            } for row in rows}

    def get_summary(self) -> dict:
        closed = self.get_all_closed_trades()
        if not closed:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_r": 0, "total_pnl": 0}
        wins   = [t for t in closed if t.status == "closed_win"]
        losses = [t for t in closed if t.status == "closed_loss"]
        total_pnl = sum(t.pnl for t in closed if t.pnl)
        avg_r     = sum(t.pnl_r for t in closed if t.pnl_r) / len(closed)
        return {
            "total":    len(closed),
            "wins":     len(wins),
            "losses":   len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "avg_r":    round(avg_r, 2),
            "total_pnl": round(total_pnl, 2),
        }
