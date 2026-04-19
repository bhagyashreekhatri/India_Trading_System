from langchain.tools import tool
import json
from memory.chroma_client import ChromaMemory

_chroma = None
def get_chroma():
    global _chroma
    if _chroma is None: _chroma = ChromaMemory()
    return _chroma

@tool("Query similar past signals from ChromaDB")
def query_similar_signals(setup_type: str, regime: str) -> str:
    """Find past signals with same setup+regime. Returns win_rate and avg_r."""
    result = get_chroma().query_similar_signals(setup_type=setup_type, regime=regime)
    return json.dumps({"setup_type": setup_type, "regime": regime, "history": result,
                       "context": f"Found {result['found']} similar signals. Win rate: {result['win_rate']}% Avg R: {result['avg_r']}"
                       if result["found"] > 0 else "No historical data yet."})

@tool("Store trade outcome in ChromaDB")
def store_signal_outcome(symbol: str, setup_type: str, regime: str, score: float,
                         grade: str, entry: float, sl: float, target: float,
                         outcome: str, pnl_r: float) -> str:
    """Store completed trade outcome for future learning."""
    get_chroma().store_signal_outcome(symbol=symbol, setup_type=setup_type, regime=regime,
                                      score=score, grade=grade, entry=entry, sl=sl,
                                      target=target, outcome=outcome, pnl_r=pnl_r)
    return json.dumps({"stored": True, "symbol": symbol, "outcome": outcome})

@tool("Get regime history from ChromaDB")
def get_regime_history(regime: str) -> str:
    """Get past sessions with same regime to understand what setups worked."""
    history = get_chroma().get_regime_history(regime, n=5)
    return json.dumps({"regime": regime, "history": history, "count": len(history)})

CHROMA_TOOLS = [query_similar_signals, store_signal_outcome, get_regime_history]
