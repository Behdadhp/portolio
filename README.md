# Portfolio App

A web application for tracking your stock and cryptocurrency assets. Built with Django.

## Features

- User registration and login with email and password
- Password hashing for secure storage
- Personal dashboard showing user information
- Separate pages for viewing stock and crypto assets
- Each user can only see their own assets

## Tech Stack

- **Backend:** Django 6.0, Celery 5.4, Django Channels (Daphne ASGI)
- **Frontend:** Django Templates, Bootstrap 5
- **Database:** SQLite
- **Cache / Message Broker / Channel Layer:** Redis
- **Real-time Data:** Finnhub WebSocket API → Celery → Channels → Browser WebSocket

## Database Schema

- **User** — UUID, first name, last name, email, birthdate, hashed password
- **CryptoAsset** — UUID, user (FK), crypto name, price, status (bought/sold)
- **StockAsset** — UUID, user (FK), stock name, price, status (bought/sold)

## How to Run

1. **Clone the repository and navigate to the project directory:**

   ```bash
   cd portfolio
   ```

2. **Create and activate a virtual environment:**

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**

   ```bash
   pip install -r requirements/base.txt
   ```

4. **Configure environment variables:**

   ```bash
   cp config/.env.sample config/.env
   ```

   Edit `config/.env` and set your values (secret key, admin credentials, etc).

5. **Run setup (migrations + superuser creation):**

   ```bash
   ./setup.sh
   ```

   Or manually:

   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

6. **Set your Finnhub API key:**

   Get a free API key from [finnhub.io](https://finnhub.io/) and set it in `config/.env`:

   ```
   FINNHUB_API_KEY=your-actual-api-key
   ```

7. **Start Redis:**

   ```bash
   brew install redis   # macOS (one-time)
   redis-server
   ```

8. **Start the Celery worker (in a separate terminal):**

   ```bash
   source venv/bin/activate
   celery -A portfolio_project worker --loglevel=info
   ```

   The price stream starts automatically when the worker is ready — no manual command needed. If the Finnhub connection drops, it reconnects automatically with exponential backoff. Prices are pushed to the browser via Django Channels in real-time.

9. **Start the development server (Daphne ASGI):**

   With `daphne` installed, `runserver` automatically uses the ASGI server, which supports WebSocket connections:

   ```bash
   python manage.py runserver
   ```

10. **Open your browser and go to:** `http://127.0.0.1:8000/`