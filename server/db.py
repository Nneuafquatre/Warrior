"""SQLite storage for the booking system.

All date-times are stored as local shop time (Europe/Stockholm) in the form
"YYYY-MM-DDTHH:MM". That format sorts correctly as plain text, so overlap
checks can be done directly in SQL.
"""
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("WARRIOR_DB") or ROOT / "data" / "warrior.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    duration_min INTEGER NOT NULL CHECK (duration_min BETWEEN 5 AND 480),
    price_sek    INTEGER NOT NULL CHECK (price_sek >= 0),
    active       INTEGER NOT NULL DEFAULT 1,
    sort         INTEGER NOT NULL DEFAULT 0
);

-- Regular week. weekday: 0 = Monday ... 6 = Sunday.
CREATE TABLE IF NOT EXISTS weekly_hours (
    weekday    INTEGER PRIMARY KEY CHECK (weekday BETWEEN 0 AND 6),
    open_time  TEXT NOT NULL DEFAULT '10:00',
    close_time TEXT NOT NULL DEFAULT '19:00',
    closed     INTEGER NOT NULL DEFAULT 0
);

-- A single date with different hours (or closed) than the regular week.
CREATE TABLE IF NOT EXISTS date_overrides (
    day        TEXT PRIMARY KEY,
    open_time  TEXT,
    close_time TEXT,
    closed     INTEGER NOT NULL DEFAULT 0,
    note       TEXT NOT NULL DEFAULT ''
);

-- Blocked time inside opening hours: lunch, errands, vacation.
CREATE TABLE IF NOT EXISTS time_off (
    id       INTEGER PRIMARY KEY,
    start_at TEXT NOT NULL,
    end_at   TEXT NOT NULL,
    note     TEXT NOT NULL DEFAULT '',
    CHECK (end_at > start_at)
);

CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY,
    service_id    INTEGER NOT NULL REFERENCES services(id),
    start_at      TEXT NOT NULL,
    end_at        TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    phone         TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled')),
    source        TEXT NOT NULL DEFAULT 'web' CHECK (source IN ('web', 'admin')),
    token         TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL,
    CHECK (end_at > start_at)
);
CREATE INDEX IF NOT EXISTS bookings_start ON bookings (start_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "slot_step_min": "15",      # how often a bookable start time is offered
    "min_notice_min": "60",     # latest a customer can book before the start
    "max_days_ahead": "60",     # how far ahead customers can book
    "cancel_notice_min": "120", # latest a customer can cancel or rebook online
}

# Opening hours taken from the old site.
DEFAULT_HOURS = [
    (0, "10:00", "19:00"), (1, "10:00", "19:00"), (2, "10:00", "19:00"),
    (3, "10:00", "19:00"), (4, "10:00", "19:00"),
    (5, "11:00", "17:00"), (6, "12:00", "16:00"),
]


def connect() -> sqlite3.Connection:
    # isolation_level=None: we open transactions ourselves with BEGIN IMMEDIATE.
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        for weekday, open_time, close_time in DEFAULT_HOURS:
            conn.execute(
                "INSERT OR IGNORE INTO weekly_hours (weekday, open_time, close_time) VALUES (?, ?, ?)",
                (weekday, open_time, close_time),
            )
        if conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO services (name, description, duration_min, price_sek, sort) VALUES (?, ?, ?, ?, ?)",
                ("Klippning", "Valfri frisyr. Skägg, ögonbryn och mustasch ingår.", 30, 200, 1),
            )
        conn.execute("COMMIT")
    finally:
        conn.close()


def get_settings(conn: sqlite3.Connection) -> dict:
    values = dict(DEFAULT_SETTINGS)
    values.update({row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")})
    return {key: int(value) for key, value in values.items()}
