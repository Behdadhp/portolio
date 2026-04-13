# Portfolio App

A web application for tracking your stock and cryptocurrency assets. Built with Django.

## Features

- User registration and login with email and password
- Password hashing for secure storage
- Personal dashboard showing user information
- Separate pages for viewing stock and crypto assets
- Each user can only see their own assets

## Tech Stack

- **Backend:** Django 6.0
- **Frontend:** Django Templates, Bootstrap 5
- **Database:** SQLite

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

6. **Start the development server:**

   ```bash
   python manage.py runserver
   ```

6. **Open your browser and go to:** `http://127.0.0.1:8000/`

## Pages

| URL | Description |
|---|---|
| `/` | Login page |
| `/register/` | Create a new account |
| `/dashboard/` | View your info and navigate to assets |
| `/stocks/` | View your stock assets |
| `/crypto/` | View your crypto assets |
