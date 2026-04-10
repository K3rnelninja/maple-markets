"""
gex/moomoo_relay.py — Laptop-side GEX engine
Connects to Moomoo OpenD, pulls SPY + QQQ options chains,
computes GEX, maps to ES/NQ, pushes to Render.

Run on your laptop:
    python -m gex.moomoo_relay

Requires:
    pip install moomoo-api requests
    Moomoo OpenD running on localhost:11111
"""

import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("gex.moomoo_relay")

# ── Config ──────────────────────────────────────────────────────────────
RENDER_URL = os.environ.get("RENDER_URL", "https://maple-markets.onrender.com")
PUSH_KEY = os.environ.get("GEX_PUSH_KEY", "zeroprofit-default-key")
OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))
INTERVAL_SECONDS = int(os.environ.get("GEX_INTERVAL", "600"))  # 10 min default


def check_opend():
    """Verify OpenD is reachable."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((OPEND_HOST, OPEND_PORT))
        s.close()
        return True
    except Exception as e:
        log.error(f"OpenD not reachable at {OPEND_HOST}:{OPEND_PORT}: {e}")
        return False


def fetch_options_chain(ticker="SPY"):
    """
    Fetch options chain from Moomoo OpenD.
    Returns list of dicts: [{strike, expiry_days, iv, oi, type}, ...]
    """
    try:
        from moomoo import OpenQuoteContext, SubType, OptionType, OptionCondType
    except ImportError:
        log.error("moomoo-api not installed. Run: pip install moomoo-api")
        return None, None

    quote_ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)

    try:
        # Get current price
        ret, data = quote_ctx.get_market_snapshot([f"US.{ticker}"])
        if ret != 0:
            log.error(f"Failed to get snapshot for {ticker}: {data}")
            return None, None
        spot = float(data["last_price"].iloc[0])
        log.info(f"{ticker} spot: {spot}")

        # Get option expiry dates
        ret, data = quote_ctx.get_option_expiration_date(f"US.{ticker}")
        if ret != 0:
            log.error(f"Failed to get expiry dates: {data}")
            return None, spot

        # Take first 4 expiries (covers weekly + monthly)
        expiries = data["strike_time"].tolist()[:4]
        log.info(f"Expiries: {expiries}")

        chain = []
        today = datetime.now()

        for expiry_str in expiries:
            # Get option chain for this expiry
            ret, data = quote_ctx.get_option_chain(
                f"US.{ticker}",
                start=expiry_str,
                end=expiry_str,
                option_cond_type=OptionCondType.WITHIN,
            )
            if ret != 0:
                log.warning(f"Failed chain for {expiry_str}: {data}")
                continue

            # Parse expiry to DTE
            try:
                expiry_dt = datetime.strptime(expiry_str[:10], "%Y-%m-%d")
                dte = max((expiry_dt - today).days, 1)
            except Exception:
                dte = 7

            for _, row in data.iterrows():
                code = row.get("code", "")
                strike = float(row.get("strike_price", 0))
                oi = int(row.get("open_interest", 0))
                iv = float(row.get("implied_volatility", 0))
                opt_type_val = row.get("option_type", "")

                # Determine call/put
                if "CALL" in str(opt_type_val).upper() or "C" == str(opt_type_val).upper():
                    opt_type = "call"
                elif "PUT" in str(opt_type_val).upper() or "P" == str(opt_type_val).upper():
                    opt_type = "put"
                else:
                    continue

                # Filter: within 10% of spot, OI > 0
                if oi <= 0 or strike <= 0:
                    continue
                if abs(strike - spot) / spot > 0.10:
                    continue

                chain.append({
                    "strike": strike,
                    "expiry_days": dte,
                    "iv": iv if iv > 0 else 0.20,
                    "oi": oi,
                    "type": opt_type,
                })

        log.info(f"Fetched {len(chain)} option contracts for {ticker}")
        return chain, spot

    except Exception as e:
        log.error(f"Error fetching {ticker} chain: {e}")
        return None, None
    finally:
        quote_ctx.close()


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


def run_once():
    """Single GEX computation cycle."""
    from gex.compute import compute_gex_profile, map_spy_to_es, map_qqq_to_nq

    if not check_opend():
        log.error("OpenD not available, skipping cycle")
        return False

    # ── SPY → ES ──
    spy_chain, spy_spot = fetch_options_chain("SPY")
    es_levels = None
    if spy_chain and spy_spot:
        spy_gex = compute_gex_profile(spy_chain, spy_spot)
        if spy_gex:
            es_levels = map_spy_to_es(spy_gex)
            log.info(f"ES levels: HVL={es_levels['hvl']}, "
                     f"Call Wall={es_levels['call_walls']}, "
                     f"Put Wall={es_levels['put_walls']}")

    # ── QQQ → NQ ──
    qqq_chain, qqq_spot = fetch_options_chain("QQQ")
    nq_levels = None
    if qqq_chain and qqq_spot:
        qqq_gex = compute_gex_profile(qqq_chain, qqq_spot)
        if qqq_gex:
            # Approximate NQ price from QQQ (NQ ≈ QQQ × 40)
            nq_approx = qqq_spot * 40
            nq_levels = map_qqq_to_nq(qqq_gex, qqq_spot, nq_approx)
            log.info(f"NQ levels: HVL={nq_levels['hvl']}, "
                     f"Call Wall={nq_levels['call_walls']}, "
                     f"Put Wall={nq_levels['put_walls']}")

    if es_levels or nq_levels:
        push_to_render({
            "es": es_levels,
            "nq": nq_levels,
            "source": "moomoo_realtime",
        })
        return True
    else:
        log.warning("No GEX data computed this cycle")
        return False


def main():
    """Main loop — runs GEX computation every INTERVAL_SECONDS."""
    log.info(f"ZeroProfit GEX Engine starting")
    log.info(f"Render: {RENDER_URL}")
    log.info(f"OpenD: {OPEND_HOST}:{OPEND_PORT}")
    log.info(f"Interval: {INTERVAL_SECONDS}s")

    while True:
        try:
            run_once()
        except Exception as e:
            log.error(f"Cycle error: {e}", exc_info=True)

        log.info(f"Sleeping {INTERVAL_SECONDS}s...")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
