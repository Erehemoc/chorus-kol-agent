"""Deterministic post understanding: which tokens a post talks about, and with what
sentiment, conviction and urgency. Every number comes with the words that produced it,
so the reasoning trail can show *why*.

No model calls: the same text always gives the same reading (replayable).
"""
from __future__ import annotations

import re

# Tokens we can price (symbol -> CoinGecko id). Names are matched as whole words too.
UNIVERSE = {
    "BTC": ("bitcoin", ["bitcoin"]), "ETH": ("ethereum", ["ethereum", "ether"]),
    "SOL": ("solana", ["solana"]), "XRP": ("ripple", ["ripple"]), "BNB": ("binancecoin", []),
    "DOGE": ("dogecoin", ["dogecoin"]), "ADA": ("cardano", ["cardano"]),
    "HYPE": ("hyperliquid", ["hyperliquid"]), "SUI": ("sui", []), "AVAX": ("avalanche-2", ["avalanche"]),
    "LINK": ("chainlink", ["chainlink"]), "TON": ("the-open-network", ["toncoin"]),
    "ENA": ("ethena", ["ethena"]), "PEPE": ("pepe", []), "TRX": ("tron", ["tron"]),
    "LTC": ("litecoin", ["litecoin"]), "AAVE": ("aave", []), "UNI": ("uniswap", ["uniswap"]),
    "ARB": ("arbitrum", ["arbitrum"]), "OP": ("optimism", []), "NEAR": ("near", []),
    "WLD": ("worldcoin-wld", ["worldcoin"]), "PUMP": ("pump-fun", []), "ONDO": ("ondo-finance", []),
    "TAO": ("bittensor", ["bittensor"]), "XMR": ("monero", ["monero"]), "ZEC": ("zcash", ["zcash"]),
}
# Bare uppercase words that are also English or finance jargon: only counted as $CASHTAG.
AMBIGUOUS = {"OP", "NEAR", "UNI", "TON", "PUMP", "LINK", "SUI", "ENA", "TAO", "HYPE", "ONDO"}

BULL = {  # exact words (lower-case); multi-word phrases are matched as substrings
    "bought": 2, "buying": 2, "buys": 1.5, "buy": 1.5, "accumulating": 2, "accumulated": 2,
    "accumulation": 1.5, "accumulates": 2, "long": 1.5, "longs": 1, "bullish": 2, "breakout": 1.5,
    "pumping": 1.5, "rally": 1.5, "rallies": 1.5, "surge": 1.5, "surges": 1.5, "surged": 1.5,
    "soar": 1.5, "soars": 1.5, "inflow": 1.5, "inflows": 1.5, "approved": 1.5, "approves": 1.5,
    "ath": 1.5, "all-time high": 2, "record high": 2, "undervalued": 1.5, "reclaims": 1,
    "reclaimed": 1, "withdrew": 1, "withdrawn": 1, "partnership": 1, "gains": 1, "rises": 1,
    "jumps": 1.5, "jumped": 1.5, "higher": 0.5, "adds": 1, "added": 0.5,
}
BEAR = {
    "sold": 2, "selling": 2, "sells": 1.5, "sell": 1.5, "dump": 2, "dumping": 2, "dumped": 2,
    "short": 1.5, "shorts": 1, "shorting": 1.5, "bearish": 2, "crash": 2, "crashes": 2,
    "crashed": 2, "plunge": 2, "plunges": 2, "plunged": 2, "drop": 1.5, "dropped": 1.5,
    "drops": 1.5, "falls": 1.5, "fell": 1.5, "liquidated": 1.5, "liquidation": 1,
    "liquidations": 1, "outflow": 1.5, "outflows": 1.5, "hack": 2, "hacked": 2.5, "exploit": 2.5,
    "exploited": 2.5, "scam": 2, "rug": 2.5, "deposited": 1, "deposits": 1, "lawsuit": 1.5,
    "sec sues": 2, "delist": 2, "delisting": 2, "unlock": 1, "unlocks": 1, "overvalued": 1.5,
    "rejection": 1, "loses": 1, "lower": 0.5, "slides": 1, "tumbles": 1.5,
}
NEGATORS = {"not", "no", "never", "don't", "dont", "isn't", "won't", "without"}
CERTAIN = {"definitely": 1, "100%": 1.5, "guaranteed": 1, "huge": 0.5, "massive": 0.8,
           "all in": 2, "loaded": 1, "conviction": 1, "i bought": 1.5, "we bought": 1.5,
           "i'm long": 1.5, "im long": 1.5, "whale": 0.5, "smart money": 1}
HEDGE = {"maybe": -1, "might": -0.7, "could": -0.5, "possibly": -0.8, "if ": -0.3,
         "not financial advice": -0.5, "nfa": -0.5, "rumor": -0.8, "unconfirmed": -1, "?": -0.3}
URGENT = {"breaking": 2, "just in": 2, "now": 1, "right now": 1.5, "today": 0.5, "minutes": 1,
          "hours ago": 0.5, "alert": 1, "urgent": 2, "🚨": 1.5, "⚡": 0.5, "!!": 1}

_WORD = re.compile(r"[a-z0-9$%'\-]+")


def find_tokens(text: str) -> list[str]:
    found = set()
    for sym in re.findall(r"\$([A-Za-z]{2,6})\b", text):
        if sym.upper() in UNIVERSE:
            found.add(sym.upper())
    for sym in re.findall(r"\b([A-Z]{2,5})\b", text):
        if sym in UNIVERSE and sym not in AMBIGUOUS:
            found.add(sym)
    low = text.lower()
    for sym, (_, names) in UNIVERSE.items():
        if any(re.search(rf"\b{re.escape(n)}\b", low) for n in names):
            found.add(sym)
    return sorted(found)


def _score(text: str, lex: dict) -> tuple[float, list[str]]:
    low = text.lower()
    words = _WORD.findall(low)
    hits, total = [], 0.0
    for key, w in lex.items():
        if " " in key or not key.replace("-", "").isalnum():
            if key in low:
                total += w
                hits.append(key)
    for i, word in enumerate(words):
        w = lex.get(word.strip("$'"))
        if w is None:
            continue
        neg = any(x in NEGATORS for x in words[max(0, i - 3):i])
        total += -w if neg else w
        hits.append(("not " if neg else "") + word)
    return total, hits


MAX_TOKENS_PER_POST = 4  # digests ("market movers", daily roll-ups) are not a voice's call

_CLAUSE = re.compile(r"[\n.;!?]+")


def _mentions(clause: str, sym: str) -> bool:
    return sym in find_tokens(clause)


def read_post(text: str) -> dict:
    """-> {tokens, calls{tok: {direction, sentiment, why}}, conviction, urgency, why}

    Sentiment is scored per token, only on the clauses that mention that token, so
    "BTC saw outflows while ZEC saw inflows" is bearish BTC and bullish ZEC.
    """
    tokens = find_tokens(text)
    cert, cert_hits = _score(text, CERTAIN)
    hedge, hedge_hits = _score(text, HEDGE)
    urg, urg_hits = _score(text, URGENT)
    letters = [c for c in text if c.isalpha()]
    caps = sum(c.isupper() for c in letters) / max(1, len(letters))
    if caps > 0.5 and len(letters) > 12:
        urg += 1
        urg_hits.append("ALL CAPS")
    calls = {}
    digest = len(tokens) > MAX_TOKENS_PER_POST
    clauses = [c for c in _CLAUSE.split(text) if c.strip()]
    for tok in ([] if digest else tokens):
        scope = " . ".join(c for c in clauses if _mentions(c, tok)) or text
        if len(tokens) == 1:
            scope = text
        bull, bh = _score(scope, BULL)
        bear, brh = _score(scope, BEAR)
        sent = bull - bear
        direction = 1 if sent >= 1 else -1 if sent <= -1 else 0
        calls[tok] = {"direction": direction, "sentiment": round(sent, 2),
                      "evidence": re.sub(r"\s+", " ", scope).strip()[:280],
                      "strength": min(1.0, abs(sent) / 4), "why": {"bull": bh, "bear": brh}}
    strength = max((c["strength"] for c in calls.values()), default=0.0)
    conviction = max(0.0, min(1.0, 0.35 + 0.15 * cert + 0.2 * hedge + 0.3 * strength))
    return {
        "tokens": tokens, "digest": digest, "calls": calls,
        "conviction": round(conviction, 3), "urgency": round(max(0.0, min(1.0, urg / 3)), 3),
        "why": {"certainty": cert_hits, "hedge": hedge_hits, "urgency": urg_hits},
    }
