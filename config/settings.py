import os
from dotenv import load_dotenv

load_dotenv()

# ─── Broker ───────────────────────────────────────────────────────────────────
KITE_API_KEY        = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET     = os.getenv("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN   = os.getenv("KITE_ACCESS_TOKEN", "")

# ─── AI / LLM (Groq — used ONLY for news sentiment) ──────────────────────────
GROQ_API_KEY        = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL          = "llama-3.3-70b-versatile"

# ─── News ─────────────────────────────────────────────────────────────────────
NEWS_API_KEY        = os.getenv("NEWS_API_KEY", "")

# ─── Telegram alerts ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── ChromaDB ─────────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR  = os.getenv("CHROMA_PERSIST_DIR", "./chroma_store")

# ─── Trading parameters ───────────────────────────────────────────────────────
PAPER_TRADING           = True
CAPITAL                 = 1_500_000
MAX_POSITIONS           = 10              # raised for paper trading (was 5)
MAX_SECTOR_EXPOSURE     = 0.30
RISK_PER_TRADE_PCT      = 0.01            # 1% of capital per trade
MAX_POSITION_VALUE_PCT  = 0.20            # max 20% of capital per trade (₹3,00,000 at ₹15L capital)
TARGET_R1               = 1.0            # TP1 — exit 50% here
TARGET_R2               = 2.0            # TP2 — exit remaining 50% here
SCAN_INTERVAL_MIN       = 3              # scan every 3 minutes (was 5)

# ─── Trailing Stop Loss ───────────────────────────────────────────────────────
TRAILING_SL_ENABLED     = True
TRAILING_ATR_MULTIPLIER = 0.5            # trail SL by 0.5× ATR after TP1 hit
BREAKEVEN_AFTER_TP1     = True           # move SL to entry after TP1 hit

# ─── Opening Range Breakout ───────────────────────────────────────────────────
ORB_MINUTES             = 15             # 15-min ORB (9:15–9:30)
ORB_MIN_RANGE_PCT       = 0.3            # minimum range to be tradeable
ORB_MAX_RANGE_PCT       = 2.5            # skip if range too wide (volatile open)

# ─── Scoring thresholds ───────────────────────────────────────────────────────
MIN_SCORE_ENTRY         = 7.0            # Grade A minimum
MIN_SCORE_ENTRY_CONSERVATIVE = 8.0      # used after 3 consecutive losses
MIN_SCORE_WATCHLIST     = 5.0
PROXIMITY_MAX_PCT       = 0.007

# ─── Volume thresholds ────────────────────────────────────────────────────────
VOLUME_MIN_RATIO        = 1.2
VOLUME_STRONG_RATIO     = 1.5
VOLUME_VERY_STRONG      = 2.5

# ─── Market breadth thresholds ───────────────────────────────────────────────
BREADTH_BULLISH         = 0.65           # >65% stocks above VWAP → lean long
BREADTH_BEARISH         = 0.40           # <40% → avoid new longs
BREADTH_SAMPLE_SIZE     = 50             # stocks sampled for breadth score

# ─── Consecutive loss protection ─────────────────────────────────────────────
MAX_CONSECUTIVE_LOSSES  = 3              # after 3 losses → go conservative
CONSERVATIVE_SIZE_PCT   = 0.50          # reduce position size by 50%

# ─── Correlation filter ───────────────────────────────────────────────────────
MAX_SAME_SECTOR_POSITIONS = 3            # max positions in same sector

# ─── Time filters ─────────────────────────────────────────────────────────────
NO_ENTRY_BEFORE_MIN     = 5              # skip 9:15–9:20 (liquidity)
ORB_WINDOW_END          = "09:30"        # ORB setups only before this
PRIME_TIME_START        = "09:30"        # best time for momentum/reclaim
PRIME_TIME_END          = "11:30"        # peak volume window
MIDDAY_AVOID_START      = "13:00"        # lunch lull — be selective
MIDDAY_AVOID_END        = "14:00"        # resume normal scanning
NO_NEW_ENTRY_AFTER      = "14:45"        # no new entries after this
MARKET_OPEN             = "09:15"
MARKET_CLOSE            = "15:30"
EOD_CLOSE_TIME          = "15:00"        # close all positions by 3 PM

# ─── Sector definitions ───────────────────────────────────────────────────────
SECTOR_LEADERS = {
    "BANKING":    ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN"],
    "IT":         ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
    "AUTO":       ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "HEROMOTOCO"],
    "PHARMA":     ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP"],
    "FMCG":       ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR"],
    "METAL":      ["TATASTEEL", "HINDALCO", "JSWSTEEL", "COALINDIA", "VEDL"],
    "ENERGY":     ["RELIANCE", "ONGC", "BPCL", "IOC", "NTPC"],
    "FINANCIAL":  ["BAJFINANCE", "BAJAJFINSV", "HDFCAMC", "LICHSGFIN", "MUTHOOTFIN"],
}

# ─── Timezone ─────────────────────────────────────────────────────────────────
TIMEZONE                = "Asia/Kolkata"
