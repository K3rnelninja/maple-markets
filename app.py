"""
maple-markets v3.0 — 5-Tab Trading Dashboard
Day Trade / Swing / RRSP / Trades / Stats
Render: maple-markets.onrender.com
GitHub: K3rnelninja/maple-markets
"""
import os
import json
import time
import requests as req_lib
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template, send_from_directory

app = Flask(__name__, static_folder='static', template_folder='templates')

# ── Persistent store (survives restarts via file) ──────────────────
STORE_FILE = os.environ.get("STORE_FILE", "/tmp/maple_store.json")

def load_store():
    try:
        with open(STORE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None

def save_store(data):
    try:
        with open(STORE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"save_store error: {e}")

# ── In-memory stores ────────────────────────────────────────────────
_gex_store = {"es": None, "nq": None, "updated_at": None, "source": None}

_trades_store = [
    {"id":1,"date":"03/25","dir":"SHORT","entry":6643,"exit":6634,"pnl":449},
    {"id":2,"date":"03/25","dir":"SHORT","entry":6645.25,"exit":6636.25,"pnl":449},
    {"id":3,"date":"03/26","dir":"SHORT","entry":6553.75,"exit":6544.75,"pnl":449},
    {"id":4,"date":"03/26","dir":"SHORT","entry":6547.25,"exit":6538.5,"pnl":449},
    {"id":5,"date":"03/26","dir":"SHORT","entry":6554,"exit":6557,"pnl":-163.5},
    {"id":6,"date":"03/26","dir":"SHORT","entry":6589.5,"exit":6591.5,"pnl":-101},
    {"id":7,"date":"03/29","dir":"SHORT","entry":6380.75,"exit":6384,"pnl":-163.5},
    {"id":8,"date":"03/30","dir":"SHORT","entry":6414,"exit":6417.75,"pnl":-188.5},
    {"id":9,"date":"03/31","dir":"LONG","entry":6428.75,"exit":6437.75,"pnl":449},
    {"id":10,"date":"03/31","dir":"LONG","entry":6465.75,"exit":6466.75,"pnl":49},
    {"id":11,"date":"03/31","dir":"LONG","entry":6582,"exit":6578.25,"pnl":-188.5},
    {"id":12,"date":"04/01","dir":"LONG","entry":6604.75,"exit":6600.75,"pnl":-201},
    {"id":13,"date":"04/02","dir":"SHORT","entry":6528.25,"exit":6531.75,"pnl":-176},
    {"id":14,"date":"04/03","dir":"LONG","entry":6611,"exit":6611.25,"pnl":11.5},
    {"id":15,"date":"04/03","dir":"SHORT","entry":6607.5,"exit":6611.25,"pnl":-188.5},
    {"id":16,"date":"04/06","dir":"LONG","entry":6616.5,"exit":6625.5,"pnl":449},
    {"id":17,"date":"04/06","dir":"LONG","entry":6638.5,"exit":6635.25,"pnl":-163.5},
    {"id":18,"date":"04/06","dir":"LONG","entry":6636.5,"exit":6633,"pnl":-176},
    {"id":19,"date":"04/06","dir":"SHORT","entry":6647.75,"exit":6651.25,"pnl":-176},
    {"id":20,"date":"04/07","dir":"LONG","entry":6634.25,"exit":6629.25,"pnl":-251},
    {"id":21,"date":"04/07","dir":"SHORT","entry":6609.75,"exit":6613.75,"pnl":-201},
    {"id":22,"date":"04/10","dir":"SHORT","entry":6810.5,"exit":6813.75,"pnl":-163.5},
    {"id":23,"date":"04/13","dir":"SHORT","entry":6801.75,"exit":6808,"pnl":-313.5},
    {"id":24,"date":"04/13","dir":"SHORT","entry":6806,"exit":6809.75,"pnl":-188.5},
    {"id":25,"date":"04/14","dir":"LONG","entry":6936,"exit":6932.75,"pnl":-163.5},
]

# ── RRSP Portfolio — Canadian + US Dividend Stocks ──────────────────
# US stocks in RRSP avoid 15% withholding tax (IRS recognizes RRSP)
_rrsp_default = [
    # Canadian Holdings
    {"id":1,"ticker":"ENB.TO","name":"Enbridge","country":"CA","sector":"Pipeline","yield":6.1,"growth":3,"shares":2,"avgCost":54.20,"price":58.75,"divPerShare":3.35,"rating":"HOLD","note":"51yr dividend streak, 6%+ yield, energy infrastructure backbone"},
    {"id":2,"ticker":"BNS.TO","name":"Scotiabank","country":"CA","sector":"Bank","yield":5.8,"growth":5,"shares":1,"avgCost":68.50,"price":72.30,"divPerShare":4.24,"rating":"BUY","note":"Big 5 bank, international growth via LatAm, 5.8% yield"},
    {"id":3,"ticker":"FTS.TO","name":"Fortis","country":"CA","sector":"Utility","yield":3.3,"growth":5,"shares":2,"avgCost":56.80,"price":61.20,"divPerShare":2.39,"rating":"BUY","note":"52yr consecutive dividend raises, 4-6% annual growth through 2030"},
    {"id":4,"ticker":"BAM.TO","name":"Brookfield AM","country":"CA","sector":"Alt Assets","yield":3.2,"growth":15,"shares":1,"avgCost":65.00,"price":71.80,"divPerShare":1.72,"rating":"BUY","note":"AI infrastructure + renewables, plans to double in 5yrs"},
    # US Holdings (in RRSP — no 15% withholding)
    {"id":5,"ticker":"JNJ","name":"Johnson & Johnson","country":"US","sector":"Healthcare","yield":3.1,"growth":6,"shares":1,"avgCost":152.00,"price":158.40,"divPerShare":4.96,"rating":"BUY","note":"Dividend King, 60+yr streak, defensive healthcare"},
    {"id":6,"ticker":"PG","name":"Procter & Gamble","country":"US","sector":"Consumer Staples","yield":2.4,"growth":6,"shares":1,"avgCost":158.00,"price":168.20,"divPerShare":4.03,"rating":"HOLD","note":"Dividend King 68yrs, household brands, recession-proof"},
    {"id":7,"ticker":"KO","name":"Coca-Cola","country":"US","sector":"Consumer Staples","yield":2.9,"growth":5,"shares":2,"avgCost":68.00,"price":72.15,"divPerShare":2.08,"rating":"BUY","note":"Dividend King 62yrs, global brand moat, stable cash flows"},
    {"id":8,"ticker":"MSFT","name":"Microsoft","country":"US","sector":"Technology","yield":0.7,"growth":10,"shares":1,"avgCost":395.00,"price":432.50,"divPerShare":3.00,"rating":"BUY","note":"AI leader, cloud growth, 20yr div growth, 10% raises"},
]

_rrsp_meta_default = {
    "monthlyContribution": 50,
    "currency": "CAD",
    "targetAge": 65,
    "yearsToTarget": 25,
    "lastContribution": "2026-04-01"
}

# ── Swing Watchlist ─────────────────────────────────────────────────
_swing_default = [
    {"ticker":"SPY","name":"S&P 500 ETF","price":697.42,"signal":"LONG","score":72,"trend":"BULL","tp":710,"sl":688,"rr":"2.1:1","note":"Above 21/50 EMA, ORB breakout confirmed"},
    {"ticker":"QQQ","name":"Nasdaq 100 ETF","price":596.80,"signal":"LONG","score":68,"trend":"BULL","tp":615,"sl":585,"rr":"1.6:1","note":"Tech leading, above VWAP, positive momentum"},
    {"ticker":"AAPL","name":"Apple","price":212.50,"signal":"HOLD","score":55,"trend":"MIXED","tp":220,"sl":205,"rr":"1.0:1","note":"Consolidating at resistance, wait for breakout"},
    {"ticker":"NVDA","name":"Nvidia","price":118.30,"signal":"LONG","score":78,"trend":"BULL","tp":130,"sl":112,"rr":"1.9:1","note":"AI capex cycle, strong momentum, above all MAs"},
    {"ticker":"TSLA","name":"Tesla","price":285.60,"signal":"SHORT","score":62,"trend":"BEAR","tp":260,"sl":298,"rr":"2.1:1","note":"Below 50 EMA, tariff headwinds, fading momentum"},
    {"ticker":"AMD","name":"AMD","price":108.40,"signal":"LONG","score":70,"trend":"BULL","tp":118,"sl":102,"rr":"1.5:1","note":"MI400 catalyst, data center growth, above 21 EMA"},
    {"ticker":"AMZN","name":"Amazon","price":198.20,"signal":"HOLD","score":52,"trend":"MIXED","tp":210,"sl":190,"rr":"1.5:1","note":"Cloud strong, retail mixed, at 200 EMA support"},
    {"ticker":"META","name":"Meta","price":582.10,"signal":"LONG","score":74,"trend":"BULL","tp":610,"sl":565,"rr":"1.6:1","note":"AI monetization, strong engagement, above BGL"},
]

# Load persisted state if it exists
_saved = load_store()
if _saved:
    _rrsp_store = _saved.get("rrsp", _rrsp_default)
    _rrsp_meta = _saved.get("rrsp_meta", _rrsp_meta_default)
    _swing_store = _saved.get("swing", _swing_default)
else:
    _rrsp_store = _rrsp_default
    _rrsp_meta = _rrsp_meta_default
    _swing_store = _swing_default

def persist():
    save_store({"rrsp": _rrsp_store, "rrsp_meta": _rrsp_meta, "swing": _swing_store})

PUSH_KEY = os.environ.get("GEX_PUSH_KEY", "dev-key")

# ── PWA Routes ──────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("app.html")

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Maple Markets",
        "short_name": "Maple",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0f",
        "theme_color": "#e63946",
        "orientation": "portrait",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    })

@app.route("/sw.js")
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "2.1.0", "updated_at": _gex_store["updated_at"]})

# ── Market Data Proxy (Yahoo Finance) ───────────────────────────────
# Cached to avoid hammering Yahoo — refreshes every 60s
_market_cache = {"data": None, "fetched_at": 0}
CACHE_TTL = 60  # seconds

@app.route("/api/market")
def get_market():
    now = time.time()
    if _market_cache["data"] and (now - _market_cache["fetched_at"]) < CACHE_TTL:
        return jsonify(_market_cache["data"])
    
    result = {"es": {}, "vix": {}, "live": False, "fetched_at": None, "error": None}
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    
    try:
        # ES Futures
        es_url = "https://query1.finance.yahoo.com/v8/finance/chart/ES=F?interval=5m&range=1d"
        es_resp = req_lib.get(es_url, headers=headers, timeout=8)
        es_json = es_resp.json()
        if es_json.get("chart", {}).get("result"):
            r = es_json["chart"]["result"][0]
            meta = r.get("meta", {})
            price = meta.get("regularMarketPrice", 0)
            prev = meta.get("chartPreviousClose", meta.get("previousClose", price))
            
            candles = []
            if r.get("timestamp") and r.get("indicators", {}).get("quote"):
                q = r["indicators"]["quote"][0]
                ts = r["timestamp"]
                for i in range(len(ts)):
                    if q["open"][i] is not None and q["close"][i] is not None:
                        candles.append({
                            "o": round(q["open"][i], 2),
                            "h": round(q["high"][i], 2),
                            "l": round(q["low"][i], 2),
                            "c": round(q["close"][i], 2),
                            "t": ts[i]
                        })
            
            result["es"] = {
                "price": price,
                "change": round(price - prev, 2),
                "changePct": round((price - prev) / prev * 100, 2) if prev else 0,
                "candles": candles
            }
            result["live"] = True
    except Exception as e:
        result["error"] = f"ES: {str(e)}"
    
    try:
        # VIX
        vix_url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=2d"
        vix_resp = req_lib.get(vix_url, headers=headers, timeout=8)
        vix_json = vix_resp.json()
        if vix_json.get("chart", {}).get("result"):
            vix_val = vix_json["chart"]["result"][0]["meta"].get("regularMarketPrice", 0)
            regime = "LOW VOL" if vix_val < 15 else ("HIGH VOL" if vix_val > 25 else "MODERATE")
            result["vix"] = {"value": round(vix_val, 2), "regime": regime}
    except Exception as e:
        if result["error"]:
            result["error"] += f" | VIX: {str(e)}"
        else:
            result["error"] = f"VIX: {str(e)}"
    
    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    _market_cache["data"] = result
    _market_cache["fetched_at"] = now
    return jsonify(result)

# ── Trade API ───────────────────────────────────────────────────────
@app.route("/api/trades")
def get_trades():
    return jsonify({"trades": _trades_store, "count": len(_trades_store)})

@app.route("/api/trades", methods=["POST"])
def add_trade():
    key = request.headers.get("X-Api-Key", "")
    if key != PUSH_KEY:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json()
    if data:
        data["id"] = len(_trades_store) + 1
        _trades_store.append(data)
        return jsonify({"ok": True, "trade": data})
    return jsonify({"error": "no data"}), 400

@app.route("/api/stats")
def get_stats():
    trades = _trades_store
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate = (len(wins) / len(trades) * 100) if trades else 0
    avg_win = (sum(t["pnl"] for t in wins) / len(wins)) if wins else 0
    avg_loss = (sum(t["pnl"] for t in losses) / len(losses)) if losses else 0
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 0
    
    longs = [t for t in trades if t["dir"] == "LONG"]
    shorts = [t for t in trades if t["dir"] == "SHORT"]
    long_wr = (len([t for t in longs if t["pnl"] > 0]) / len(longs) * 100) if longs else 0
    short_wr = (len([t for t in shorts if t["pnl"] > 0]) / len(shorts) * 100) if shorts else 0
    
    return jsonify({
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "total_pnl": total_pnl,
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 1),
        "avg_loss": round(avg_loss, 1),
        "profit_factor": round(pf, 2),
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "long_win_rate": round(long_wr, 1),
        "short_win_rate": round(short_wr, 1),
        "long_pnl": sum(t["pnl"] for t in longs),
        "short_pnl": sum(t["pnl"] for t in shorts),
        "weekly": [
            {"week": "W12 (Mar 25-26)", "trades": 6, "wins": 4, "pnl": 1531.5},
            {"week": "W13 (Mar 29-Apr 1)", "trades": 9, "wins": 3, "pnl": -596.5},
            {"week": "W14 (Apr 2-6)", "trades": 7, "wins": 1, "pnl": -682},
            {"week": "W15 (Apr 7-14)", "trades": 3, "wins": 0, "pnl": -665.5},
        ],
        "equity_curve": list(accumulate_pnl(trades)),
    })

def accumulate_pnl(trades):
    eq = 0
    for t in trades:
        eq += t["pnl"]
        yield round(eq, 2)

# ── GEX API (existing) ─────────────────────────────────────────────
@app.route("/api/gex")
def get_gex():
    if _gex_store["es"] is None:
        return jsonify({"error": "no data yet", "stale": True}), 200
    now = datetime.now(timezone.utc)
    updated = _gex_store.get("updated_at")
    stale = True
    if updated:
        try:
            dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            stale = (now - dt).total_seconds() > 1800
        except:
            stale = True
    return jsonify({**_gex_store, "stale": stale})

@app.route("/api/gex", methods=["POST"])
def push_gex():
    key = request.headers.get("X-Api-Key", "")
    if key != PUSH_KEY:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400
    _gex_store["es"] = data.get("es")
    _gex_store["nq"] = data.get("nq")
    _gex_store["updated_at"] = data.get("updated_at", datetime.now(timezone.utc).isoformat())
    _gex_store["source"] = data.get("source", "unknown")
    return jsonify({"ok": True})

# ── RRSP API ────────────────────────────────────────────────────────
@app.route("/api/rrsp")
def get_rrsp():
    total_value = sum(h["price"] * h["shares"] for h in _rrsp_store)
    total_cost = sum(h["avgCost"] * h["shares"] for h in _rrsp_store)
    total_gain = total_value - total_cost
    annual_div = sum(h["divPerShare"] * h["shares"] for h in _rrsp_store)
    avg_yield = (annual_div / total_value * 100) if total_value > 0 else 0
    
    # 25-year projection: monthly contribution + 8% growth + DRIP
    monthly = _rrsp_meta.get("monthlyContribution", 50)
    years = _rrsp_meta.get("yearsToTarget", 25)
    monthly_return = 0.08 / 12
    projected = total_value
    for _ in range(years * 12):
        projected = (projected + monthly) * (1 + monthly_return)
    
    # Split by country
    ca_holdings = [h for h in _rrsp_store if h.get("country") == "CA"]
    us_holdings = [h for h in _rrsp_store if h.get("country") == "US"]
    ca_value = sum(h["price"] * h["shares"] for h in ca_holdings)
    us_value = sum(h["price"] * h["shares"] for h in us_holdings)
    
    return jsonify({
        "holdings": _rrsp_store,
        "meta": _rrsp_meta,
        "summary": {
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_gain": round(total_gain, 2),
            "total_gain_pct": round((total_gain / total_cost * 100) if total_cost > 0 else 0, 2),
            "annual_dividend": round(annual_div, 2),
            "avg_yield": round(avg_yield, 2),
            "projected_25yr": round(projected, 0),
            "ca_value": round(ca_value, 2),
            "us_value": round(us_value, 2),
            "ca_pct": round((ca_value / total_value * 100) if total_value > 0 else 0, 1),
            "us_pct": round((us_value / total_value * 100) if total_value > 0 else 0, 1),
        }
    })

@app.route("/api/rrsp/holding", methods=["POST"])
def add_or_update_holding():
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400
    
    hid = data.get("id")
    if hid:
        # Update existing
        for i, h in enumerate(_rrsp_store):
            if h["id"] == hid:
                _rrsp_store[i] = {**h, **data}
                persist()
                return jsonify({"ok": True, "holding": _rrsp_store[i]})
        return jsonify({"error": "not found"}), 404
    else:
        # Add new
        new_id = max([h["id"] for h in _rrsp_store], default=0) + 1
        new_holding = {
            "id": new_id,
            "ticker": data.get("ticker", ""),
            "name": data.get("name", ""),
            "country": data.get("country", "CA"),
            "sector": data.get("sector", ""),
            "yield": float(data.get("yield", 0)),
            "growth": float(data.get("growth", 0)),
            "shares": float(data.get("shares", 0)),
            "avgCost": float(data.get("avgCost", 0)),
            "price": float(data.get("price", 0)),
            "divPerShare": float(data.get("divPerShare", 0)),
            "rating": data.get("rating", "HOLD"),
            "note": data.get("note", "")
        }
        _rrsp_store.append(new_holding)
        persist()
        return jsonify({"ok": True, "holding": new_holding})

@app.route("/api/rrsp/holding/<int:hid>", methods=["DELETE"])
def delete_holding(hid):
    global _rrsp_store
    _rrsp_store = [h for h in _rrsp_store if h["id"] != hid]
    persist()
    return jsonify({"ok": True})

@app.route("/api/rrsp/meta", methods=["POST"])
def update_rrsp_meta():
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400
    global _rrsp_meta
    _rrsp_meta = {**_rrsp_meta, **data}
    persist()
    return jsonify({"ok": True, "meta": _rrsp_meta})

# ── Swing Watchlist API ─────────────────────────────────────────────
@app.route("/api/swing")
def get_swing():
    return jsonify({"watchlist": _swing_store})

@app.route("/api/swing/ticker", methods=["POST"])
def add_or_update_swing():
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400
    ticker = data.get("ticker", "").upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    for i, t in enumerate(_swing_store):
        if t["ticker"] == ticker:
            _swing_store[i] = {**t, **data, "ticker": ticker}
            persist()
            return jsonify({"ok": True, "ticker": _swing_store[i]})
    _swing_store.append({**data, "ticker": ticker})
    persist()
    return jsonify({"ok": True, "ticker": data})

@app.route("/api/swing/ticker/<ticker>", methods=["DELETE"])
def delete_swing(ticker):
    global _swing_store
    _swing_store = [t for t in _swing_store if t["ticker"] != ticker.upper()]
    persist()
    return jsonify({"ok": True})

# ── Old chart route (kept for backward compat) ─────────────────────
@app.route("/chart")
def chart():
    return render_template("app.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
