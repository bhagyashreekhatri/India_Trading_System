from langchain.tools import tool
import json
from data.news_client import NewsClient
from memory.chroma_client import ChromaMemory

_news = None
_chroma = None
def get_news():
    global _news
    if _news is None: _news = NewsClient()
    return _news
def get_chroma():
    global _chroma
    if _chroma is None: _chroma = ChromaMemory()
    return _chroma

def _news_score(llm_score, has_news, catalyst):
    if not has_news: return 0.5
    if catalyst == "earnings" and llm_score >= 0.7: return 1.0
    elif llm_score >= 0.7: return 1.0
    elif llm_score >= 0.5: return 0.7
    elif llm_score >= 0.3: return 0.4
    return -0.5

@tool("Get news sentiment for an NSE stock")
def get_news_sentiment(symbol: str) -> str:
    """Fetch news and score sentiment using LLM. Returns score 0-1 and catalyst type."""
    nd = get_news().get_news_for_symbol(symbol)
    if nd.has_news and nd.headline:
        try: get_chroma().store_news(symbol, nd.headline, nd.sentiment, nd.llm_score, nd.catalyst_type)
        except: pass
    return json.dumps({"symbol": symbol, "has_news": nd.has_news, "llm_score": nd.llm_score,
                       "catalyst_type": nd.catalyst_type, "headline": nd.headline,
                       "news_score": _news_score(nd.llm_score, nd.has_news, nd.catalyst_type)})

@tool("Get batch news sentiment for multiple stocks")
def get_batch_news(symbols: str) -> str:
    """Get news for comma-separated symbols efficiently."""
    results = {}
    for sym in [s.strip() for s in symbols.split(",")]:
        try:
            nd = get_news().get_news_for_symbol(sym)
            results[sym] = {"has_news": nd.has_news, "llm_score": nd.llm_score,
                            "catalyst_type": nd.catalyst_type,
                            "headline": nd.headline[:80] if nd.headline else "",
                            "news_score": _news_score(nd.llm_score, nd.has_news, nd.catalyst_type)}
        except:
            results[sym] = {"has_news": False, "llm_score": 0.5, "catalyst_type": "none",
                            "headline": "", "news_score": 0.5}
    return json.dumps(results)

@tool("Query past news from ChromaDB")
def query_past_news(symbol: str) -> str:
    """Check ChromaDB for recent news sentiment about a stock."""
    avg = get_chroma().get_recent_news_sentiment(symbol, days=3)
    past = get_chroma().query_news(symbol, f"news about {symbol}", n_results=3)
    return json.dumps({"symbol": symbol, "avg_sentiment_3d": avg,
                       "recent_headlines": [n["headline"] for n in past]})

NEWS_TOOLS = [get_news_sentiment, get_batch_news, query_past_news]
