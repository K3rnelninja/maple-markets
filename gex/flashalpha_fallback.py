"""
gex/flashalpha_fallback.py — GitHub Actions fallback GEX fetcher
Uses FlashAlpha free API to get GEX snapshots.
Free tier: individual stocks only, single-expiry.
We use SPY with next Friday's expiry as best-effort fallback.
Falls back gracefully if blocked.

Run via GitHub Actions:
    python -m gex.flashalpha_fallback
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("gex.flashalpha")

FLASHALPHA_KEY = os.environ.get("FLASHALPHA_API_KEY", "")
RENDER_URL = os.environ.get("RENDER_URL", "https://maple-markets.onrender.com")
PUSH_KEY = os.environ.get("GEX_PUSH_KEY", "zeroprofit-default-key")
FLASHALPHA_BASE = "https://lab.flashalpha.com/v1"

# Symbols to try, in priority order
# SPY/QQQ may be blocked on free tier (ETF restriction)
# Individual stocks work as proxies for market structure
SYMBOL_ATTEMPTS = [
    {"symbol": "SPY", "map_to": "es", "factor": 10.0},     # SPY × 10 ≈ ES
    {"symbol": "AAPL", "map_to": None, "factor": 1.0},      # test if API works
]

QQQ_ATTEMPTS = [
    {"symbol": "QQQ", "map_to": "nq", "factor": 40.0},     # QQQ × 40 ≈ NQ
]


def get_next_expiry():
    """Get next Friday's date as YYYY-MM-DD for single-expiry query."""
    today = datetime.utcnow().date()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7  # next friday, not today
    next_friday = today + timedelta(days=days_until_friday)
    return next_friday.strftime("%Y-%m-%d")


def fetch_gex(symbol, expiry=None):
    """Fetch GEX from FlashAlpha API."""
    url = f"{FLASHALPHA_BASE}/exposure/gex/{symbol}"
    headers = {"X-Api-Key": FLASHALPHA_KEY}
    params = {}
    if expiry:
        params["expiration"] = expiry

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            log.info(f"{symbol} GEX: flip={data.get('gamma_flip')}, "
                     f"regime={data.get('net_gex_label', data.get('regime'))}, "
                     f"net={data.get('net_gex')}")
            return data
        elif resp.status_code == 403:
            log.warning(f"{symbol} blocked on free tier: {resp.text[:200]}")
            return None
        elif resp.status_code == 429:
            log.warning(f"{symbol} rate limited")
            return None
        else:
            log.error(f"FlashAlpha {symbol} failed ({resp.status_code}): {resp.text[:200]}")
            return None
    except Exception as e:
        log.error(f"FlashAlpha {symbol} error: {e}")
        return None


def flashalpha_to_levels(data, factor=1.0):
    """Convert FlashAlpha response to our standard levels format."""
    if not data:
        return None

    strikes = data.get("strikes", [])

    # Extract call wall and put wall from response if available
    call_wall_data = data.get("call_wall", {})
    put_wall_data = data.get("put_wall", {})

    # Find additional walls from strikes
    positive = [(s.get("strike", 0), s.get("net_gex", s.get("gex", 0)))
                for s in strikes if s.get("net_gex", s.get("gex", 0)) > 0]
    positive.sort(key=lambda x: x[1], reverse=True)
    call_walls = [s[0] for s in positive[:3]]

    negative = [(s.get("strike", 0), s.get("net_gex", s.get("gex", 0)))
                for s in strikes if s.get("net_gex", s.get("gex", 0)) < 0]
    negative.sort(key=lambda x: x[1])
    put_walls = [s[0] for s in negative[:3]]

    # Use explicit call/put wall if provided
    if call_wall_data and call_wall_data.get("strike"):
        if call_wall_data["strike"] not in call_walls:
            call_walls.insert(0, call_wall_data["strike"])
            call_walls = call_walls[:3]

    if put_wall_data and put_wall_data.get("strike"):
        if put_wall_data["strike"] not in put_walls:
            put_walls.insert(0, put_wall_data["strike"])
            put_walls = put_walls[:3]

    hvl = data.get("gamma_flip", 0)
    net_gex = data.get("net_gex", 0)
    regime = data.get("net_gex_label", data.get("regime", "unknown"))
    if regime not in ("positive", "negative"):
        regime = "positive" if net_gex >= 0 else "negative"

    levels = {
        "hvl": round(hvl * factor, 2),
        "call_walls": sorted([round(w * factor, 2) for w in call_walls]),
        "put_walls": sorted([round(w * factor, 2) for w in put_walls]),
        "max_pain": round(hvl * factor, 2),  # approximation
        "net_gex": net_gex,
        "regime": regime,
        "strikes": [
            {"strike": round(s.get("strike", 0) * factor, 2),
             "gex": s.get("net_gex", s.get("gex", 0))}
            for s in strikes[:20]
        ],
    }

    return levels


def push_to_render(payload):
    """Push GEX data to Render relay."""
    url = f"{RENDER_URL}/api/gex"
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"X-Api-Key": PUSH_KEY, "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            log.info(f"Pushed to Render: {resp.json()}")
        else:
            log.error(f"Render push failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        log.error(f"Render push error: {e}")


def main():
    if not FLASHALPHA_KEY:
        log.error("FLASHALPHA_API_KEY not set!")
        sys.exit(1)

    log.info("FlashAlpha fallback GEX fetch starting")
    expiry = get_next_expiry()
    log.info(f"Using expiry: {expiry}")

    es_levels = None
    nq_levels = None
    calls_used = 0

    # Try SPY → ES (with single expiry to stay on free tier)
    spy_data = fetch_gex("SPY", expiry=expiry)
    calls_used += 1
    if spy_data:
        es_levels = flashalpha_to_levels(spy_data, factor=10.0)
        if es_levels:
            log.info(f"ES: HVL={es_levels['hvl']}, regime={es_levels['regime']}")
    else:
        log.warning("SPY blocked — trying without expiry filter")
        # Try SPY without expiry (might hit tier restriction)
        spy_data = fetch_gex("SPY")
        calls_used += 1
        if spy_data:
            es_levels = flashalpha_to_levels(spy_data, factor=10.0)

    # Try QQQ → NQ
    if calls_used < 4:  # stay within daily limit
        qqq_data = fetch_gex("QQQ", expiry=expiry)
        calls_used += 1
        if qqq_data:
            nq_levels = flashalpha_to_levels(qqq_data, factor=40.0)
            if nq_levels:
                log.info(f"NQ: HVL={nq_levels['hvl']}, regime={nq_levels['regime']}")

    log.info(f"FlashAlpha calls used: {calls_used}")

    if es_levels or nq_levels:
        push_to_render({
            "es": es_levels,
            "nq": nq_levels,
            "source": "flashalpha_fallback",
        })
        log.info("Done")
    else:
        log.error("No data fetched — FlashAlpha free tier may not support SPY/QQQ")
        log.info("GEX data requires laptop + Moomoo OpenD for accurate levels")
        # Don't exit 1 — this is expected behavior on free tier
        # Push a "no data" marker so the chart shows stale status
        push_to_render({
            "es": None,
            "nq": None,
            "source": "flashalpha_unavailable",
        })


if __name__ == "__main__":
    main()
