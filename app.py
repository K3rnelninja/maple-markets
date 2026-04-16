"""
maple-markets v2.0 — Trading Dashboard + API
Render deployment: maple-markets.onrender.com
GitHub: K3rnelninja/maple-markets
"""
import os
import json
import time
import requests as req_lib
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template, send_from_directory

app = Flask(__name__, static_folder='static', template_folder='templates')

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

# ── Old chart route (kept for backward compat) ─────────────────────
@app.route("/chart")
def chart():
    return render_template("app.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
