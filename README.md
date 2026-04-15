# Portfolio Tracker

A personal portfolio app for tracking stock and cryptocurrency holdings with real-time prices, analytics, and German tax estimates.

## Features

- **Authentication** — Email-based registration and login
- **Stock & Crypto tracking** — Buy/sell transactions with full history, filtering, sorting, and pagination
- **Real-time prices** — Finnhub WebSocket for crypto, REST polling every 15s for stocks (free-tier limitation)
- **Live dashboard** — Portfolio value updates in real-time via browser WebSocket
- **Allocation charts** — Donut charts on dashboard, stock list, and crypto list pages
- **Analytics** — Weighted-average cost basis, unrealized/realized P&L, sell/buy targets with custom % simulator
- **Price alerts** — DB-backed alerts on target prices, checked on every price tick via Redis cache (zero DB polling)
- **German tax estimates** — Kapitalertragsteuer for stocks (26.375% + Freibetrag), FIFO holding-period rules for crypto (Freigrenze + 1-year tax-free)
- **EUR/USD toggle** — Enter prices in EUR (auto-converts to USD), view analytics/tax in EUR using ECB rates
- **Market status** — NYSE open/closed indicator with countdown timer
- **Market caps** — Fetched from Finnhub (stocks) and CoinGecko (crypto)

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0, Celery 5.4, Django Channels |
| Frontend | Django Templates, Bootstrap 5.3 |
| Database | SQLite |
| Cache / Broker | Redis |
| Real-time | Finnhub WebSocket + REST API, CoinGecko, Frankfurter (ECB rates) |

## Setup

**Prerequisites:** Python 3.12+, Redis

```bash
# Clone and enter the project
git clone <repo-url> && cd portfolio

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements/base.txt

# Configure environment
cp config/.env.sample config/.env
# Edit config/.env — set SECRET_KEY and FINNHUB_API_KEY (free key from finnhub.io)

# Run migrations and create superuser
./setup.sh
```

## Running

Start everything with one command:

```bash
./start.sh
```

This launches Redis, Celery worker, and Django dev server. Press `Ctrl+C` to stop all services.

Open **http://127.0.0.1:8000/** in your browser.

Logs:
- Celery: `tail -f /tmp/folio_celery.log`
- Server: `tail -f /tmp/folio_server.log`

## Database Schema

| Model | Description |
|---|---|
| **User** | Custom user with UUID, email-based auth, birthdate |
| **Stock / Crypto** | Master asset table — name, symbol, finnhub_symbol |
| **StockAsset / CryptoAsset** | Buy/sell transactions — user, asset FK, price, amount, date, status |
| **PriceAlert** | Target price alerts — user, asset FK, target_price, direction (above/below), email_sent |

## Environment Variables

See `config/.env.sample` for all options. Key ones:

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Django secret key |
| `FINNHUB_API_KEY` | Yes | Free API key from [finnhub.io](https://finnhub.io/) |
| `DEBUG` | No | `True` for development (default: `False`) |
| `ALLOWED_HOSTS` | No | Comma-separated hostnames (default: none) |
