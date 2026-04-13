"""
gex/moomoo_relay.py — Laptop-side GEX engine
Connects to Moomoo OpenD for OPTIONS chains (real-time, free).
Uses Yahoo Finance for SPOT prices (free from laptop, not cloud).
Computes GEX, maps to ES/NQ, pushes to Render.

Run on your laptop:
    python -m gex.moomoo_relay

Requires:
    pip install moomoo-api requests numpy scipy yfinance
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


def get_spot_price(ticker):
    """
    Get spot price using Yahoo Finance (free from laptop).
    Falls back to a simple requests-based approach if yfinance isn't installed.
    """
    # Method 1: yfinance
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        data = t.fast_info
        price = data.get("lastPrice", None) or data.get("last_price", None)
        if price and price > 0:
            log.info(f"{ticker} spot (yfinance): {price}")
            return float(price)
    except ImportError:
        pass
    except Exception as e:
        log.warning(f"yfinance failed for {ticker}: {e}")

    # Method 2: Direct Yahoo Finance JSON endpoint
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            log.info(f"{ticker} spot (yahoo): {price}")
            return float(price)
    except Exception as e:
        log.warning(f"Yahoo Finance failed for {ticker}: {e}")

    # Method 3: Try Moomoo (may fail without Nasdaq Basic)
    try:
        from moomoo import OpenQuoteContext
        quote_ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
        ret, data = quote_ctx.get_market_snapshot([f"US.{ticker}"])
        quote_ctx.close()
        if ret == 0 and len(data) > 0:
            price = float(data["last_price"].iloc[0])
            if price > 0:
                log.info(f"{ticker} spot (moomoo): {price}")
                return price
    except Exception as e:
        log.warning(f"Moomoo spot failed for {ticker}: {e}")

    log.error(f"Could not get spot price for {ticker}")
    return None


def fetch_options_chain(ticker="SPY"):
    """
    Fetch options chain from Moomoo OpenD.
    Returns list of dicts: [{strike, expiry_days, iv, oi, type}, ...]
    """
    try:
        from moomoo import OpenQuoteContext, OptionCondType
    except ImportError:
        log.error("moomoo-api not installed. Run: pip install moomoo-api")
        return None

    quote_ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)

    try:
        # Get spot price separately (doesn't need Nasdaq Basic)
        spot = get_spot_price(ticker)
        if not spot:
            log.error(f"Cannot get spot price for {ticker}")
            return None

        # Get option expiry dates
        ret, data = quote_ctx.get_option_expiration_date(f"US.{ticker}")
        if ret != 0:
            log.error(f"Failed to get expiry dates for {ticker}: {data}")
            return None

        # Take first 4 expiries (covers weekly + monthly)
        expiries = data["strike_time"].tolist()[:4]
        log.info(f"{ticker} expiries: {expiries}")

        chain = []
        today = datetime.now()

        for expiry_str in expiries:
            ret, data = quote_ctx.get_option_chain(
                f"US.{ticker}",
                start=expiry_str,
                end=expiry_str,
                option_cond_type=OptionCondType.WITHIN,
            )
            if ret != 0:
                log.warning(f"Failed chain for {expiry_str}: {data}")
                continue

            try:
                expiry_dt = datetime.strptime(expiry_str[:10], "%Y-%m-%d")
                dte = max((expiry_dt - today).days, 1)
            except Exception:
                dte = 7

            for _, row in data.iterrows():
                strike = float(row.get("strike_price", 0))
                oi = int(row.get("open_interest", 0))
                iv = float(row.get("implied_volatility", 0))
                opt_type_val = row.get("option_type", "")

                if "CALL" in str(opt_type_val).upper() or "C" == str(opt_type_val).upper():
                    opt_type = "call"
                elif "PUT" in str(opt_type_val).upper() or "P" == str(opt_type_val).upper():
                    opt_type = "put"
                else:
                    continue

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

        log.info(f"Fetched {len(chain)} contracts for {ticker} (spot: {spot})")
        return chain

    except Exception as e:
        log.error(f"Error fetching {ticker} chain: {e}")
        return None
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
    spy_spot = get_spot_price("SPY")
    spy_chain = fetch_options_chain("SPY")
    es_levels = None
    if spy_chain and spy_spot:
        spy_gex = compute_gex_profile(spy_chain, spy_spot)
        if spy_gex:
            es_levels = map_spy_to_es(spy_gex)
            log.info(f"ES levels: HVL={es_levels['hvl']}, "
                     f"Calls={es_levels['call_walls']}, "
                     f"Puts={es_levels['put_walls']}, "
                     f"Regime={es_levels['regime']}")

    # ── QQQ → NQ ──
    qqq_spot = get_spot_price("QQQ")
    qqq_chain = fetch_options_chain("QQQ")
    nq_levels = None
    if qqq_chain and qqq_spot:
        qqq_gex = compute_gex_profile(qqq_chain, qqq_spot)
        if qqq_gex:
            nq_price = get_spot_price("NQ=F")  # NQ futures from Yahoo
            if not nq_price:
                nq_price = qqq_spot * 40  # fallback ratio
            nq_levels = map_qqq_to_nq(qqq_gex, qqq_spot, nq_price)
            log.info(f"NQ levels: HVL={nq_levels['hvl']}, "
                     f"Calls={nq_levels['call_walls']}, "
                     f"Puts={nq_levels['put_walls']}, "
                     f"Regime={nq_levels['regime']}")

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
    log.info("=" * 50)
    log.info("ZeroProfit GEX Engine v1.0")
    log.info("=" * 50)
    log.info(f"Render: {RENDER_URL}")
    log.info(f"OpenD: {OPEND_HOST}:{OPEND_PORT}")
    log.info(f"Interval: {INTERVAL_SECONDS}s")
    log.info(f"Spot prices: Yahoo Finance (free from laptop)")
    log.info(f"Options chains: Moomoo OpenD (real-time)")
    log.info("")

    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error(f"Cycle error: {e}", exc_info=True)

        log.info(f"Sleeping {INTERVAL_SECONDS}s...")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
