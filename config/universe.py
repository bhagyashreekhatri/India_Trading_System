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


# ─── Company-name aliases for news search (Fix #18) ──────────────────────────
# NewsAPI rarely uses ticker symbols ("RELIANCE", "HDFCBANK") in headlines —
# it uses official names. This map lets the news client query with both.
# Falls back to the symbol itself if not listed.
COMPANY_NAMES = {
    # Nifty 50 — most-covered names
    "RELIANCE":   "Reliance Industries",
    "TCS":        "Tata Consultancy Services",
    "HDFCBANK":   "HDFC Bank",
    "INFY":       "Infosys",
    "ICICIBANK":  "ICICI Bank",
    "HINDUNILVR": "Hindustan Unilever",
    "SBIN":       "State Bank of India",
    "BHARTIARTL": "Bharti Airtel",
    "ITC":        "ITC Limited",
    "KOTAKBANK":  "Kotak Mahindra Bank",
    "LT":         "Larsen Toubro",
    "HCLTECH":    "HCL Technologies",
    "AXISBANK":   "Axis Bank",
    "BAJFINANCE": "Bajaj Finance",
    "ASIANPAINT": "Asian Paints",
    "MARUTI":     "Maruti Suzuki",
    "SUNPHARMA":  "Sun Pharmaceutical",
    "TITAN":      "Titan Company",
    "ULTRACEMCO": "UltraTech Cement",
    "WIPRO":      "Wipro",
    "ONGC":       "Oil and Natural Gas Corporation",
    "NTPC":       "NTPC Limited",
    "POWERGRID":  "Power Grid Corporation",
    "COALINDIA":  "Coal India",
    "BPCL":       "Bharat Petroleum",
    "TECHM":      "Tech Mahindra",
    "NESTLEIND":  "Nestle India",
    "DRREDDY":    "Dr Reddys Laboratories",
    "DIVISLAB":   "Divis Laboratories",
    "CIPLA":      "Cipla",
    "BAJAJFINSV": "Bajaj Finserv",
    "HINDALCO":   "Hindalco Industries",
    "JSWSTEEL":   "JSW Steel",
    "TATASTEEL":  "Tata Steel",
    "GRASIM":     "Grasim Industries",
    "ADANIENT":   "Adani Enterprises",
    "ADANIPORTS": "Adani Ports",
    "APOLLOHOSP": "Apollo Hospitals",
    "EICHERMOT":  "Eicher Motors",
    "HEROMOTOCO": "Hero MotoCorp",
    "BRITANNIA":  "Britannia Industries",
    "INDUSINDBK": "IndusInd Bank",
    "SBILIFE":    "SBI Life Insurance",
    "HDFCLIFE":   "HDFC Life Insurance",
    "TATACONSUM": "Tata Consumer Products",
    "BAJAJ-AUTO": "Bajaj Auto",
    "UPL":        "UPL Limited",
    "TATAMOTORS": "Tata Motors",
    "M&M":        "Mahindra Mahindra",
    "LTIM":       "LTIMindtree",
    # High-volume extras commonly in news
    "ADANIGREEN": "Adani Green Energy",
    "ADANIPOWER": "Adani Power",
    "TATAPOWER":  "Tata Power",
    "BANKBARODA": "Bank of Baroda",
    "PNB":        "Punjab National Bank",
    "CANBK":      "Canara Bank",
    "YESBANK":    "Yes Bank",
    "BANDHANBNK": "Bandhan Bank",
    "PERSISTENT": "Persistent Systems",
    "COFORGE":    "Coforge",
    "MPHASIS":    "Mphasis",
    "TATAELXSI":  "Tata Elxsi",
    "TVSMOTOR":   "TVS Motor",
    "MOTHERSON":  "Samvardhana Motherson",
    "BOSCHLTD":   "Bosch",
    "MRF":        "MRF Limited",
    "VEDL":       "Vedanta",
    "NMDC":       "NMDC Limited",
    "SAIL":       "Steel Authority of India",
    "IRCTC":      "IRCTC",
    "HAL":        "Hindustan Aeronautics",
    "BEL":        "Bharat Electronics",
    "DLF":        "DLF Limited",
    "BHEL":       "BHEL",
    "RVNL":       "Rail Vikas Nigam",
    "IDEA":       "Vodafone Idea",
    "ZEEL":       "Zee Entertainment",
    "DABUR":      "Dabur India",
    "MARICO":     "Marico",
}


def get_company_name(symbol: str) -> str:
    """Return official company name for news search; fall back to symbol."""
    return COMPANY_NAMES.get(symbol, symbol)


def get_sector(symbol: str) -> str:
    return SECTOR_MAP.get(symbol, "OTHER")


def get_symbols_by_sector(sector: str) -> list:
    return [sym for sym, sec in SECTOR_MAP.items() if sec == sector]


def get_top_liquid_stocks(n: int = 50) -> list:
    """Return top N most liquid stocks for breadth sampling."""
    return NIFTY_50[:n]
