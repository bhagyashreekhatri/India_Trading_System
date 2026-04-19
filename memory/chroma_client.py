"""
ChromaDB memory layer.
3 collections: news_signals, signal_patterns, regime_context.
"""
import chromadb
from chromadb.config import Settings
from datetime import datetime
from typing import Optional
import json

from config.settings import CHROMA_PERSIST_DIR


class ChromaMemory:

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False),
        )
        self.news      = self.client.get_or_create_collection("news_signals")
        self.patterns  = self.client.get_or_create_collection("signal_patterns")
        self.regimes   = self.client.get_or_create_collection("regime_context")

    # ── News signals ──────────────────────────────────────────────────────────

    def store_news(
        self,
        symbol:       str,
        headline:     str,
        sentiment:    float,
        llm_score:    float,
        event_type:   str = "news",
        source:       str = "newsapi",
    ):
        doc_id = f"news_{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.news.add(
            ids=[doc_id],
            documents=[headline],
            metadatas=[{
                "symbol":     symbol,
                "sentiment":  sentiment,
                "llm_score":  llm_score,
                "event_type": event_type,
                "source":     source,
                "date":       datetime.now().date().isoformat(),
                "time":       datetime.now().strftime("%H:%M"),
            }]
        )

    def query_news(self, symbol: str, query: str, n_results: int = 3) -> list[dict]:
        """Semantic search for news about a symbol."""
        try:
            results = self.news.query(
                query_texts=[query],
                n_results=n_results,
                where={"symbol": symbol},
            )
            if not results["documents"][0]:
                return []
            return [
                {
                    "headline": doc,
                    "metadata": meta,
                }
                for doc, meta in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                )
            ]
        except Exception:
            return []

    def get_recent_news_sentiment(self, symbol: str, days: int = 3) -> float:
        """Average sentiment score for a symbol over recent days."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()
        try:
            results = self.news.get(
                where={"$and": [
                    {"symbol": {"$eq": symbol}},
                    {"date": {"$gte": cutoff}},
                ]}
            )
            if not results["metadatas"]:
                return 0.5   # neutral default
            scores = [m["llm_score"] for m in results["metadatas"]]
            return sum(scores) / len(scores)
        except Exception:
            return 0.5

    # ── Signal patterns (trade history for learning) ───────────────────────────

    def store_signal_outcome(
        self,
        symbol:       str,
        setup_type:   str,
        regime:       str,
        score:        float,
        grade:        str,
        entry:        float,
        sl:           float,
        target:       float,
        outcome:      str,    # "hit_target" | "hit_sl" | "expired"
        pnl_r:        float,
    ):
        description = (
            f"{setup_type.replace('_', ' ')} on {symbol}, "
            f"{regime} regime, score {score:.1f}, grade {grade}, "
            f"outcome: {outcome} at {pnl_r:.1f}R"
        )
        doc_id = f"signal_{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.patterns.add(
            ids=[doc_id],
            documents=[description],
            metadatas=[{
                "symbol":     symbol,
                "setup_type": setup_type,
                "regime":     regime,
                "score":      score,
                "grade":      grade,
                "entry":      entry,
                "sl":         sl,
                "target":     target,
                "outcome":    outcome,
                "pnl_r":      pnl_r,
                "date":       datetime.now().date().isoformat(),
            }]
        )

    def query_similar_signals(
        self,
        setup_type: str,
        regime:     str,
        symbol:     Optional[str] = None,
        n_results:  int = 5,
    ) -> dict:
        """
        Find past signals similar to current setup.
        Returns win_rate and avg_r for context-aware scoring.
        """
        query = f"{setup_type.replace('_', ' ')} {regime} regime"
        where_filter = {"setup_type": {"$eq": setup_type}}

        try:
            results = self.patterns.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter,
            )
            metas = results["metadatas"][0] if results["metadatas"] else []
            if not metas:
                return {"found": 0, "win_rate": None, "avg_r": None}

            hits   = [m for m in metas if m["outcome"] == "hit_target"]
            avg_r  = sum(m["pnl_r"] for m in metas) / len(metas)
            return {
                "found":    len(metas),
                "win_rate": round(len(hits) / len(metas) * 100, 1),
                "avg_r":    round(avg_r, 2),
            }
        except Exception:
            return {"found": 0, "win_rate": None, "avg_r": None}

    # ── Regime context ────────────────────────────────────────────────────────

    def store_regime_snapshot(
        self,
        regime:           str,
        nifty_vwap_min:   int,
        breadth_score:    float,
        best_setups:      list[str],
        worst_setups:     list[str],
        notes:            str = "",
    ):
        description = (
            f"{regime} regime, Nifty VWAP {nifty_vwap_min} min, "
            f"breadth {breadth_score:.0%}, best: {', '.join(best_setups)}"
        )
        doc_id = f"regime_{datetime.now().strftime('%Y%m%d%H%M')}"
        self.regimes.add(
            ids=[doc_id],
            documents=[description],
            metadatas=[{
                "regime":          regime,
                "nifty_vwap_min":  nifty_vwap_min,
                "breadth_score":   breadth_score,
                "best_setups":     json.dumps(best_setups),
                "worst_setups":    json.dumps(worst_setups),
                "notes":           notes,
                "date":            datetime.now().date().isoformat(),
                "time":            datetime.now().strftime("%H:%M"),
            }]
        )

    def get_regime_history(self, regime: str, n: int = 10) -> list[dict]:
        try:
            results = self.regimes.query(
                query_texts=[f"{regime} regime"],
                n_results=n,
                where={"regime": {"$eq": regime}},
            )
            return results["metadatas"][0] if results["metadatas"] else []
        except Exception:
            return []
