"""
maple-markets — GEX relay + dashboard
Render deployment: maple-markets.onrender.com
GitHub: K3rnelninja/maple-markets
"""

import os
import json
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

# ── In-memory GEX store (survives until Render restarts) ────────────────
_gex_store = {
    "es": None,
    "nq": None,
    "updated_at": None,
    "source": None,
}


# ── Health check ────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "updated_at": _gex_store["updated_at"]})


# ── GET GEX data (Pine Script / Expo app / Lightweight Charts read this)
@app.route("/api/gex")
def get_gex():
    if _gex_store["es"] is None:
        return jsonify({"error": "no data yet", "stale": True}), 200

    now = datetime.now(timezone.utc)
    updated = _gex_store["updated_at"]
    stale = True
    if updated:
        try:
            age_seconds = (now - datetime.fromisoformat(updated)).total_seconds()
            stale = age_seconds > 900  # stale if > 15 min old
        except Exception:
            stale = True

    return jsonify({
        "es": _gex_store["es"],
        "nq": _gex_store["nq"],
        "updated_at": _gex_store["updated_at"],
        "source": _gex_store["source"],
        "stale": stale,
    })


# ── POST GEX data (laptop GEX engine + GitHub Actions push here) ───────
@app.route("/api/gex", methods=["POST"])
def post_gex():
    auth = request.headers.get("X-Api-Key", "")
    expected = os.environ.get("GEX_PUSH_KEY", "zeroprofit-default-key")
    if auth != expected:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "no JSON body"}), 400

    _gex_store["es"] = data.get("es")
    _gex_store["nq"] = data.get("nq")
    _gex_store["source"] = data.get("source", "unknown")
    _gex_store["updated_at"] = datetime.now(timezone.utc).isoformat()

    return jsonify({"status": "ok", "updated_at": _gex_store["updated_at"]})


# ── Lightweight Charts page (auto-updating GEX overlay) ─────────────────
@app.route("/chart")
def chart():
    return render_template("chart.html")


# ── Run ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
