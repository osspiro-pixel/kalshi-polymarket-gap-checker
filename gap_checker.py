"""
gap_checker.py

Pulls live crypto markets from Kalshi and Polymarket, lines up the ones that
look like the same event, and prints the price gap between venues.

Also dumps every comparison to snapshots.csv so you build history instead of
staring at one moment in time.

Run:  python gap_checker.py
Needs: pip install requests
"""

import csv
import json
import os
import time
from datetime import datetime, timezone

import requests

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
POLY = "https://gamma-api.polymarket.com/markets"

CATEGORY = "Crypto"          # change to "Politics", "Economics", etc.
MIN_VOLUME = 100             # ignore markets nobody trades
GAP_THRESHOLD = 0.03         # only print gaps bigger than this (3 cents)
SNAPSHOT_FILE = "snapshots.csv"

KEYWORDS = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol",
            "dogecoin", "doge", "xrp", "satoshi", "crypto"]


# ----------------------------------------------------------------------
# KALSHI
# ----------------------------------------------------------------------

def kalshi_series(category):
    """Every series in a category. This is the fix for the MVE parlay flood --
    we ask for what we want instead of scrolling past 12,000 junk markets."""
    out = []
    cursor = None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{KALSHI}/series", params=params, timeout=20).json()
        batch = r.get("series", [])
        out += [s for s in batch if s.get("category") == category]
        cursor = r.get("cursor")
        if not cursor or not batch:
            break
    return out


def kalshi_markets(series_list):
    """Walk every series and keep markets with real volume and a live quote."""
    live = []
    for i, s in enumerate(series_list, 1):
        ticker = s.get("ticker")
        try:
            r = requests.get(
                f"{KALSHI}/markets",
                params={"series_ticker": ticker, "status": "open", "limit": 200},
                timeout=20,
            ).json()
        except Exception as e:
            print(f"   ! {ticker} failed: {e}")
            continue

        for m in r.get("markets", []):
            bid = float(m.get("yes_bid_dollars") or 0)
            ask = float(m.get("yes_ask_dollars") or 0)
            vol = float(m.get("volume") or 0)
            if vol < MIN_VOLUME or ask == 0:
                continue
            live.append({
                "venue": "kalshi",
                "title": m.get("title", ""),
                "ticker": m.get("ticker"),
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 4),
                "volume": vol,
                "rules": (m.get("rules_primary") or "").strip(),
            })

        if i % 25 == 0:
            print(f"   ...{i}/{len(series_list)} series scanned")
        time.sleep(0.05)
    return live


# ----------------------------------------------------------------------
# POLYMARKET
# ----------------------------------------------------------------------

def poly_markets():
    """Paginate the gamma API. 100 per page is the real cap regardless of
    what you put in limit."""
    out = []
    offset = 0
    while offset < 2000:
        r = requests.get(
            POLY,
            params={"limit": 100, "offset": offset, "closed": False,
                    "order": "volumeNum", "ascending": False},
            timeout=20,
        ).json()
        if not r:
            break
        out += r
        offset += 100
        time.sleep(0.05)

    live = []
    for m in out:
        q = (m.get("question") or "").lower()
        if not any(w in q for w in KEYWORDS):
            continue
        try:
            prices = json.loads(m.get("outcomePrices") or "[]")
            yes = float(prices[0])
        except Exception:
            continue
        vol = float(m.get("volumeNum") or 0)
        if vol < MIN_VOLUME or yes <= 0:
            continue
        live.append({
            "venue": "polymarket",
            "title": m.get("question", ""),
            "ticker": m.get("slug", ""),
            "bid": yes,
            "ask": yes,
            "mid": round(yes, 4),
            "volume": vol,
            "rules": (m.get("description") or "").strip(),
        })
    return live


# ----------------------------------------------------------------------
# MATCHING  -- the actually hard part
# ----------------------------------------------------------------------

STOP = {"will", "the", "be", "on", "in", "by", "at", "to", "a", "of", "or",
        "and", "above", "below", "reach", "hit", "price", "market", "any"}


def fingerprint(title):
    """Words + numbers that matter. Crude on purpose -- you want to see it
    fail so you know what to fix."""
    t = title.lower().replace("$", " ").replace(",", "")
    tokens = {w.strip("?.()") for w in t.split()}
    return {w for w in tokens if w and w not in STOP and len(w) > 1}


def match(kalshi_list, poly_list):
    pairs = []
    for k in kalshi_list:
        kf = fingerprint(k["title"])
        best, best_score = None, 0
        for p in poly_list:
            pf = fingerprint(p["title"])
            if not kf or not pf:
                continue
            score = len(kf & pf) / len(kf | pf)   # Jaccard
            if score > best_score:
                best, best_score = p, score
        if best and best_score >= 0.35:
            pairs.append((k, best, round(best_score, 2)))
    return pairs


# ----------------------------------------------------------------------

def main():
    print(f"[1/4] pulling Kalshi {CATEGORY} series...")
    series = kalshi_series(CATEGORY)
    print(f"      {len(series)} series")

    print("[2/4] pulling tradeable Kalshi markets...")
    k = kalshi_markets(series)
    print(f"      {len(k)} with volume >= {MIN_VOLUME}")

    print("[3/4] pulling Polymarket...")
    p = poly_markets()
    print(f"      {len(p)} crypto markets with volume")

    print("[4/4] matching...\n")
    pairs = match(k, p)
    pairs.sort(key=lambda x: abs(x[0]["mid"] - x[1]["mid"]), reverse=True)

    stamp = datetime.now(timezone.utc).isoformat()
    rows = []
    shown = 0

    for km, pm, score in pairs:
        gap = round(km["mid"] - pm["mid"], 4)
        rows.append({
            "timestamp": stamp,
            "kalshi_title": km["title"], "kalshi_ticker": km["ticker"],
            "kalshi_bid": km["bid"], "kalshi_ask": km["ask"],
            "poly_title": pm["title"], "poly_slug": pm["ticker"],
            "poly_price": pm["mid"],
            "gap": gap, "match_score": score,
        })

        if abs(gap) < GAP_THRESHOLD:
            continue
        shown += 1
        print(f"GAP {gap:+.3f}   (match confidence {score})")
        print(f"  KALSHI  {km['mid']:.3f}  {km['title']}")
        print(f"  POLY    {pm['mid']:.3f}  {pm['title']}")
        print(f"  --- kalshi rules: {km['rules'][:220]}")
        print(f"  --- poly rules:   {pm['rules'][:220]}")
        print()

    print(f"{len(pairs)} matched pairs, {shown} above {GAP_THRESHOLD:.0%} gap")

    if rows:
        new = not os.path.exists(SNAPSHOT_FILE)
        with open(SNAPSHOT_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            if new:
                w.writeheader()
            w.writerows(rows)
        print(f"appended {len(rows)} rows to {SNAPSHOT_FILE}")


if __name__ == "__main__":
    main()
