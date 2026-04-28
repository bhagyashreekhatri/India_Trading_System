"""
NewsAPI client + Groq LLM sentiment scorer.
Fetches Indian market news and scores sentiment per stock.

Hardening (Fix #4):
  - Persistent daily cache on disk (./news_cache.json) — survives restarts so
    Groq quota isn't re-burned on systemd restart.
  - Typed Groq exception handling — RateLimitError honours Retry-After header,
    APITimeoutError / APIConnectionError get exponential backoff with jitter,
    BadRequestError / JSONDecodeError fail fast, never silently 0.5.
  - response_format={"type": "json_object"} forces structured output.
  - Per-call timeout=10 s.
  - Telemetry counters on the client (calls / 429s / retries / failures).
"""
import os
import json
import time as _time
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from newsapi import NewsApiClient
import groq
from groq import Groq

from config.settings import NEWS_API_KEY, GROQ_API_KEY, GROQ_MODEL
from scoring.engine import NewsData


CACHE_FILE = Path("./news_cache.json")
GROQ_TIMEOUT_S = 10
GROQ_MAX_ATTEMPTS = 4

SENTIMENT_PROMPT = """You are a financial news analyst for Indian stock markets.

Analyze this news headline for the stock {symbol} and return ONLY a JSON object.

Headline: "{headline}"

Return ONLY this JSON (no explanation):
{{
  "sentiment": 0.8,
  "event_type": "earnings",
  "reason": "brief reason in 10 words"
}}

Rules:
- sentiment: 0.0 to 1.0 (0=very negative, 0.5=neutral, 1.0=very positive)
- event_type: one of: earnings, split, buyback, news, regulatory, results, dividend, none
- reason: max 10 words
"""


class NewsClient:
    """
    NewsAPI + Groq sentiment with persistent daily cache, typed retry, JSON mode.
    """

    def __init__(self):
        self._cache: dict = {}
        self._rate_limited_today = False
        self._newsapi_ok = False
        self._groq_ok = False

        # Telemetry counters (read by dashboard / EOD report later)
        self.stats = {
            "groq_calls": 0,
            "groq_success": 0,
            "groq_429": 0,
            "groq_timeout": 0,
            "groq_other_err": 0,
            "groq_retries": 0,
            "cache_hits": 0,
            "cache_writes": 0,
        }

        try:
            self.newsapi = NewsApiClient(api_key=NEWS_API_KEY)
            self._newsapi_ok = bool(NEWS_API_KEY)
        except Exception as e:
            print(f"[News] NewsAPI init failed (non-fatal): {e}")
            self.newsapi = None

        try:
            self.groq = Groq(api_key=GROQ_API_KEY)
            self._groq_ok = bool(GROQ_API_KEY)
        except Exception as e:
            print(f"[News] Groq init failed (non-fatal): {e}")
            self.groq = None

        # Load persistent cache from disk
        self._load_cache()

    # ─── Persistent cache ─────────────────────────────────────────────────────

    def _load_cache(self):
        """
        Load yesterday's + today's cache from disk. Anything older than 2 days
        is dropped to keep the file small.
        """
        if not CACHE_FILE.exists():
            return
        try:
            raw = json.loads(CACHE_FILE.read_text())
            today_str = datetime.now().strftime("%Y%m%d")
            yest_str  = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            kept = {}
            for k, v in raw.items():
                # Keys look like "RELIANCE_20260428"
                date_part = k.split("_")[-1] if "_" in k else ""
                if date_part in (today_str, yest_str):
                    # Reconstruct NewsData
                    kept[k] = NewsData(
                        symbol=v.get("symbol", ""),
                        has_news=v.get("has_news", False),
                        sentiment=v.get("sentiment", 0.5),
                        catalyst_type=v.get("catalyst_type", "none"),
                        headline=v.get("headline", ""),
                        llm_score=v.get("llm_score", 0.5),
                    )
            self._cache = kept
            print(f"[News] Loaded {len(kept)} cached entries from {CACHE_FILE}")
        except Exception as e:
            print(f"[News] Cache load failed (non-fatal): {e}")
            self._cache = {}

    def _save_cache(self):
        """Persist cache to disk. Called after every new write."""
        try:
            serial = {
                k: {
                    "symbol": v.symbol,
                    "has_news": v.has_news,
                    "sentiment": v.sentiment,
                    "catalyst_type": v.catalyst_type,
                    "headline": v.headline,
                    "llm_score": v.llm_score,
                }
                for k, v in self._cache.items()
            }
            CACHE_FILE.write_text(json.dumps(serial, indent=2))
            self.stats["cache_writes"] += 1
        except Exception as e:
            print(f"[News] Cache save failed (non-fatal): {e}")

    # ─── NewsAPI fetch ────────────────────────────────────────────────────────

    def _fetch_headlines(self, symbol: str, company_name: str = "") -> list[str]:
        if not self._newsapi_ok or self.newsapi is None:
            return []
        if self._rate_limited_today:
            return []
        query = company_name if company_name else symbol
        try:
            response = self.newsapi.get_everything(
                q=f"{query} stock India NSE",
                language="en",
                sort_by="publishedAt",
                from_param=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
                page_size=5,
            )
            articles = response.get("articles", [])
            return [a["title"] for a in articles if a.get("title")]
        except Exception as e:
            err_str = str(e)
            if "rateLimited" in err_str or "429" in err_str or "too many requests" in err_str.lower():
                self._rate_limited_today = True
                print("[News] NewsAPI rate limit hit — suspending fetches for today")
            else:
                print(f"[News] NewsAPI fetch error for {symbol}: {e}")
            return []

    # ─── Groq sentiment with full hardening ───────────────────────────────────

    def _score_sentiment_with_llm(self, symbol: str, headline: str) -> tuple[float, str, str]:
        """
        Returns (sentiment_score, event_type, reason).
        Falls back to (0.5, "news", "") on permanent failure.

        Retry policy:
          - RateLimitError (429): honour Retry-After header if present, else
            exponential backoff with jitter (max 60 s per wait).
          - APITimeoutError / APIConnectionError: exponential backoff (max 20 s).
          - APIError (5xx etc.): exponential backoff (max 20 s).
          - BadRequestError: NO retry (prompt or model issue).
          - JSONDecodeError / ValueError / KeyError: NO retry (model output bad).
          - Up to GROQ_MAX_ATTEMPTS attempts total.
        """
        if not self._groq_ok or self.groq is None:
            return 0.5, "news", ""

        prompt = SENTIMENT_PROMPT.format(symbol=symbol, headline=headline)
        self.stats["groq_calls"] += 1

        for attempt in range(1, GROQ_MAX_ATTEMPTS + 1):
            try:
                response = self.groq.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=100,
                    response_format={"type": "json_object"},
                    timeout=GROQ_TIMEOUT_S,
                )
                content = response.choices[0].message.content.strip()
                # Strip any code-fence wrapping the model may have added
                content = content.replace("```json", "").replace("```", "").strip()
                data = json.loads(content)
                self.stats["groq_success"] += 1
                return (
                    float(data.get("sentiment", 0.5)),
                    str(data.get("event_type", "news")),
                    str(data.get("reason", "")),
                )

            except groq.RateLimitError as e:
                self.stats["groq_429"] += 1
                wait = self._retry_after_seconds(e) or self._backoff(attempt, cap=60)
                print(f"[News] Groq 429 on attempt {attempt}/{GROQ_MAX_ATTEMPTS} for {symbol}; waiting {wait:.1f}s")
                if attempt < GROQ_MAX_ATTEMPTS:
                    self.stats["groq_retries"] += 1
                    _time.sleep(wait)
                    continue

            except (groq.APITimeoutError, groq.APIConnectionError) as e:
                self.stats["groq_timeout"] += 1
                wait = self._backoff(attempt, cap=20)
                print(f"[News] Groq {type(e).__name__} on attempt {attempt} for {symbol}; waiting {wait:.1f}s")
                if attempt < GROQ_MAX_ATTEMPTS:
                    self.stats["groq_retries"] += 1
                    _time.sleep(wait)
                    continue

            except groq.BadRequestError as e:
                # Prompt malformed or model unavailable — don't retry, will keep failing.
                self.stats["groq_other_err"] += 1
                print(f"[News] Groq BadRequestError (no retry) for {symbol}: {e}")
                break

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                # Model returned non-JSON / unexpected shape — fall back, don't retry.
                self.stats["groq_other_err"] += 1
                print(f"[News] Groq malformed JSON for {symbol}: {e}")
                break

            except groq.APIError as e:
                # Generic 5xx / unknown groq error — backoff and retry.
                self.stats["groq_other_err"] += 1
                wait = self._backoff(attempt, cap=20)
                print(f"[News] Groq APIError on attempt {attempt} for {symbol}: {e}; waiting {wait:.1f}s")
                if attempt < GROQ_MAX_ATTEMPTS:
                    self.stats["groq_retries"] += 1
                    _time.sleep(wait)
                    continue

            except Exception as e:
                # Truly unexpected — log loud, don't retry.
                self.stats["groq_other_err"] += 1
                print(f"[News] Groq unexpected error for {symbol}: {type(e).__name__}: {e}")
                break

        # Permanent failure path — return neutral so the engine doesn't crash,
        # but the call has been logged loudly above so it's not silent corruption.
        print(f"[News] Groq permanent failure for {symbol}, returning neutral (0.5)")
        return 0.5, "news", ""

    @staticmethod
    def _retry_after_seconds(exc) -> Optional[float]:
        """Pull Retry-After header off a RateLimitError if present, plus a small jitter."""
        try:
            headers = getattr(exc, "response", None)
            if headers is not None:
                headers = headers.headers
                ra = headers.get("retry-after") or headers.get("Retry-After")
                if ra:
                    return float(ra) + random.uniform(0.1, 0.5)
        except Exception:
            pass
        return None

    @staticmethod
    def _backoff(attempt: int, cap: float) -> float:
        """Exponential backoff with jitter."""
        return min(cap, (2 ** attempt) + random.uniform(0, 1))

    # ─── Public API ───────────────────────────────────────────────────────────

    def get_news_for_symbol(self, symbol: str, company_name: str = "") -> NewsData:
        """
        Main entry. Returns NewsData. Daily-cached on disk.
        First call per (symbol, day) hits NewsAPI + Groq; subsequent calls
        return instantly from cache, even after a service restart.
        """
        cache_key = f"{symbol}_{datetime.now().strftime('%Y%m%d')}"
        if cache_key in self._cache:
            self.stats["cache_hits"] += 1
            return self._cache[cache_key]

        headlines = self._fetch_headlines(symbol, company_name)

        if not headlines:
            result = NewsData(
                symbol=symbol, has_news=False, sentiment=0.5,
                catalyst_type="none", headline="", llm_score=0.5,
            )
            self._cache[cache_key] = result
            self._save_cache()
            return result

        best_headline = headlines[0]
        llm_score, event_type, _reason = self._score_sentiment_with_llm(symbol, best_headline)

        # Lightweight rule-based check as a sanity blend
        negative_keywords = ["loss", "fraud", "penalty", "fine", "probe", "decline", "fall"]
        positive_keywords = ["profit", "beat", "growth", "surge", "record", "win", "strong"]
        h_low = best_headline.lower()
        rule = 0.5
        if any(k in h_low for k in positive_keywords):
            rule = 0.75
        elif any(k in h_low for k in negative_keywords):
            rule = 0.25

        final_score = (llm_score * 0.8) + (rule * 0.2)

        result = NewsData(
            symbol=symbol, has_news=True, sentiment=final_score,
            catalyst_type=event_type, headline=best_headline,
            llm_score=round(final_score, 3),
        )
        self._cache[cache_key] = result
        self._save_cache()
        return result

    def get_news_batch(self, symbols: list[str]) -> dict[str, NewsData]:
        return {s: self.get_news_for_symbol(s) for s in symbols}

    def get_stats(self) -> dict:
        """Return telemetry. Use from dashboard / EOD report."""
        return dict(self.stats)
