# ─── Nifty 50 ─────────────────────────────────────────────────────────────────
NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "HCLTECH", "AXISBANK", "BAJFINANCE", "ASIANPAINT",
    "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO",
    "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL",
    "TECHM", "NESTLEIND", "DRREDDY", "DIVISLAB", "CIPLA",
    "BAJAJFINSV", "HINDALCO", "JSWSTEEL", "TATASTEEL", "GRASIM",
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "EICHERMOT", "HEROMOTOCO",
    "BRITANNIA", "INDUSINDBK", "SBILIFE", "HDFCLIFE", "TATACONSUM",
    "BAJAJ-AUTO", "UPL", "TATAMOTORS", "M&M", "LTIM",
]

# ─── High volume extras (Nifty Next 50 + liquid midcaps) ─────────────────────
HIGH_VOLUME_EXTRAS = [
    # Banking & Finance
    "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "IDFCFIRSTB",
    "FEDERALBNK", "BANDHANBNK", "RBLBANK", "KARURVYSYA", "LICHSGFIN",
    "MUTHOOTFIN", "CHOLAFIN", "M&MFIN", "MANAPPURAM", "SUNDARMFIN",

    # IT & Tech
    "PERSISTENT", "COFORGE", "MPHASIS", "LTTS", "KPITTECH",
    "TATAELXSI", "ZENSARTECH", "NIITTECH", "INTELLECT", "HAPPSTMNDS",

    # Pharma & Healthcare
    "AUROPHARMA", "TORNTPHARM", "ALKEM", "LALPATHLAB", "METROPOLIS",
    "FORTIS", "MAXHEALTH", "IPCALAB", "GLENMARK", "NATCOPHARM",

    # Auto & Auto Ancillary
    "TVSMOTOR", "ASHOKLEY", "MOTHERSON", "BOSCHLTD", "AMARAJABAT",
    "EXIDEIND", "MRF", "APOLLOTYRE", "CEATLTD", "BALKRISIND",

    # Metals & Mining
    "VEDL", "NMDC", "SAIL", "NATIONALUM", "JINDALSTEL",
    "WELCORP", "RATNAMANI", "APL", "HINDCOPPER", "MOIL",

    # Energy & Power
    "RECLTD", "PFC", "IRFC", "HUDCO", "NBCC",
    "CESC", "TORNTPOWER", "TATAPOWER", "ADANIGREEN", "ADANIPOWER",

    # FMCG & Consumer
    "DABUR", "MARICO", "COLPAL", "EMAMILTD", "GODREJCP",
    "PGHH", "JUBLFOOD", "WESTLIFE", "DEVYANI", "SAPPHIRE",

    # Infra & Capital Goods
    "HAL", "BEL", "BHEL", "RVNL", "IRCTC",
    "SIEMENS", "ABB", "CUMMINSIND", "THERMAX", "KEC",

    # Cement & Materials
    "AMBUJACEM", "ACC", "SHREECEM", "RAMCOCEM", "JKCEMENT",

    # Others — high volume liquid
    "ZEEL", "IDEA", "YESBANK", "GMRINFRA", "DLF",
    "GODREJPROP", "OBEROIRLTY", "PHOENIXLTD", "PRESTIGE", "BRIGADE",
]

# ─── Index instruments for regime detection ───────────────────────────────────
INDEX_INSTRUMENTS = [
    "NIFTY 50",
    "NIFTY BANK",
    "NIFTY FIN SERVICE",
    "NIFTY IT",
    "NIFTY AUTO",
    "NIFTY PHARMA",
    "NIFTY METAL",
]

OPTIONS_UNIVERSE = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

# ─── Sector map ───────────────────────────────────────────────────────────────
SECTOR_MAP = {
    # Banking
    "HDFCBANK": "BANKING",    "ICICIBANK": "BANKING",   "KOTAKBANK": "BANKING",
    "AXISBANK": "BANKING",    "SBIN": "BANKING",         "INDUSINDBK": "BANKING",
    "BANKBARODA": "BANKING",  "PNB": "BANKING",          "CANBK": "BANKING",
    "IDFCFIRSTB": "BANKING",  "FEDERALBNK": "BANKING",   "BANDHANBNK": "BANKING",
    "RBLBANK": "BANKING",     "KARURVYSYA": "BANKING",   "YESBANK": "BANKING",

    # NBFC & Finance
    "BAJFINANCE": "NBFC",     "BAJAJFINSV": "NBFC",      "LICHSGFIN": "NBFC",
    "MUTHOOTFIN": "NBFC",     "CHOLAFIN": "NBFC",        "M&MFIN": "NBFC",
    "MANAPPURAM": "NBFC",     "SUNDARMFIN": "NBFC",

    # Insurance
    "SBILIFE": "INSURANCE",   "HDFCLIFE": "INSURANCE",

    # IT
    "TCS": "IT",              "INFY": "IT",              "HCLTECH": "IT",
    "WIPRO": "IT",            "TECHM": "IT",             "LTIM": "IT",
    "PERSISTENT": "IT",       "COFORGE": "IT",           "MPHASIS": "IT",
    "LTTS": "IT",             "KPITTECH": "IT",          "TATAELXSI": "IT",
    "ZENSARTECH": "IT",       "NIITTECH": "IT",          "INTELLECT": "IT",
    "HAPPSTMNDS": "IT",

    # Oil & Gas
    "RELIANCE": "OIL_GAS",   "ONGC": "OIL_GAS",         "BPCL": "OIL_GAS",

    # Pharma
    "SUNPHARMA": "PHARMA",    "DRREDDY": "PHARMA",       "CIPLA": "PHARMA",
    "DIVISLAB": "PHARMA",     "AUROPHARMA": "PHARMA",    "TORNTPHARM": "PHARMA",
    "ALKEM": "PHARMA",        "IPCALAB": "PHARMA",       "GLENMARK": "PHARMA",
    "NATCOPHARM": "PHARMA",

    # Healthcare
    "APOLLOHOSP": "HEALTHCARE", "LALPATHLAB": "HEALTHCARE", "METROPOLIS": "HEALTHCARE",
    "FORTIS": "HEALTHCARE",   "MAXHEALTH": "HEALTHCARE",

    # Auto
    "MARUTI": "AUTO",         "TATAMOTORS": "AUTO",      "M&M": "AUTO",
    "HEROMOTOCO": "AUTO",     "BAJAJ-AUTO": "AUTO",      "EICHERMOT": "AUTO",
    "TVSMOTOR": "AUTO",       "ASHOKLEY": "AUTO",

    # Auto Ancillary
    "MOTHERSON": "AUTO_ANC",  "BOSCHLTD": "AUTO_ANC",   "AMARAJABAT": "AUTO_ANC",
    "EXIDEIND": "AUTO_ANC",   "MRF": "AUTO_ANC",        "APOLLOTYRE": "AUTO_ANC",
    "CEATLTD": "AUTO_ANC",    "BALKRISIND": "AUTO_ANC",

    # Metals
    "JSWSTEEL": "METALS",     "TATASTEEL": "METALS",     "HINDALCO": "METALS",
    "VEDL": "METALS",         "SAIL": "METALS",          "NMDC": "METALS",
    "NATIONALUM": "METALS",   "JINDALSTEL": "METALS",    "WELCORP": "METALS",
    "HINDCOPPER": "METALS",   "MOIL": "METALS",

    # Power & Energy
    "NTPC": "POWER",          "POWERGRID": "POWER",      "COALINDIA": "ENERGY",
    "RECLTD": "POWER",        "PFC": "POWER",            "IRFC": "POWER",
    "HUDCO": "POWER",         "TATAPOWER": "POWER",      "CESC": "POWER",
    "TORNTPOWER": "POWER",    "ADANIGREEN": "POWER",     "ADANIPOWER": "POWER",

    # Infra & Defence
    "LT": "INFRA",            "HAL": "DEFENCE",          "BEL": "DEFENCE",
    "BHEL": "CAPITAL_GOODS",  "RVNL": "INFRA",           "IRCTC": "TRAVEL",
    "KEC": "INFRA",           "SIEMENS": "CAPITAL_GOODS","ABB": "CAPITAL_GOODS",
    "CUMMINSIND": "CAPITAL_GOODS", "THERMAX": "CAPITAL_GOODS",
    "NBCC": "INFRA",          "GMRINFRA": "INFRA",

    # FMCG
    "HINDUNILVR": "FMCG",    "ITC": "FMCG",             "BRITANNIA": "FMCG",
    "NESTLEIND": "FMCG",      "TATACONSUM": "FMCG",      "DABUR": "FMCG",
    "MARICO": "FMCG",         "COLPAL": "FMCG",          "EMAMILTD": "FMCG",
    "GODREJCP": "FMCG",       "PGHH": "FMCG",

    # Consumer & QSR
    "JUBLFOOD": "CONSUMER",   "WESTLIFE": "CONSUMER",    "DEVYANI": "CONSUMER",
    "SAPPHIRE": "CONSUMER",   "TITAN": "CONSUMER",

    # Cement
    "ULTRACEMCO": "CEMENT",   "GRASIM": "CEMENT",        "AMBUJACEM": "CEMENT",
    "ACC": "CEMENT",          "SHREECEM": "CEMENT",      "RAMCOCEM": "CEMENT",
    "JKCEMENT": "CEMENT",

    # Paints
    "ASIANPAINT": "PAINTS",

    # Telecom
    "BHARTIARTL": "TELECOM",  "IDEA": "TELECOM",

    # Real Estate
    "DLF": "REALTY",          "GODREJPROP": "REALTY",    "OBEROIRLTY": "REALTY",
    "PHOENIXLTD": "REALTY",   "PRESTIGE": "REALTY",      "BRIGADE": "REALTY",

    # Conglomerate
    "ADANIENT": "CONGLOMERATE", "ADANIPORTS": "PORTS",

    # Others
    "ZEEL": "MEDIA",          "UPL": "AGRI",             "APL": "METALS",
    "RATNAMANI": "METALS",
}

FULL_UNIVERSE = list(dict.fromkeys(NIFTY_50 + HIGH_VOLUME_EXTRAS))  # deduped, 150 stocks


def get_sector(symbol: str) -> str:
    return SECTOR_MAP.get(symbol, "OTHER")


def get_symbols_by_sector(sector: str) -> list:
    return [sym for sym, sec in SECTOR_MAP.items() if sec == sector]


def get_top_liquid_stocks(n: int = 50) -> list:
    """Return top N most liquid stocks for breadth sampling."""
    return NIFTY_50[:n]
