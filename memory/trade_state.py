"""
Trade State Manager — SQLite-backed state for all positions and trades.
Tracks open positions, closed trades, watchlist, and session stats.
"""
import sqlite3
import json
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from config.settings import CAPITAL, RISK_PER_TRADE_PCT, TARGET_R1, TARGET_R2

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = Path("./trade_state.db")


def _now_iso_ist() -> str:
    """IST-aware ISO timestamp. Use for all new writes to entry_time/exit_time."""
    return datetime.now(IST).isoformat()


def _to_ist(ts: str) -> Optional[datetime]:
    """
    Parse a stored ISO timestamp into a TZ-aware IST datetime.
    Handles legacy naive ISO (UTC-host or IST-host) and new IST-aware ISO.
    """
    if not ts:
        return None
    try:
        import time as _t
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is not None:
            return parsed.astimezone(IST)
        # Naive: assume host-local tz at the time of write
        host_offset = _t.localtime().tm_gmtoff
        return parsed.replace(tzinfo=timezone(timedelta(seconds=host_offset))).astimezone(IST)
    except Exception:
        return None


@dataclass
class Position:
    id:               int
    symbol:           str
    setup_type:       str
    direction:        str
    grade:            str
    score:            float
    confidence:       float

    # Prices
    entry_price:      float
    stop_loss:        float
    initial_sl:       float
    target_price:     float
    tp1_price:        float
    tp2_price:        float
    tp1_hit:          bool = False

    # Size
    quantity:         int   = 0
    quantity_remaining: int = 0

    # P&L
    pnl:              float = 0.0
    pnl_r:            float = 0.0

    # Reasons
    entry_reason:     str   = ""
    exit_reason:      str   = ""
    score_breakdown:  str   = "{}"

    # Timestamps
    entry_time:       str   = ""
    exit_time:        str   = ""
    status:           str   = "open"
    exit_price:       Optional[float] = None

    # Broker-side SL-M order id (Fix #6) — populated after entry, replaced on
    # TP1/trail, cancelled on full exit. Paper trades store "PAPER_SL_*".
    sl_order_id:      str   = ""


@dataclass
class WatchlistItem:
    symbol:      str
    setup_type:  str
    score:       float
    entry_price: float
    stop_loss:   float
    tp1_price:   float
    tp2_price:   float
    reason:      str
    added_at:    str


class TradeStateManager:

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol              TEXT NOT NULL,
                    setup_type          TEXT,
                    direction           TEXT DEFAULT 'long',
                    grade               TEXT,
                    score               REAL DEFAULT 0,
                    confidence          REAL DEFAULT 0,
                    entry_price         REAL,
                    stop_loss           REAL,
                    initial_sl          REAL,
                    target_price        REAL,
                    tp1_price           REAL,
                    tp2_price           REAL,
                    tp1_hit             INTEGER DEFAULT 0,
                    quantity            INTEGER DEFAULT 0,
                    quantity_remaining  INTEGER DEFAULT 0,
                    pnl                 REAL DEFAULT 0,
                    pnl_r               REAL DEFAULT 0,
                    entry_reason        TEXT DEFAULT '',
                    exit_reason         TEXT DEFAULT '',
                    score_breakdown     TEXT DEFAULT '{}',
                    entry_time          TEXT,
                    exit_time           TEXT,
                    status              TEXT DEFAULT 'open',
                    exit_price          REAL
                );
                CREATE TABLE IF NOT EXISTS watchlist (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT,
                    setup_type  TEXT,
                    score       REAL,
                    entry_price REAL,
                    stop_loss   REAL,
                    tp1_price   REAL,
                    tp2_price   REAL,
                    reason      TEXT,
                    added_at    TEXT
                );
                CREATE TABLE IF NOT EXISTS session_stats (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    date                TEXT UNIQUE,
                    total_trades        INTEGER DEFAULT 0,
                    wins                INTEGER DEFAULT 0,
                    losses              INTEGER DEFAULT 0,
                    total_pnl           REAL DEFAULT 0,
                    consecutive_losses  INTEGER DEFAULT 0,
                    best_trade_pnl      REAL DEFAULT 0,
                    worst_trade_pnl     REAL DEFAULT 0
                );
            """)
            # ── Schema migrations (safe to run on every startup) ───────────────
            # ALTER TABLE ignores columns that already exist via the except clause.
            # Add every column introduced after initial deployment — order matters
            # only if columns depend on each other (none here do).
            _migrations = [
                "ALTER TABLE positions ADD COLUMN initial_sl        REAL     DEFAULT 0.0",
                "ALTER TABLE positions ADD COLUMN tp1_price         REAL     DEFAULT 0.0",
                "ALTER TABLE positions ADD COLUMN tp2_price         REAL     DEFAULT 0.0",
                "ALTER TABLE positions ADD COLUMN tp1_hit           INTEGER  DEFAULT 0",
                "ALTER TABLE positions ADD COLUMN quantity_remaining INTEGER  DEFAULT 0",
                "ALTER TABLE positions ADD COLUMN direction         TEXT     DEFAULT 'long'",
                "ALTER TABLE positions ADD COLUMN confidence        REAL     DEFAULT 0.0",
                "ALTER TABLE positions ADD COLUMN score_breakdown   TEXT     DEFAULT '{}'",
                "ALTER TABLE positions ADD COLUMN pnl_r             REAL     DEFAULT 0.0",
                "ALTER TABLE positions ADD COLUMN exit_reason       TEXT     DEFAULT ''",
                "ALTER TABLE positions ADD COLUMN entry_reason      TEXT     DEFAULT ''",
                "ALTER TABLE positions ADD COLUMN sl_order_id       TEXT     DEFAULT ''",
            ]
            for sql in _migrations:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass   # column already exists — safe to ignore

    def open_position(self, symbol, setup_type, grade, score, confidence,
                      entry_price, stop_loss, tp1_price, tp2_price, quantity,
                      entry_reason="", score_breakdown=None, direction="long",
                      sector="UNKNOWN") -> int:
        now = _now_iso_ist()
        bd  = json.dumps(score_breakdown or {})
        with self._conn() as conn:
            # Ensure sector column exists (may not in older DBs)
            try:
                conn.execute("ALTER TABLE positions ADD COLUMN sector TEXT DEFAULT 'UNKNOWN'")
            except Exception:
                pass
            cur = conn.execute("""
                INSERT INTO positions
                (symbol,setup_type,direction,grade,score,confidence,
                 entry_price,stop_loss,initial_sl,target_price,
                 tp1_price,tp2_price,tp1_hit,quantity,quantity_remaining,
                 entry_reason,score_breakdown,entry_time,status,sector)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?)
            """, (symbol,setup_type,direction,grade,score,confidence,
                  entry_price,stop_loss,stop_loss,tp2_price,
                  tp1_price,tp2_price,quantity,quantity,
                  entry_reason,bd,now,"open",sector))
            return cur.lastrowid

    def get_open_positions(self) -> List[Position]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM positions WHERE status='open'").fetchall()
        return [self._row_to_position(r) for r in rows]

    def get_position(self, position_id: int) -> Optional[Position]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
        return self._row_to_position(row) if row else None

    def update_stop_loss(self, position_id: int, new_sl: float):
        with self._conn() as conn:
            conn.execute("UPDATE positions SET stop_loss=? WHERE id=?", (new_sl, position_id))

    def update_sl_order_id(self, position_id: int, order_id: str):
        """Persist the active broker-side SL-M order id (Fix #6)."""
        with self._conn() as conn:
            conn.execute("UPDATE positions SET sl_order_id=? WHERE id=?", (order_id or "", position_id))

    def mark_tp1_hit(self, position_id: int, qty_remaining: int, partial_pnl: float):
        with self._conn() as conn:
            conn.execute("""
                UPDATE positions SET tp1_hit=1, quantity_remaining=?, pnl=pnl+?
                WHERE id=?
            """, (qty_remaining, partial_pnl, position_id))

    def close_position(self, position_id, exit_price, pnl, pnl_r, status, exit_reason=""):
        now = _now_iso_ist()
        with self._conn() as conn:
            conn.execute("""
                UPDATE positions
                SET exit_price=?,pnl=?,pnl_r=?,status=?,exit_reason=?,exit_time=?
                WHERE id=?
            """, (exit_price,pnl,pnl_r,status,exit_reason,now,position_id))
        self._update_session_stats(pnl, status)

    def add_to_watchlist(self, item: WatchlistItem):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO watchlist
                (symbol,setup_type,score,entry_price,stop_loss,tp1_price,tp2_price,reason,added_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (item.symbol,item.setup_type,item.score,item.entry_price,
                  item.stop_loss,item.tp1_price,item.tp2_price,item.reason,item.added_at))

    def clear_watchlist(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM watchlist")

    def get_watchlist(self) -> List[WatchlistItem]:
        """Return only today's watchlist items — stale entries from previous days are ignored."""
        today = date.today().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist WHERE added_at LIKE ? ORDER BY score DESC",
                (f"{today}%",)
            ).fetchall()
        return [WatchlistItem(symbol=r["symbol"],setup_type=r["setup_type"],
                              score=r["score"],entry_price=r["entry_price"],
                              stop_loss=r["stop_loss"],tp1_price=r["tp1_price"],
                              tp2_price=r["tp2_price"],reason=r["reason"],
                              added_at=r["added_at"]) for r in rows]

    def clear_old_watchlist(self):
        """Delete watchlist entries older than today. Call at startup."""
        today = date.today().isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM watchlist WHERE added_at NOT LIKE ?", (f"{today}%",))

    def get_today_trades(self) -> List[Position]:
        today = date.today().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE entry_time LIKE ? ORDER BY entry_time DESC",
                (f"{today}%",)).fetchall()
        return [self._row_to_position(r) for r in rows]

    def get_all_closed_trades(self) -> List[Position]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status != 'open' ORDER BY exit_time DESC"
            ).fetchall()
        return [self._row_to_position(r) for r in rows]

    def get_today_pnl(self) -> float:
        today = date.today().isoformat()
        with self._conn() as conn:
            result = conn.execute(
                "SELECT COALESCE(SUM(pnl),0) FROM positions WHERE entry_time LIKE ? AND status!='open'",
                (f"{today}%",)).fetchone()[0]
        return float(result)

    def get_consecutive_losses(self) -> int:
        today = date.today().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT consecutive_losses FROM session_stats WHERE date=?", (today,)
            ).fetchone()
        return row["consecutive_losses"] if row else 0

    def get_deployed_capital(self) -> float:
        return sum(p.entry_price * p.quantity_remaining for p in self.get_open_positions())

    def get_available_capital(self) -> float:
        return max(0.0, CAPITAL - self.get_deployed_capital())

    def get_deployment_pct(self) -> float:
        return (self.get_deployed_capital() / CAPITAL) * 100

    def get_summary(self) -> dict:
        closed = self.get_all_closed_trades()
        if not closed:
            return {"total":0,"wins":0,"losses":0,"win_rate":0,"avg_r":0,"total_pnl":0}
        wins   = [t for t in closed if t.status == "closed_win"]
        losses = [t for t in closed if t.status == "closed_loss"]
        pnls   = [t.pnl for t in closed if t.pnl]
        rs     = [t.pnl_r for t in closed if t.pnl_r]
        return {
            "total": len(closed), "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins)/len(closed)*100,1),
            "avg_r": round(sum(rs)/len(rs),2) if rs else 0,
            "total_pnl": round(sum(pnls),0),
            "best_trade": max(pnls) if pnls else 0,
            "worst_trade": min(pnls) if pnls else 0,
        }

    def get_win_rate_by_setup(self) -> dict:
        closed = self.get_all_closed_trades()
        result = {}
        for t in closed:
            s = t.setup_type
            if s not in result:
                result[s] = {"total":0,"wins":0,"pnls":[],"rs":[]}
            result[s]["total"] += 1
            if t.status == "closed_win": result[s]["wins"] += 1
            if t.pnl: result[s]["pnls"].append(t.pnl)
            if t.pnl_r: result[s]["rs"].append(t.pnl_r)
        return {s: {"total":v["total"],"wins":v["wins"],
                    "win_rate":round(v["wins"]/v["total"]*100,1),
                    "avg_r":round(sum(v["rs"])/len(v["rs"]),2) if v["rs"] else 0,
                    "total_pnl":round(sum(v["pnls"]),0)}
                for s,v in result.items() if v["total"]>0}

    def get_win_rate_by_grade(self) -> dict:
        closed = self.get_all_closed_trades()
        result = {}
        for t in closed:
            g = t.grade or "C"
            if g not in result:
                result[g] = {"total":0,"wins":0,"rs":[],"pnls":[]}
            result[g]["total"] += 1
            if t.status == "closed_win": result[g]["wins"] += 1
            if t.pnl_r: result[g]["rs"].append(t.pnl_r)
            if t.pnl: result[g]["pnls"].append(t.pnl)
        return {g: {"total":v["total"],"wins":v["wins"],
                    "win_rate":round(v["wins"]/v["total"]*100,1),
                    "avg_r":round(sum(v["rs"])/len(v["rs"]),2) if v["rs"] else 0,
                    "total_pnl":round(sum(v["pnls"]),0)}
                for g,v in result.items() if v["total"]>0}

    def get_win_rate_by_hour(self) -> dict:
        closed = self.get_all_closed_trades()
        result = {}
        for t in closed:
            if not t.entry_time: continue
            try:
                # Convert to IST first — bucketing on raw .hour() of a naive
                # UTC-host timestamp gives off-by-5h30 buckets.
                ist_dt = _to_ist(t.entry_time)
                if ist_dt is None: continue
                hour  = ist_dt.hour
                label = f"{hour:02d}:00"
                if label not in result:
                    result[label] = {"total":0,"wins":0,"pnls":[]}
                result[label]["total"] += 1
                if t.status == "closed_win": result[label]["wins"] += 1
                if t.pnl: result[label]["pnls"].append(t.pnl)
            except Exception:
                continue
        return {h: {"total":v["total"],"wins":v["wins"],
                    "win_rate":round(v["wins"]/v["total"]*100,1),
                    "avg_pnl":round(sum(v["pnls"])/len(v["pnls"]),0) if v["pnls"] else 0}
                for h,v in sorted(result.items()) if v["total"]>0}

    def get_best_stocks(self, top_n: int = 10) -> list:
        closed = self.get_all_closed_trades()
        stock_pnl = {}
        for t in closed:
            if t.pnl:
                stock_pnl[t.symbol] = stock_pnl.get(t.symbol, 0) + t.pnl
        sorted_stocks = sorted(stock_pnl.items(), key=lambda x: x[1], reverse=True)
        return [{"symbol":s,"total_pnl":round(p,0)} for s,p in sorted_stocks[:top_n]]

    def is_in_cooldown(self, symbol: str, cooldown_minutes: int = 30) -> bool:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT exit_time FROM positions
                WHERE symbol=? AND status!='open'
                ORDER BY exit_time DESC LIMIT 1
            """, (symbol,)).fetchone()
        if not row or not row["exit_time"]: return False
        try:
            # IST-aware on both sides to remain correct after the entry/exit
            # write path is migrated to IST-aware ISO.
            exit_dt = _to_ist(row["exit_time"])
            if exit_dt is None: return False
            return (datetime.now(IST) - exit_dt).total_seconds() / 60 < cooldown_minutes
        except Exception:
            return False

    def _update_session_stats(self, pnl: float, status: str):
        today   = date.today().isoformat()
        is_win  = status == "closed_win"
        is_loss = status == "closed_loss"
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT * FROM session_stats WHERE date=?", (today,)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO session_stats (date,total_trades) VALUES (?,0)", (today,)
                )
                existing = conn.execute(
                    "SELECT * FROM session_stats WHERE date=?", (today,)
                ).fetchone()
            consec = existing["consecutive_losses"]
            if is_loss: consec += 1
            elif is_win: consec = 0
            conn.execute("""
                UPDATE session_stats
                SET total_trades=total_trades+1, wins=wins+?,
                    losses=losses+?, total_pnl=total_pnl+?,
                    consecutive_losses=?,
                    best_trade_pnl=MAX(best_trade_pnl,?),
                    worst_trade_pnl=MIN(worst_trade_pnl,?)
                WHERE date=?
            """, (1 if is_win else 0, 1 if is_loss else 0,
                  pnl, consec, pnl, pnl, today))

    def _row_to_position(self, row) -> Position:
        # sl_order_id may not be in older rows — handle KeyError gracefully
        try:
            sl_oid = row["sl_order_id"] or ""
        except (KeyError, IndexError):
            sl_oid = ""
        return Position(
            id=row["id"], symbol=row["symbol"],
            setup_type=row["setup_type"] or "",
            direction=row["direction"] or "long",
            grade=row["grade"] or "",
            score=row["score"] or 0,
            confidence=row["confidence"] or 0,
            entry_price=row["entry_price"] or 0,
            stop_loss=row["stop_loss"] or 0,
            initial_sl=row["initial_sl"] or row["stop_loss"] or 0,
            target_price=row["target_price"] or 0,
            tp1_price=row["tp1_price"] or 0,
            tp2_price=row["tp2_price"] or 0,
            tp1_hit=bool(row["tp1_hit"]),
            quantity=row["quantity"] or 0,
            quantity_remaining=row["quantity_remaining"] or 0,
            pnl=row["pnl"] or 0,
            pnl_r=row["pnl_r"] or 0,
            entry_reason=row["entry_reason"] or "",
            exit_reason=row["exit_reason"] or "",
            score_breakdown=row["score_breakdown"] or "{}",
            entry_time=row["entry_time"] or "",
            exit_time=row["exit_time"] or "",
            status=row["status"] or "open",
            exit_price=row["exit_price"],
            sl_order_id=sl_oid,
        )
