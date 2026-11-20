# Warrior Barbershop

Website and booking system for Warrior Barbershop, Långholmsgatan 11, Stockholm.

- **Site** (`public/`): plain HTML, CSS and JavaScript, in Swedish.
- **Backend** (`server/`): Python + Flask with a SQLite database (`data/warrior.db`).

## Run it locally

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
```

- Site: http://localhost:5000
- Admin: http://localhost:5000/admin

The first run creates a `.env` file with a random admin password (`ADMIN_PASSWORD`).
Change it there if you like, then restart. `.env` and `data/` are never committed.

## What it does

**Customers** pick a service, a day and a free time, and leave name and mobile number.
They get a private link (`/bokning?t=...`) where they can rebook or cancel.

**The barber** logs in at `/admin`:

- **Bokningar** – day and week view, add a booking (also outside opening hours),
  rebook, edit, cancel and restore.
- **Schema** – regular weekly hours, single days with other hours or closed,
  blocked time (lunch, vacation) and the booking rules.
- **Tjänster** – name, length, price, and whether it can be booked online.

Two bookings can never overlap: the check and the save happen in one database
transaction.

## E-mail confirmations

Off until `SMTP_HOST` and the other `SMTP_*` values are filled in `.env`.
Set `NOTIFY_EMAIL` to give the barber a copy of every booking and cancellation.

## Tests

```powershell
.venv\Scripts\python -m unittest -v
```

## Going live

GitHub Pages cannot run the backend, so the site needs a host that runs Python
and keeps the `data/` folder on a persistent disk. In production:

- run with `waitress-serve --port 8000 server.app:app` instead of `run.py`
- serve over https and set `COOKIE_SECURE=1` and `PUBLIC_URL=https://warriorbarbershop.com`
- back up `data/warrior.db` regularly
