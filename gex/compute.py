"""
gex/compute.py — GEX computation engine
Takes an options chain (list of dicts) and computes:
  - NETGEX per strike
  - HVL (gamma flip / zero gamma)
  - Call walls (top 3 positive GEX strikes)
  - Put walls (top 3 negative GEX strikes)
  - Max pain
  - IV rank (requires historical IV data, approximated here)
  - Gamma regime (positive / negative)
"""

import numpy as np
from scipy.stats import norm


def black_scholes_gamma(S, K, T, r, sigma, q=0.0):
    """Compute BS gamma for a single option."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return np.exp(-q * T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))


def compute_gex_strike(S, K, T, r, sigma, oi, opt_type, q=0.0):
    """
    Compute dollar-gamma exposure for one strike.
    Convention: dealers are short calls, long puts (retail buys from dealers).
      Call GEX = +gamma * OI * 100 * S^2 * 0.01
      Put  GEX = -gamma * OI * 100 * S^2 * 0.01
    """
    gamma = black_scholes_gamma(S, K, T, r, sigma, q)
    gex = gamma * oi * 100 * S * S * 0.01
    if opt_type.lower() in ("put", "p"):
        gex = -gex
    return gex


def compute_gex_profile(chain, spot, risk_free_rate=0.05, dividend_yield=0.015):
    """
    Compute full GEX profile from an options chain.

    Args:
        chain: list of dicts, each with keys:
            strike, expiry_days (DTE), iv, oi, type ('call'/'put')
        spot: current underlying price
        risk_free_rate: annual risk-free rate (default 5%)
        dividend_yield: annual dividend yield (default 1.5% for SPX)

    Returns:
        dict with HVL, call_walls, put_walls, max_pain, net_gex, regime, strikes
    """
    if not chain or spot <= 0:
        return None

    # Aggregate GEX by strike
    strike_gex = {}
    strike_call_oi = {}
    strike_put_oi = {}

    for opt in chain:
        K = opt["strike"]
        T = max(opt["expiry_days"] / 365.0, 1 / 365.0)  # min 1 day
        iv = opt.get("iv", 0.20)
        oi = opt.get("oi", 0)
        opt_type = opt.get("type", "call")

        if oi <= 0 or iv <= 0:
            continue

        gex = compute_gex_strike(spot, K, T, risk_free_rate, iv, oi, opt_type, dividend_yield)

        strike_gex[K] = strike_gex.get(K, 0) + gex

        if opt_type.lower() in ("call", "c"):
            strike_call_oi[K] = strike_call_oi.get(K, 0) + oi
        else:
            strike_put_oi[K] = strike_put_oi.get(K, 0) + oi

    if not strike_gex:
        return None

    # Sort strikes
    sorted_strikes = sorted(strike_gex.keys())

    # ── NETGEX ──
    net_gex = sum(strike_gex.values())
    regime = "positive" if net_gex >= 0 else "negative"

    # ── HVL (gamma flip) — where cumulative GEX crosses zero ──
    hvl = spot  # default
    cumulative = 0
    for K in sorted_strikes:
        prev_cum = cumulative
        cumulative += strike_gex[K]
        if prev_cum < 0 and cumulative >= 0:
            # Linear interpolation
            if cumulative != prev_cum:
                frac = -prev_cum / (cumulative - prev_cum)
                prev_K = sorted_strikes[max(0, sorted_strikes.index(K) - 1)]
                hvl = prev_K + frac * (K - prev_K)
            else:
                hvl = K
            break
        elif prev_cum >= 0 and cumulative < 0:
            hvl = K
            break

    # If no crossing found, use strike with smallest absolute cumulative
    if hvl == spot:
        cum = 0
        best_k, best_abs = sorted_strikes[0], abs(sum(strike_gex.values()))
        for K in sorted_strikes:
            cum += strike_gex[K]
            if abs(cum) < best_abs:
                best_abs = abs(cum)
                best_k = K
        hvl = best_k

    # ── Call walls (top 3 positive GEX strikes) ──
    positive = [(K, g) for K, g in strike_gex.items() if g > 0]
    positive.sort(key=lambda x: x[1], reverse=True)
    call_walls = [K for K, _ in positive[:3]]

    # ── Put walls (top 3 negative GEX strikes) ──
    negative = [(K, g) for K, g in strike_gex.items() if g < 0]
    negative.sort(key=lambda x: x[1])  # most negative first
    put_walls = [K for K, _ in negative[:3]]

    # ── Max pain (strike where total OI dollar value is minimized) ──
    all_strikes = sorted(set(list(strike_call_oi.keys()) + list(strike_put_oi.keys())))
    if all_strikes:
        min_pain = float("inf")
        max_pain_strike = spot
        for test_price in all_strikes:
            total_pain = 0
            for K, oi in strike_call_oi.items():
                total_pain += max(0, test_price - K) * oi * 100
            for K, oi in strike_put_oi.items():
                total_pain += max(0, K - test_price) * oi * 100
            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = test_price
    else:
        max_pain_strike = spot

    # ── Top strikes for chart profile ──
    top_strikes = []
    for K in sorted_strikes:
        if abs(K - spot) / spot < 0.10:  # within 10% of spot
            top_strikes.append({"strike": K, "gex": round(strike_gex[K], 2)})

    return {
        "hvl": round(hvl, 2),
        "call_walls": sorted(call_walls),
        "put_walls": sorted(put_walls),
        "max_pain": max_pain_strike,
        "net_gex": round(net_gex, 2),
        "regime": regime,
        "strikes": top_strikes,
    }


def map_spy_to_es(levels):
    """SPY levels → ES levels. SPY ≈ SPX/10, ES ≈ SPX."""
    if not levels:
        return None
    factor = 10.0  # SPY × 10 ≈ ES
    return {
        "hvl": round(levels["hvl"] * factor, 2),
        "call_walls": [round(w * factor, 2) for w in levels["call_walls"]],
        "put_walls": [round(w * factor, 2) for w in levels["put_walls"]],
        "max_pain": round(levels["max_pain"] * factor, 2),
        "net_gex": levels["net_gex"],
        "regime": levels["regime"],
        "strikes": [
            {"strike": round(s["strike"] * factor, 2), "gex": s["gex"]}
            for s in levels.get("strikes", [])
        ],
    }


def map_qqq_to_nq(levels, qqq_price, nq_price):
    """QQQ levels → NQ levels using live ratio."""
    if not levels or not qqq_price or not nq_price:
        return None
    factor = nq_price / qqq_price
    return {
        "hvl": round(levels["hvl"] * factor, 2),
        "call_walls": [round(w * factor, 2) for w in levels["call_walls"]],
        "put_walls": [round(w * factor, 2) for w in levels["put_walls"]],
        "max_pain": round(levels["max_pain"] * factor, 2),
        "net_gex": levels["net_gex"],
        "regime": levels["regime"],
        "strikes": [
            {"strike": round(s["strike"] * factor, 2), "gex": s["gex"]}
            for s in levels.get("strikes", [])
        ],
    }
