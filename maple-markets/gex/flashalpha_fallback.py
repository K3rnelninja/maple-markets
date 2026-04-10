"""
gex/flashalpha_fallback.py — GitHub Actions fallback GEX fetcher
Uses FlashAlpha free API (5 req/day) to get SPX + QQQ GEX snapshots,
maps to ES/NQ, pushes to Render.

Run via GitHub Actions:
    python -m gex.flashalpha_fallback
"""

import os
import sys
import json
import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("gex.flashalpha")

FLASHALPHA_KEY = os.environ.get("FLASHALPHA_API_KEY", "")
RENDER_URL = os.environ.get("RENDER_URL", "https://maple-markets.onrender.com")
PUSH_KEY = os.environ.get("GEX_PUSH_KEY", "zeroprofit-default-key")
FLASHALPHA_BASE = "https://lab.flashalpha.com/v1"


def fetch_gex(symbol):
    """Fetch GEX from FlashAlpha API."""
    url = f"{FLASHALPHA_BASE}/exposure/gex/{symbol}"
    headers = {"X-Api-Key": FLASHALPHA_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            log.info(f"{symbol} GEX: flip={data.get('gamma_flip')}, "
                     f"regime={data.get('regime')}, net={data.get('net_gex')}")
            return data
        else:
            log.error(f"FlashAlpha {symbol} failed ({resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        log.error(f"FlashAlpha {symbol} error: {e}")
        return None


def fetch_exposure_levels(symbol):
    """Fetch key levels (call wall, put wall, gamma flip) from FlashAlpha."""
    url = f"{FLASHALPHA_BASE}/exposure/gex/{symbol}"
    headers = {"X-Api-Key": FLASHALPHA_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        else:
            log.error(f"FlashAlpha levels {symbol} failed: {resp.text}")
            return None
    except Exception as e:
        log.error(f"FlashAlpha levels {symbol} error: {e}")
        return None


def flashalpha_to_levels(data, is_spy=False):
    """Convert FlashAlpha response to our standard levels format."""
    if not data:
        return None

    strikes = data.get("strikes", [])

    # Find call walls (top positive GEX strikes)
    positive = [(s["strike"], s["gex"]) for s in strikes if s.get("gex", 0) > 0]
    positive.sort(key=lambda x: x[1], reverse=True)
    call_walls = [s[0] for s in positive[:3]]

    # Find put walls (top negative GEX strikes)
    negative = [(s["strike"], s["gex"]) for s in strikes if s.get("gex", 0) < 0]
    negative.sort(key=lambda x: x[1])
    put_walls = [s[0] for s in negative[:3]]

    levels = {
        "hvl": data.get("gamma_flip", 0),
        "call_walls": sorted(call_walls),
        "put_walls": sorted(put_walls),
        "max_pain": data.get("gamma_flip", 0),  # approximation
        "net_gex": data.get("net_gex", 0),
        "regime": data.get("regime", "unknown"),
        "strikes": strikes[:20],  # top strikes
    }

    return levels


def map_spx_to_es(levels):
    """SPX and ES trade at ~same price, minimal mapping needed."""
    # SPX ≈ ES (nearly 1:1)
    return levels


def map_qqq_to_nq(levels):
    """QQQ → NQ. Approximate: NQ ≈ QQQ × 40."""
    if not levels:
        return None
    factor = 40.0
    return {
        "hvl": round(levels["hvl"] * factor, 2),
        "call_walls": [round(w * factor, 2) for w in levels["call_walls"]],
        "put_walls": [round(w * factor, 2) for w in levels["put_walls"]],
        "max_pain": round(levels["max_pain"] * factor, 2),
        "net_gex": levels["net_gex"],
        "regime": levels["regime"],
        "strikes": [
            {"strike": round(s["strike"] * factor, 2), "gex": s.get("gex", 0)}
            for s in levels.get("strikes", [])
        ],
    }


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

    # Fetch SPX GEX → ES levels (1 API call)
    spx_data = fetch_gex("SPX")
    es_levels = None
    if spx_data:
        raw_levels = flashalpha_to_levels(spx_data)
        es_levels = map_spx_to_es(raw_levels)
        if es_levels:
            log.info(f"ES: HVL={es_levels['hvl']}, regime={es_levels['regime']}")

    # Fetch QQQ GEX → NQ levels (1 API call)
    qqq_data = fetch_gex("QQQ")
    nq_levels = None
    if qqq_data:
        raw_levels = flashalpha_to_levels(qqq_data)
        nq_levels = map_qqq_to_nq(raw_levels)
        if nq_levels:
            log.info(f"NQ: HVL={nq_levels['hvl']}, regime={nq_levels['regime']}")

    # Push to Render (uses 2 of 5 daily FlashAlpha calls)
    if es_levels or nq_levels:
        push_to_render({
            "es": es_levels,
            "nq": nq_levels,
            "source": "flashalpha_delayed",
        })
        log.info("Done — 2 FlashAlpha calls used, 3 remaining today")
    else:
        log.error("No data fetched from FlashAlpha")
        sys.exit(1)


if __name__ == "__main__":
    main()
