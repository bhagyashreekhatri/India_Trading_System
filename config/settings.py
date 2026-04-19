import os
from dotenv import load_dotenv

load_dotenv()

# ─── Broker ───────────────────────────────────────────────────────────────────
KITE_API_KEY        = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET     = os.getenv("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN   = os.getenv("KITE_ACCESS_TOKEN", "")   # refreshed daily

# ─── AI / LLM ─────────────────────────────────────────────────────────────────
GROQ_API_KEY        = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL          = "llama-3.3-70b-versatile"

# ─── News ─────────────────────────────────────────────────────────────────────
NEWS_API_KEY        = os.getenv("NEWS_API_KEY", "")

# ─── ChromaDB ─────────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR  = os.getenv("CHROMA_PERSIST_DIR", "./chroma_store")

# ─── Trading parameters ───────────────────────────────────────────────────────
PAPER_TRADING       = True                  # set False for live
CAPITAL             = 200_000               # ₹2,00,000 virtual capital
MAX_POSITIONS       = 5                     # max concurrent open trades
MAX_SECTOR_EXPOSURE = 0.30                  # 30% max in one sector
RISK_PER_TRADE_PCT  = 0.01                  # 1% of capital per trade (SL distance)
TARGET_R            = 1.5                   # default target = 1.5× SL distance
SCAN_INTERVAL_MIN   = 5                     # scan every 5 minutes

# ─── Scoring thresholds ───────────────────────────────────────────────────────
MIN_SCORE_ENTRY     = 7.0                   # A grade minimum to enter
MIN_SCORE_WATCHLIST = 5.0                   # B grade goes to watchlist
PROXIMITY_MAX_PCT   = 0.007                 # 0.7% max price drift from signal

# ─── Volume thresholds ────────────────────────────────────────────────────────
VOLUME_MIN_RATIO    = 1.2                   # minimum to even consider
VOLUME_STRONG_RATIO = 1.5                   # full volume score starts here
VOLUME_VERY_STRONG  = 2.5                   # max volume score

# ─── Session hard limits (risk rules, not time rules) ─────────────────────────
NO_ENTRY_BEFORE_MIN  = 5                    # skip first 5 min (9:15–9:20)
NO_NEW_ENTRY_AFTER   = "15:00"              # can't manage exit after 3pm
MARKET_OPEN          = "09:15"
MARKET_CLOSE         = "15:30"

# ─── Timezone ─────────────────────────────────────────────────────────────────
TIMEZONE             = "Asia/Kolkata"
