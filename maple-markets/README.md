# maple-markets

ZeroProfit Trading Infrastructure — GEX system for ES/NQ futures.

## Architecture

```
LAPTOP ON (real-time):
  Moomoo OpenD → gex/moomoo_relay.py → compute GEX → POST to Render

LAPTOP OFF (fallback):
  GitHub Actions (5x/day) → gex/flashalpha_fallback.py → POST to Render

RENDER (always-on relay):
  app.py → serves /api/gex (JSON) + /chart (Lightweight Charts)
```

## Setup

### 1. Render (auto-deploys from this repo)
Set these environment variables in Render dashboard:
- `GEX_PUSH_KEY` — a secret key (make one up, e.g. `mySecretKey123`)

### 2. GitHub Secrets (for Actions fallback)
In repo Settings → Secrets → Actions, add:
- `FLASHALPHA_API_KEY` — your FlashAlpha API key
- `RENDER_URL` — `https://maple-markets.onrender.com`
- `GEX_PUSH_KEY` — same key as Render env var

### 3. Laptop (Moomoo real-time engine)
```bash
# Clone repo
git clone https://github.com/K3rnelninja/maple-markets.git
cd maple-markets

# Create venv
python3 -m venv venv
source venv/bin/activate

# Install deps
pip install moomoo-api requests numpy scipy

# Set env vars
export RENDER_URL="https://maple-markets.onrender.com"
export GEX_PUSH_KEY="your-secret-key"
export OPEND_HOST="127.0.0.1"
export OPEND_PORT="11111"
export GEX_INTERVAL="600"  # 10 minutes

# Ensure OpenD is running, then:
python -m gex.moomoo_relay
```

### 4. View GEX
- Chart: https://maple-markets.onrender.com/chart
- API: https://maple-markets.onrender.com/api/gex
- iPhone: open /chart in Safari, add to Home Screen

## Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | none | Landing page |
| `/chart` | GET | none | Lightweight Charts GEX overlay |
| `/api/gex` | GET | none | Latest GEX JSON |
| `/api/gex` | POST | X-Api-Key | Push new GEX data |
| `/health` | GET | none | Health check |

## Future modules
- `/api/signals` — VectorVest-style day/swing scoring with TP/SL
- `/api/rrsp` — Dividend portfolio tracker ($50/mo CAD)
